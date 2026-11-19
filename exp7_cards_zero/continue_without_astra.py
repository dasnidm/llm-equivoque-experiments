"""Continue wave one with six models after draining and parking the old controllers."""
import argparse
from collections import Counter
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time

from exp7_backup_v1.sidecar import verify_private_repository
from exp7_cards.queued_retry_audit import audit_queued_trial
from exp7_cards.queued_retry_runner import run_trial
from exp7_cards.queued_retry_transport import QueuedRetryTransport
from exp7_main_v2.storage import disk_guard
from exp7_pre.runner import CallBudget, atomic_json, now
from .main_backup import PrivateGitBackup, archive_conversation, sha
from .main_controller import ASSIGNMENTS, ASSIGNMENTS_SHA, BOARD, RAW, RAW_BRANCH, REMOTE, REPO, RUN_ID, BackupThread
from .main_schedule import load
from .main_status import Dashboard, RemoteControl, StatusDB, render
from .protocol import ZeroCardProtocol
from .rerun_held import process_identity, read_json
from .rolling_dispatch import dispatch

PAUSED_MODEL = 'gpt-6-astra'
BINARY = b'/opt/codex/bin/codex'


def old_children(root, controllers):
    found = {}
    prefix = b'model_instructions_file='
    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            args, status = process_identity(int(entry.name))
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        if int(status['PPid']) not in controllers or b'app-server' not in args:
            continue
        for option in args:
            if not option.startswith(prefix):
                continue
            path = Path(json.loads(option[len(prefix):]))
            if path.name != 'subject-system.txt' or path.parent.parent != root / 'native':
                raise RuntimeError('Unexpected native child of an old controller')
            if path.parent.name in found:
                raise RuntimeError('Two native children share a scratch directory')
            found[path.parent.name] = (int(entry.name), args[0] == BINARY, status['State'].strip()[0])
    return found


def active_checkpoints(db, root):
    with db.lock:
        rows = db.db.execute("SELECT id,model FROM trials WHERE status='active'").fetchall()
    result = {}
    for ident, model in rows:
        path = root / 'states' / (ident + '.json')
        result[ident] = (model, read_json(path) if path.exists() else None)
    return result


def startup_only(root, record):
    if not record or record['turns'] or record.get('session_id'):
        return False
    native = root / 'native' / record['scratch_id']
    for path in native.glob('turn-*-attempt-*/rpc-sent.jsonl'):
        if any(json.loads(line).get('method') in ('thread/start', 'turn/start')
               for line in path.read_bytes().splitlines()):
            return False
    return True


def classify(root, controllers, checkpoints):
    children = old_children(root, controllers)
    parked, startup, draining = {}, {}, []
    for ident, (model, record) in checkpoints.items():
        child = children.get(record['scratch_id']) if record else None
        if child and child[1] and model == PAUSED_MODEL:
            pid, _, state = child
            if state not in 'Tt':
                raise RuntimeError('Astra CLI is still running')
            parked[ident] = pid
        elif child and not child[1] and startup_only(root, record):
            startup[ident] = child[0]
        else:
            draining.append(ident)
    return parked, startup, draining


