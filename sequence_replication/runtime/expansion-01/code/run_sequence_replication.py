"""Durable supervisor: gate, collect, audit, integrate, analyze and publish.

This operates only the frozen acquisition/analysis modules. It does not replay
requests, change assignments or substitute settings. A collection halt leaves
the live worktrees untouched for diagnosis rather than starting another run.
"""
import csv
import datetime
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile

ROOT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(ROOT))
from equivoque.core import read_json, write_json, digest
from sequence_replication.protocol import CONFIG, FREEZE, frozen_hashes

config = read_json(CONFIG)
RUN = config['run_id']
runtime = ROOT / 'sequence_replication/runtime'
logs = ROOT / 'work/execution-logs' / (RUN + '-expanded-01')
logs.mkdir(parents=True, exist_ok=True)
status_path = runtime / 'supervisor-status.json'
lock = (logs / 'supervisor.lock').open('a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def status(stage, **extra):
    write_json(status_path, {'run_id': RUN, 'pid': os.getpid(), 'stage': stage,
               'updated_at': stamp(), 'workers': len(config['workers']), **extra})
    print(json.dumps({'stage': stage, 'at': stamp(), **extra}), flush=True)


def command(name, args, cwd=ROOT, required=True):
    logfile = logs / (name + '.log')
    with logfile.open('x') as f:
        result = subprocess.run(args, cwd=cwd, stdout=f, stderr=f,
                    env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
    if required and result.returncode:
        raise RuntimeError(name + ' exited ' + str(result.returncode) + '; see ' + str(logfile))
    return result.returncode


def invocation_ledger(integration):
    rows = []
    roots = [(integration / 'results' / RUN / ('worker-' + w) / 'trials', 'evaluation')
             for w in config['workers']]
    for w in config['workers']:
        roots.append((integration / 'results' / RUN / ('worker-' + w) / 'preflight-01/check/trials', 'calibration'))
    roots += [(integration / 'sequence_replication/runtime/expansion-01/preflight-02/checks', 'calibration_expansion'),
              (integration / 'sequence_replication/runtime/shared-preflight-01/short', 'calibration'),
              (integration / 'sequence_replication/runtime/shared-preflight-01/long', 'calibration')]
    seen = set()
    for folder, scope in roots:
        for path in sorted(folder.rglob('*.json')):
            state = read_json(path)
            if 'trial' not in state or 'turns' not in state:
                continue
            trial = state['trial']
            for turn in state['turns'] + ([state['pending_turn']] if state.get('pending_turn') else []):
                key = (scope, trial['trial_id'], turn['turn'])
                if key in seen:
                    raise ValueError('Duplicate physical invocation ledger key')
                seen.add(key)
                rows.append({'scope': scope, 'trial_id': trial['trial_id'], 'turn': turn['turn'],
                             'model': trial['model'], 'effort': trial['effort'],
                             'session_id': turn.get('session_id', state.get('session_id')),
                             'requested_at': turn.get('requested_at'), 'ok': turn.get('ok')})
    rows.append({'scope': 'development_failed_auth', 'trial_id': 'access-diagnostic-01', 'turn': 1,
                 'model': 'gpt-6.1-sol', 'effort': 'low', 'session_id': None, 'requested_at': None, 'ok': False})
    return rows


try:
    frozen_hashes()
    operational = read_json(runtime / 'expansion-01/launch.json')
    if operational['study_freeze_sha256'] != digest(FREEZE):
        raise RuntimeError('Scientific source changed during expansion')
    status('collecting', evaluation_started=True, workers=20, maximum_workers=40,
           evaluation_sessions=config['sessions'], planned_invocations=config['planned_invocations'],
           operational_gate_sha256=digest(runtime / 'expansion-01/launch.json'),
           calibration_invocations=318 + operational['calibration_invocations'])
    result = command('collection-expanded-01', [sys.executable, str(ROOT / 'work/expansion/expanded.py'), 'coordinate'], required=False)
    progress = read_json(runtime / 'collection-progress.json')
    attempted = progress['complete'] + progress['failed'] + progress['interrupted']
    if result or progress['halted'] or attempted != config['sessions']:
        status('collection_halted', evaluation_started=True, progress=progress,
               reason='Preserve all requested turns; no automatic replay or replacement')
        raise SystemExit(2)
    status('finalizing', evaluation_started=True, complete=progress['complete'])
    process_logs = ROOT / 'work/process-logs' / RUN
    shutil.copytree(process_logs, runtime / 'process-logs', dirs_exist_ok=True)
    shutil.copytree(ROOT / 'work/expanded-logs' / RUN, runtime / 'expansion-01/process-logs', dirs_exist_ok=True)
    shutil.copytree(logs, runtime / 'supervisor-logs', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('*.lock', 'collection-01.log'))
    controls = ROOT / 'work/coordinator' / RUN
    shutil.copytree(controls, runtime / 'coordinator-controls', dirs_exist_ok=True)
    shutil.copytree(ROOT / 'work/expanded-controls' / RUN, runtime / 'expansion-01/controls', dirs_exist_ok=True)
    command('finalize-01', [sys.executable, '-m', 'sequence_replication.finalize'])
    integration = ROOT / 'work/integration-trees' / RUN
    relative = 'analysis/results/' + RUN + '/attempt-01'
    status('analyzing', integration_tree=str(integration), complete=progress['complete'],
           failed=progress['failed'], interrupted=progress['interrupted'])
    command('analysis-01', [sys.executable, '-m', 'sequence_replication.analyze',
                          '--root', '.', '--output', relative], cwd=integration)
    out = integration / relative
    rows = invocation_ledger(integration)
    with (out / 'invocation-ledger.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    provenance = read_json(out / 'provenance.json')
    provenance['invocation_scopes'] = dict(__import__('collections').Counter(r['scope'] for r in rows))
    provenance['ledger_note'] = 'Runner invocations across physical attempts; excludes hidden HTTP retry and billing estimates.'
    write_json(out / 'provenance.json', provenance)
    with zipfile.ZipFile(out / 'frozen-source.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in frozen_hashes()['files']:
            archive.write(integration / name, name)
        archive.write(integration / 'sequence_replication/protocol/freeze.json', 'sequence_replication/protocol/freeze.json')
    write_json(out / 'artifact-manifest.json', {'run_id': RUN, 'files': {
        str(p.relative_to(out)): digest(p) for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'artifact-manifest.json'}})
    package = out.parent / 'sequence-replication-analysis.zip'
    with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(out.rglob('*')):
            if path.is_file(): archive.write(path, str(path.relative_to(out.parent)))
    package.with_suffix('.zip.sha256').write_text(digest(package) + '  ' + package.name + '\n')
    # Archive-only reproduction uses the same pinned source and no inference.
    archived = integration / 'work/archive-only-reproduction'
    archived.mkdir(parents=True)
    # The frozen resolver prefers direct data, so provide a separate root with
    # source manifests/runtime and the archives only. ROOT still pins analysis.
    for directory in ['manifests', 'sequence_replication/runtime']:
        shutil.copytree(integration / directory, archived / directory, dirs_exist_ok=True)
    shutil.copytree(integration / 'results' / RUN / 'raw-archives',
                    archived / 'results' / RUN / 'raw-archives')
    command('archive-reproduction-01', [sys.executable, '-m', 'sequence_replication.analyze',
            '--root', str(archived), '--output', str(archived / 'analysis')], cwd=integration)
    matching = []
    for path in sorted((archived / 'analysis/tables').glob('*.csv')):
        reference = out / 'tables' / path.name
        with path.open(newline='') as f: actual = list(csv.reader(f))
        with reference.open(newline='') as f: expected = list(csv.reader(f))
        if actual != expected:
            raise ValueError('Archive reproduction CSV mismatch: ' + path.name)
        matching.append(path.name)
    figures = []
    for path in sorted((archived / 'analysis/figures').glob('*.png')):
        if digest(path) != digest(out / 'figures' / path.name):
            raise ValueError('Archive reproduction PNG mismatch: ' + path.name)
        figures.append(path.name)
    write_json(integration / 'sequence_replication/runtime/analysis-completion.json', {
        'run_id': RUN, 'completed_at': stamp(), 'assigned_sessions': config['sessions'],
        'complete': progress['complete'], 'failed': progress['failed'], 'interrupted': progress['interrupted'],
        'evaluation_calls': progress['calls'], 'csv_tables_reproduced': matching,
        'png_figures_byte_identical': figures, 'package_sha256': digest(package),
        'freeze_sha256': digest(integration / 'sequence_replication/protocol/freeze.json')})
    command('commit-analysis-01', ['git', 'add', '--sparse', '--', 'analysis/results/' + RUN,
                                 'results/' + RUN + '/raw-archives', 'sequence_replication/runtime'], cwd=integration)
    command('save-analysis-01', ['git', 'commit', '-m', 'Analyze and preserve completed ten-round sequence replication'], cwd=integration)
    status('publishing', complete=progress['complete'], failed=progress['failed'], package_sha256=digest(package))
    refs = ['worker/' + RUN + '/' + w for w in config['workers']] + ['integration/' + RUN]
    command('publish-01', ['git', 'push', 'origin', *refs], cwd=integration)
    status('complete', complete=progress['complete'], failed=progress['failed'],
           interrupted=progress['interrupted'], evaluation_calls=progress['calls'],
           integration_branch='integration/' + RUN, package_sha256=digest(package),
           csv_tables_reproduced=len(matching), png_figures_byte_identical=len(figures))
except SystemExit:
    raise
except Exception as error:
    status('blocked', error=type(error).__name__ + ': ' + str(error))
    raise
