"""Additional executor checks, using unchanged A–G source and live readiness."""
import concurrent.futures
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from equivoque.core import Protocol, digest, frozen_hashes, read_json, write_json
from equivoque.runner import now, run_trial
from equivoque.transport import CodexTransport
from equivoque.isolation import inspect_request

RUN = 'equivoque-2026-10-09-v1'
settings = read_json(ROOT / 'work/coordinator/expansion-config.json')
protocol = Protocol()
config = read_json(ROOT / 'protocol/run.v1.json')
frozen_hashes()

def check(item):
    executor, worker = item
    tree = ROOT / 'work/worker-trees' / RUN / executor
    original = ROOT / 'work/worker-trees' / RUN / worker
    directory = tree / 'results' / RUN / f'worker-{worker}' / f'preflight-helper-{executor}-01'
    if (directory / 'readiness.json').exists():
        raise ValueError('Existing helper preflight must not be repeated')
    manifest = read_json(tree / 'manifests' / RUN / f'worker-{worker}.json')
    source = original / 'results' / RUN / f'worker-{worker}' / 'preflight-05/readiness.json'
    inherited = read_json(source)
    assert inherited['ready'] and inherited['base_commit'] == settings['base_commit']
    assert inherited['freeze_sha256'] == digest(tree / 'protocol/freeze.json')
    assert inherited['manifest_sha256'] == digest(tree / 'manifests' / RUN / f'worker-{worker}.json')
    for name, expected in read_json(tree / 'protocol/freeze.json')['files'].items():
        assert digest(tree / name) == expected, name
    assert subprocess.check_output(['codex','--version'],text=True).strip() == config['codex_version']
    auth = subprocess.run(['codex','login','status'],capture_output=True,text=True,check=True)
    assert (auth.stdout+auth.stderr).strip() == 'Logged in using ChatGPT'
    directory.mkdir(parents=True)
    catalog = original / 'results' / RUN / f'worker-{worker}' / 'preflight-05/catalog.json'
    inspections = [inspect_request(protocol, c, directory/'offline-isolation'/c['configuration_id'], catalog)
                   for c in config['configurations']]
    errors = [e for inspection in inspections for e in inspection['errors']]
    assert all(i['passed'] for i in inspections) and not errors
    trial = next(t for t in manifest['trials'] if t['model']=='gpt-6-sol' and t['effort']=='low')
    calibration = {**trial, 'trial_id': 'calibration/helper-' + executor}
    state = run_trial(calibration, protocol, CodexTransport(protocol,config['turn_deadline_seconds']),
                      directory/'native-session-check.json', original/'work/preflight-helper'/executor)
    report = {'run_id':RUN,'worker_id':worker,'executor_id':executor,'base_commit':settings['base_commit'],
        'freeze_sha256':digest(tree/'protocol/freeze.json'),
        'manifest_sha256':digest(tree/'manifests'/RUN/f'worker-{worker}.json'),
        'inherited_all_configuration_readiness':str(source),'inherited_readiness_sha256':digest(source),
        'subject_invocations':len(state['turns'])+int(state.get('pending_turn') is not None),
        'ready':state['status']=='complete','live':True,'ended_at':now(),
        'checks':[{'name':'all-21-frozen-request-isolation','passed':True},
                  {'name':'native-four-turn-session','passed':state['status']=='complete'}],
        'errors':[] if state['status']=='complete' else [state.get('error','native trial did not complete')],
        'note':'Additional executor shares the unchanged source, original logical-worker subject paths, authentication and all-configuration readiness. This four-turn native check and 21 offline inspections are excluded from evaluation.'}
    write_json(directory/'readiness.json',report)
    print(json.dumps({'executor':executor,'ready':report['ready'],'subject_invocations':report['subject_invocations']}),flush=True)
    return report

with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    reports=list(pool.map(check, settings['helper_to_logical_worker'].items()))
write_json(ROOT/'preparation/current-runtime/helper-readiness-01.json',{
    'run_id':RUN,'helpers':reports,'ready':all(r['ready'] for r in reports),
    'subject_invocations':sum(r['subject_invocations'] for r in reports),
    'maximum_additional_preflight_concurrency':3,'ended_at':now()})
raise SystemExit(0 if all(r['ready'] for r in reports) else 2)