def park_old_controllers(root, directory, db):
    fence = read_json(directory / 'fence.json')
    controllers = fence['controllers']
    for pid, expected in zip(controllers, (b'exp7_cards_zero.main_resume', b'exp7_cards_zero.rerun_held'), strict=True):
        args, _ = process_identity(pid)
        if expected not in args or os.fsencode(root) not in args:
            raise RuntimeError('Unexpected old controller identity')
    while True:
        active = active_checkpoints(db, root)
        parked, startup, draining = classify(root, controllers, active)
        atomic_json(directory / 'transition.json', {
            'at': now(), 'astra_parked': len(parked), 'startup_held': len(startup),
            'draining': len(draining), 'backup_pending': len(db.pending()),
        })
        if not draining and not db.pending():
            break
        time.sleep(2)

    stopped = []
    try:
        for pid in controllers:
            os.kill(pid, signal.SIGSTOP)
            stopped.append(pid)
        for pid in stopped:
            for _ in range(50):
                if process_identity(pid)[1]['State'].strip()[0] in 'Tt':
                    break
                time.sleep(.1)
            else:
                raise RuntimeError('Old controller did not pause')
        # A start or backup that raced with the snapshot must settle with its current owner.
        if (active_checkpoints(db, root) != active or classify(root, controllers, active) != (parked, startup, [])
                or db.pending()):
            raise RuntimeError('Run changed during handoff')
        store = PrivateGitBackup.reopen(root / 'backup.git', 'https://github.com/' + RAW + '.git', RAW_BRANCH)
    except Exception:
        for pid in stopped:
            os.kill(pid, signal.SIGCONT)
        raise

    evidence = directory / 'startup-evidence'
    evidence.mkdir()
    atomic_json(directory / 'handoff.json', {'at': now(), 'astra_parked': parked, 'blocked_startups': startup})
    # Blocked wrappers have never executed a CLI or made a model request. Preserve
    # their checkpoints and retire the wrapper before releasing each assignment.
    for ident, pid in startup.items():
        args, _ = process_identity(pid)
        if args[0] == BINARY or not startup_only(root, active[ident][1]):
            raise RuntimeError('Startup attempted to submit a request')
        fd = os.pidfd_open(pid)
        try:
            signal.pidfd_send_signal(fd, signal.SIGTERM)
        finally:
            os.close(fd)
        for suffix in ('.json', '.journal.jsonl', '.json.lock', '.json.queued.lock'):
            source = root / 'states' / (ident + suffix)
            if source.exists():
                source.rename(evidence / source.name)
        db.update(ident, 'unstarted', turns=0, error=None)
    for ident in parked:
        db.update(ident, 'held', turns=len(active[ident][1]['turns']), error='astra_operator_pause')
    return store, parked


def starts_before_handoff(root, dashboard):
    board = (dashboard.repo / 'README.md').read_text()
    counters = Counter()
    retries = re.search(r'\| RPC 429 / 재대기 \| ([\d,]+) / ([\d,]+) \|', board)
    if retries:
        counters['rpc_429'], counters['requeued'] = (int(x.replace(',', '')) for x in retries.groups())
    previous_replacements = root / 'replacements'
    replacement_freeze = sha(previous_replacements / 'plan.json')
    counters['rpc_429'] += read_json(previous_replacements / 'progress.json')['rpc_429']
    for folder in (root / 'states', root / 'replacements' / 'states'):
        for path in folder.glob('*.json'):
            record = read_json(path)
            counters['success'] += sum(bool(t.get('ok')) for t in record['turns'])
            if record['freeze_sha256'] != replacement_freeze:
                continue
            counters['requeued'] += sum(t.get('retry_count', 0) for t in record['turns'])
            if record.get('pending_turn'):
                turn = record['pending_turn']['turn']
                journal = root / 'native' / record['scratch_id'] / f'turn-{turn:02d}-retries.journal.jsonl'
                if journal.exists():
                    counters['requeued'] += len(journal.read_bytes().splitlines())
    counters['retryable'] = max(counters['rpc_429'], counters['requeued'])
    return counters


