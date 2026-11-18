"""Rerun the frozen assignments held by the first Exp7 controller."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import time

from exp7_backup_v1.sidecar import verify_private_repository
from exp7_cards.queued_retry_audit import audit_queued_trial
from exp7_cards.queued_retry_runner import run_trial
from exp7_cards.queued_retry_transport import QueuedRetryTransport
from exp7_main_v2.storage import disk_guard
from exp7_pre.runner import CallBudget, atomic_json, now
from .main_backup import PrivateGitBackup, archive_conversation, sha
from .main_controller import ASSIGNMENTS, ASSIGNMENTS_SHA, BOARD, RAW, RAW_BRANCH, REMOTE, REPO, RUN_ID
from .main_schedule import load
from .main_status import RemoteControl, StatusDB
from .protocol import ZeroCardProtocol
from .rolling_dispatch import dispatch


def read_json(path):
    return json.loads(path.read_text())


def process_identity(pid):
    proc = Path('/proc') / str(pid)
    args = (proc / 'cmdline').read_bytes().split(b'\0')
    status = dict(line.split(':', 1) for line in (proc / 'status').read_text().splitlines() if ':' in line)
    return args, status


def retire_controller(root, pid, records):
    """Stop only the original, paused controller and its identified trial children."""
    children = []
    controller = os.pidfd_open(pid)
    try:
        args, status = process_identity(pid)
        if (b'exp7_cards_zero.main_controller' not in args or
                os.fsencode(root) not in args or not status['State'].strip().startswith('T ')):
            raise RuntimeError('Original controller must be confirmed paused')
        expected = {
            b'model_instructions_file=' + json.dumps(
                str(root / 'native' / record['scratch_id'] / 'subject-system.txt')
            ).encode(): record for record in records
        }
        found = set()
        for entry in Path('/proc').iterdir():
            if not entry.name.isdecimal():
                continue
            child_pid = int(entry.name)
            try:
                child_args, child_status = process_identity(child_pid)
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
            if int(child_status['PPid']) != pid or b'app-server' not in child_args:
                continue
            matches = set(child_args) & expected.keys()
            if len(matches) != 1 or matches & found:
                raise RuntimeError('Original child identity could not be confirmed')
            system_arg = matches.pop()
            record = expected[system_arg]
            if record['turns'] and child_pid != record['turns'][-1]['process_pid']:
                raise RuntimeError('Original child PID differs from its checkpoint')
            found.add(system_arg)
            try:
                children.append(os.pidfd_open(child_pid))
            except ProcessLookupError:
                pass
        signal.pidfd_send_signal(controller, signal.SIGKILL)
        for child in children:
            try:
                signal.pidfd_send_signal(child, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for descriptor in [controller, *children]:
            poller = select.poll()
            poller.register(descriptor, select.POLLIN)
            if not poller.poll(500):
                try:
                    signal.pidfd_send_signal(descriptor, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                if not poller.poll(2000):
                    raise RuntimeError('Original process did not exit')
    finally:
        for descriptor in [controller, *children]:
            os.close(descriptor)


def preserve_attempt(root, directory, record):
    """Keep byte-identical original checkpoints and a verified raw archive."""
    ident = record['trial']['trial_id']
    item = archive_conversation(root, ident, record['scratch_id'])
    archive = directory / 'archives' / (ident + '.tar.gz')
    Path(item['archive']).rename(archive)
    item['archive'] = str(archive)
    for suffix in ('.json', '.journal.jsonl', '.json.lock', '.json.queued.lock'):
        source = root / 'states' / (ident + suffix)
        if source.exists():
            source.rename(directory / 'states' / source.name)
    return item


def primary_is_live(root, pid):
    args, status = process_identity(pid)
    if (b'exp7_cards_zero.main_resume' not in args or os.fsencode(root) not in args
            or status['State'].strip()[0] in 'TtZ'):
        raise RuntimeError('The primary collection and backup controller is unavailable')


def back_up_excluded(root):
    directory = root / 'replacements'
    items = read_json(directory / 'exclusions.json')['archives']
    profile = read_json(root / 'profile.json')
    if verify_private_repository(RAW)['id'] != profile['private_repository_id']:
        raise RuntimeError('Private repository identity changed')
    store = PrivateGitBackup(directory / 'excluded-backup.git', 'https://github.com/' + RAW + '.git',
                             RAW_BRANCH + '-excluded-attempts')
    commits = []
    for start in range(0, len(items), 20):
        batch = items[start:start + 20]
        for attempt in range(3):
            try:
                commits.append(store.upload(batch))
                break
            except (RuntimeError, OSError, subprocess.SubprocessError):
                if attempt == 2:
                    raise
                time.sleep(5)
    atomic_json(directory / 'excluded-backup-receipt.json', {'count': len(items), 'commits': commits})


def rerun(root, primary_pid, slots):
    directory = root / 'replacements'
    if directory.exists():
        raise FileExistsError('A replacement operation already exists')
    primary_is_live(root, primary_pid)
    disk_guard(root)
    assignments = load(ASSIGNMENTS, ASSIGNMENTS_SHA)
    db = StatusDB.attach(root / 'status.sqlite', assignments)
    rows = db.db.execute(
        "SELECT id FROM trials WHERE wave='wave-1' AND status='held' AND error='previous_controller_paused'"
    ).fetchall()
    ids = {row[0] for row in rows}
    takeover = read_json(root / 'recovery-takeover.json')
    recovery_profile = read_json(root / 'recovery-profile.json')
    held_hash = hashlib.sha256('\n'.join(sorted(ids)).encode()).hexdigest()
    if len(ids) != takeover['held_count'] or held_hash != recovery_profile['held_trial_ids_sha256']:
        raise RuntimeError('The held assignments no longer match the recovery record')
    trials = [trial for trial in assignments if trial['trial_id'] in ids]
    records = [read_json(root / 'states' / (trial['trial_id'] + '.json')) for trial in trials]
    original_freeze = sha(root / 'profile.json')
    for trial, record in zip(trials, records, strict=True):
        if (record['trial'] != trial or record['freeze_sha256'] != original_freeze or
                record['status'] != 'active' or not record['pending_turn']):
            raise RuntimeError('Original checkpoint differs from the held assignment')
        if not (root / 'states' / (trial['trial_id'] + '.journal.jsonl')).is_file():
            raise RuntimeError('Original journal is missing')
        if not (root / 'native' / record['scratch_id']).is_dir():
            raise RuntimeError('Original native directory is missing')

    source = subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(
        ['git', '-C', str(REPO), 'status', '--porcelain', '--untracked-files=no'], text=True
    )
    if dirty:
        raise RuntimeError('Replacement controller source is not frozen')
    catalog = root / 'catalog.json'
    if sha(catalog) != read_json(root / 'profile.json')['catalog_sha256']:
        raise RuntimeError('Model catalog changed')
    directory.mkdir(mode=0o700)
    (directory / 'archives').mkdir()
    (directory / 'states').mkdir()
    with (directory / 'operator.lock').open('xb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        control = RemoteControl(REMOTE, BOARD, directory / 'control.git', RUN_ID)
        if not control.check_once():
            raise RuntimeError('The dashboard has paused collection')
        atomic_json(directory / 'plan.json', {
            'source_commit': source, 'original_freeze_sha256': original_freeze,
            'recovery_freeze_sha256': sha(root / 'recovery-profile.json'),
            'assignment_sha256': ASSIGNMENTS_SHA, 'slots': slots, 'prepared_at': now(),
            'basis': 'Backup error remained after resuming the original controller.',
            'original_attempt': 'Exclude interrupted session and retain its raw archive.',
            'replacement_attempts': [trial['trial_id'] for trial in trials],
        })
        retire_controller(root, takeover['previous_controller_pid'], records)
        items = [preserve_attempt(root, directory, record) for record in records]
        atomic_json(directory / 'exclusions.json', {'recorded_at': now(), 'archives': items})
        freeze = sha(directory / 'plan.json')
        transport = QueuedRetryTransport(
            timeout=180, codex_binary=str(root / 'codex-main'), catalog_path=catalog
        )
        budget = CallBudget(directory / 'budget.json', RUN_ID + '-replacement-turns', len(trials) * 34)

        def before_send():
            while True:
                try:
                    primary_is_live(root, primary_pid)
                    disk_guard(root)
                    progress = read_json(root / 'recovery-progress.json')
                    if control.check_once() and not progress['backup_error']:
                        return
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                    pass
                time.sleep(2)

        transport.before_send = before_send

        def finish(trial, record):
            ident = trial['trial_id']
            count = len(record['turns'])
            if record['status'] == 'complete':
                audit = audit_queued_trial(trial, ZeroCardProtocol(), root / 'states' / (ident + '.json'), freeze)
                if not audit['integrity_ok']:
                    db.update(ident, 'held', turns=count, error='replacement_audit_failed')
                    return {'status': 'held'}
                status = 'complete'
            elif record['status'] == 'failed' and record.get('failure_kind') == 'process_exited':
                status = 'failed'
            else:
                db.update(ident, 'held', turns=count, error='replacement_session_held')
                return {'status': 'held'}
            item = archive_conversation(root, ident, record['scratch_id'])
            # The existing private backup worker remains the sole publisher to the main raw branch.
            db.update(ident, status + '_pending_backup', turns=count, archive=item['archive'],
                      archive_sha=item['sha256'], archive_bytes=item['bytes'], scratch=record['scratch_id'])
            return {'status': status, 'trial_id': ident}

        def run_one(trial):
            ident = trial['trial_id']
            path = root / 'states' / (ident + '.json')
            if path.exists() or db.resume_snapshot()[ident] != 'held':
                raise RuntimeError('Replacement assignment is already claimed')
            db.update(ident, 'active', error=None)
            try:
                record = run_trial(trial, ZeroCardProtocol(), transport, path, root / 'native', budget, freeze)
                return finish(trial, record)
            except Exception:
                db.update(ident, 'held', error='replacement_controller_error')
                raise

        def reconcile(trial):
            ident = trial['trial_id']
            path = root / 'states' / (ident + '.json')
            if path.exists():
                record = read_json(path)
                if (record['status'] == 'failed' and record.get('failure_kind') == 'process_exited'
                        and ident not in transport.held_processes):
                    return finish(trial, record)
            return None

        def progress(done, held, active, errors):
            atomic_json(directory / 'progress.json', {
                'updated_at': now(), 'total': len(trials), 'finished': len(done),
                'active': len(active), 'held': len(held), 'exceptions': errors,
                'success': transport.attempt_counts['success'], 'rpc_429': transport.attempt_counts['rpc_429'],
            })

        try:
            dispatch(trials, slots, run_one, reconcile, progress, poll_seconds=3)
        finally:
            if not transport.held_processes:
                transport.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--primary-pid', type=int)
    mode.add_argument('--back-up-excluded', action='store_true')
    parser.add_argument('--slots', type=int, choices=range(1, 15), default=7)
    options = parser.parse_args()
    if options.back_up_excluded:
        back_up_excluded(options.root.resolve())
    else:
        rerun(options.root.resolve(), options.primary_pid, options.slots)
