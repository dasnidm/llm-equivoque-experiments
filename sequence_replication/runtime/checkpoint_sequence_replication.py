"""Publish audited byte snapshots without changing live trial files or requests."""
import collections
import datetime
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(ROOT))
from equivoque.core import read_json, write_json, digest
from equivoque2.runner import archive_native
from sequence_replication.audit import audit_worker
from sequence_replication.protocol import CONFIG, FREEZE, frozen_hashes

config = read_json(CONFIG)
RUN = config['run_id']
control = ROOT / 'work/checkpoint-control' / RUN
control.mkdir(parents=True, exist_ok=True)
lock = (control / 'publisher.lock').open('a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
paused_pid = None


def stop(signum, frame):
    raise KeyboardInterrupt


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)


def git(tree, *args, **kwargs):
    result = subprocess.run(['git', '-C', str(tree), *args], capture_output=True, text=True,
               env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'}, **kwargs)
    if result.returncode:
        raise RuntimeError('git ' + args[0] + ': ' + result.stderr[:500])
    return result.stdout.strip()


def snapshot_worker(w, snapshot):
    tree = ROOT / 'work/worker-trees' / RUN / w
    live = tree / 'results' / RUN / ('worker-' + w)
    dest = snapshot / 'results' / RUN / ('worker-' + w)
    for attempt in range(5):
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(live, dest, ignore=shutil.ignore_patterns('*.lock', '*.tmp'))
        changed = False
        for path in sorted((dest / 'trials').glob('*.json')):
            state = read_json(path)
            if state['status'] != 'active':
                continue
            original = live / 'trials' / path.name
            if path.read_bytes() != original.read_bytes():
                changed = True; break
            if not state['turns'] and state.get('pending_turn') is None:
                # A request-limited executor can initialize a case while still
                # waiting for its first slot. Preserve that ownership record
                # separately; no native bytes or model invocation exist yet.
                claims = dest / 'unrequested-claims'
                claims.mkdir(exist_ok=True)
                shutil.move(str(path), str(claims / path.name))
                continue
            native = Path(config['subject_scratch_root']) / state['scratch_id']
            archive = dest / 'native-raw' / state['trial']['trial_id'].replace('/', '__')
            if not native.exists():
                changed = True; break
            # The current request's stdout may be an unfinished prefix. Preserve
            # it as pending bytes, never as a completed response or new request.
            pending_files = archive_native(native, archive, dest)
            if path.read_bytes() != original.read_bytes():
                changed = True; break
            state['checkpoint_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            state['pending_raw_files'] = pending_files
            write_json(path, state)
        if changed:
            time.sleep(.2); continue
        try:
            audit = audit_worker(tree / 'manifests' / RUN / f'worker-{w}.json', dest)
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            time.sleep(.2); continue
        if not audit['integrity_ok']:
            time.sleep(.2); continue
        write_json(dest / 'CHECKPOINT.json', {'run_id': RUN, 'worker_id': w,
                   'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   'provisional': True, 'freeze_sha256': digest(FREEZE), 'audit': audit,
                   'note': 'Active or pending snapshots are not completion claims. Do not replay a recorded pending request.'})
        # Separate snapshot files form the index; live raw files are not changed.
        git(tree, '--work-tree=' + str(snapshot), 'add', '--sparse', '--', 'results/' + RUN + '/worker-' + w)
        git(tree, 'commit', '-m', 'Checkpoint sequence replication worker ' + w.upper())
        return {'worker': w, 'head': git(tree, 'rev-parse', 'HEAD'),
                'counts': audit['counts'], 'invocations': audit['subject_invocations'],
                'raw_integrity_ok': True}
    raise RuntimeError('Could not obtain a consistent raw snapshot for worker ' + w)


def checkpoint():
    global paused_pid
    frozen_hashes()
    status = read_json(ROOT / 'sequence_replication/runtime/supervisor-status.json')
    if status['stage'] != 'collecting':
        return False
    pid = status['pid']
    if b'run_sequence_replication.py' not in Path('/proc/' + str(pid) + '/cmdline').read_bytes():
        raise RuntimeError('Supervisor PID no longer identifies this run')
    # Only the orchestration parent waits briefly; its collecting coordinator,
    # all ten workers and native CLI children continue without interruption.
    os.kill(pid, signal.SIGSTOP); paused_pid = pid
    try:
        if read_json(ROOT / 'sequence_replication/runtime/supervisor-status.json')['stage'] != 'collecting':
            return False
        summaries = []
        with tempfile.TemporaryDirectory(prefix='snapshot-', dir=control) as tmp:
            for w in config['workers']:
                summaries.append(snapshot_worker(w, Path(tmp) / w))
        refs = ['worker/' + RUN + '/' + w for w in config['workers']]
        git(ROOT, 'push', 'origin', *refs)
        record = {'run_id': RUN, 'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'workers': summaries, 'published': True, 'provisional': True}
        write_json(ROOT / 'sequence_replication/runtime/remote-checkpoint.json', record)
        print(json.dumps({'event': 'checkpoint_published', 'workers': len(summaries),
                         'invocations_snapshotted': sum(s['invocations'] for s in summaries)}), flush=True)
        return True
    finally:
        if paused_pid is not None:
            os.kill(paused_pid, signal.SIGCONT); paused_pid = None


try:
    if '--once' in sys.argv:
        checkpoint()
    else:
        delay_first = '--delay-first' in sys.argv
        while True:
            status = read_json(ROOT / 'sequence_replication/runtime/supervisor-status.json')
            if status['stage'] != 'collecting':
                break
            write_json(control / 'publisher-status.json', {'pid': os.getpid(), 'run_id': RUN,
                'at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'stage': 'sleeping' if delay_first else 'checkpoint'})
            if not delay_first:
                try:
                    if not checkpoint(): break
                except Exception as error:
                    print(json.dumps({'event': 'checkpoint_failed', 'error': str(error)}), flush=True)
            delay_first = False
            for _ in range(120):
                time.sleep(5)
                if read_json(ROOT / 'sequence_replication/runtime/supervisor-status.json')['stage'] != 'collecting':
                    raise SystemExit(0)
finally:
    if paused_pid is not None:
        os.kill(paused_pid, signal.SIGCONT)