def continue_run(root, dashboard_repo, slots):
    directory = root / 'astra-pause'
    with (directory / 'operator.lock').open('xb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        run_selected(root, directory, dashboard_repo, slots)


def run_selected(root, directory, dashboard_repo, slots):
    if subprocess.check_output(['git', '-C', str(REPO), 'status', '--porcelain', '--untracked-files=no']).strip():
        raise RuntimeError('Continuation source is not committed')
    source = subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True).strip()
    profile = read_json(root / 'profile.json')
    catalog = root / 'catalog.json'
    if profile['run_id'] != RUN_ID or sha(catalog) != profile['catalog_sha256']:
        raise RuntimeError('Run or catalog changed')
    repo = verify_private_repository(RAW)
    if repo['id'] != profile['private_repository_id']:
        raise RuntimeError('Private backup repository identity changed')
    disk_guard(root)
    trials = load(ASSIGNMENTS, ASSIGNMENTS_SHA)
    db = StatusDB.attach(root / 'status.sqlite', trials)
    control = RemoteControl(REMOTE, BOARD, directory / 'control.git', RUN_ID)
    if not control.check_once():
        raise RuntimeError('Collection is stopped on the dashboard')
    store, paused = park_old_controllers(root, directory, db)
    dashboard = Dashboard(dashboard_repo)
    dashboard.sync()
    baseline = starts_before_handoff(root, dashboard)
    atomic_json(directory / 'profile.json', {
        'source_commit': source, 'assignments_sha256': ASSIGNMENTS_SHA, 'paused_model': PAUSED_MODEL,
        'catalog_sha256': sha(catalog), 'wrapper_sha256': sha(root / 'codex-main'),
        'handoff_sha256': sha(directory / 'handoff.json'), 'original_profile_sha256': sha(root / 'profile.json'),
        'sessions': slots, 'created_at': now(), 'counter_baseline': dict(baseline),
    })
    freeze = sha(directory / 'profile.json')
    transport = QueuedRetryTransport(timeout=180, codex_binary=str(root / 'codex-main'), catalog_path=catalog)
    transport.attempt_counts.update(baseline)
    backup = BackupThread(root, db, store, repo['id'])
    budget = CallBudget(root / 'budget.json', RUN_ID, 8400 * 34)
    publish_stop = threading.Event()
    message = {'text': 'Astra 일시 중단 · 나머지 6개 모델 1차 수집 중', 'error': None}

    def before_send():
        while True:
            try:
                disk_guard(root)
                if control.check_once() and not backup.error and time.monotonic() - dashboard.last_success < 180:
                    return
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
                pass
            time.sleep(2)

    def publish():
        dashboard.publish(render(db, transport, message['text'], backup.error))
        message['error'] = None

    def publisher():
        while not publish_stop.wait(30):
            try:
                publish()
            except Exception as error:
                message['error'] = type(error).__name__

    def finish(trial, record):
        ident = trial['trial_id']
        count = len(record['turns'])
        status = record['status']
        if status == 'complete':
            audit = audit_queued_trial(trial, ZeroCardProtocol(), root / 'states' / (ident + '.json'), freeze)
            if not audit['integrity_ok']:
                db.update(ident, 'held', turns=count, error='integrity_audit_failed')
                return {'status': 'held'}
        elif status != 'failed' or record.get('failure_kind') != 'process_exited':
            db.update(ident, 'held', turns=count, error='session_not_terminal')
            return {'status': 'held'}
        item = archive_conversation(root, ident, record['scratch_id'])
        db.update(ident, status + '_pending_backup', turns=count, archive=item['archive'],
                  archive_sha=item['sha256'], archive_bytes=item['bytes'], scratch=record['scratch_id'])
        backup.wake.set()
        return {'status': status, 'trial_id': ident}

    def run_one(trial):
        ident = trial['trial_id']
        path = root / 'states' / (ident + '.json')
        if path.exists() or trial['model'] == PAUSED_MODEL:
            raise RuntimeError('Assignment already started or is paused')
        db.update(ident, 'active', error=None)
        try:
            return finish(trial, run_trial(trial, ZeroCardProtocol(), transport, path, root / 'native', budget, freeze))
        except Exception as error:
            db.update(ident, 'held', error=type(error).__name__)
            raise

    def reconcile(trial):
        ident = trial['trial_id']
        path = root / 'states' / (ident + '.json')
        if path.exists() and ident not in transport.held_processes:
            record = read_json(path)
            if record['status'] == 'failed' and record.get('failure_kind') == 'process_exited':
                return finish(trial, record)
        return None

    def progress(done, held, active, errors):
        atomic_json(directory / 'progress.json', {
            'at': now(), 'completed_this_controller': len(done), 'active': len(active),
            'astra_paused': len(paused), 'new_held': len(held), 'errors': errors,
            'backup_error': backup.error, 'dashboard_error': message['error'],
        })

    transport.before_send = before_send
    while True:
        try:
            publish()
            break
        except (RuntimeError, OSError, subprocess.SubprocessError):
            time.sleep(5)
    backup.start()
    publisher_thread = threading.Thread(target=publisher, daemon=True)
    publisher_thread.start()
    try:
        snapshot = db.resume_snapshot()
        selected = [t for t in trials if t['stage'] == 'wave-1' and t['model'] != PAUSED_MODEL
                    and snapshot[t['trial_id']] == 'unstarted']
        dispatch(selected, slots, run_one, reconcile, progress)
        while db.pending():
            backup.wake.set()
            time.sleep(3)
        message['text'] = '나머지 6개 모델 1차 종료 · Astra 일시 중단'
        publish()
    finally:
        publish_stop.set()
        backup.stopping.set()
        backup.wake.set()
        if not transport.held_processes:
            transport.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--dashboard', type=Path, required=True)
    parser.add_argument('--slots', type=int, choices=range(1, 43), default=42)
    args = parser.parse_args()
    continue_run(args.root.resolve(), args.dashboard.resolve(), args.slots)
