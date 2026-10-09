"""Separate shared access checks and 20 native nine-turn calibration sessions."""
import json
from pathlib import Path
import subprocess
import uuid

from equivoque.core import ROOT, digest, read_json, write_json
from equivoque.isolation import inspect_request
from equivoque.runner import now
from equivoque.transport import CodexTransport, DISABLED_FEATURES, overrides
from .protocol import CONFIG, FREEZE, RepeatedProtocol, frozen_hashes
from .runner import archive_native, run_trial


def cli_checks(config, directory, protocol, errors):
    version = subprocess.run(['codex', '--version'], capture_output=True, text=True, timeout=10)
    auth = subprocess.run(['codex', 'login', 'status'], capture_output=True, text=True, timeout=10)
    auth_route = (auth.stdout + auth.stderr).strip()
    if version.returncode or version.stdout.strip() != config['codex_version']:
        errors.append('Pinned CLI version unavailable')
    if auth.returncode or auth_route != 'Logged in using ChatGPT':
        errors.append('ChatGPT authentication route unavailable')
    sandbox = ROOT / 'work/preflight-subjects' / str(uuid.uuid4())
    sandbox.mkdir(parents=True)
    system = sandbox.parent / (sandbox.name + '.system.txt')
    system.write_text(protocol.data['system'])
    options = overrides(system, 'low')
    features = subprocess.run(['codex', 'features', 'list', *options], capture_output=True, text=True, timeout=20)
    (directory / 'effective-features.txt').write_text(features.stdout)
    flags = {line.split()[0]: line.split()[-1] for line in features.stdout.splitlines() if line.split()}
    if features.returncode:
        errors.append('Feature inspection failed')
    for feature in DISABLED_FEATURES:
        if feature != 'unified_exec' and flags.get(feature) != 'false':
            errors.append('Subject feature not disabled: ' + feature)
    prompt = 'Reply with the JSON object {"ready":true}.'
    context = subprocess.run(['codex', 'debug', 'prompt-input', *options, prompt],
        cwd=sandbox, capture_output=True, text=True, timeout=30)
    (directory / 'debug-input.json').write_text(context.stdout)
    (directory / 'debug-input.stderr.txt').write_text(context.stderr)
    try:
        texts = [block.get('text', '') for item in json.loads(context.stdout)
                 for block in item.get('content', [])]
        if context.returncode or len(texts) != 2 or not texts[0].startswith('<environment_context>') or texts[-1] != prompt:
            errors.append('Unexpected visible subject context')
    except (ValueError, TypeError, AttributeError):
        errors.append('Cannot inspect visible subject context')
    return {'codex_version': version.stdout.strip(), 'auth_route': auth_route,
            'observed_unified_exec_flag': flags.get('unified_exec')}


def shared(directory):
    frozen_hashes()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    config, protocol = read_json(CONFIG), RepeatedProtocol()
    report = {'run_id': config['run_id'], 'started_at': now(), 'ready': False,
        'freeze_sha256': digest(FREEZE), 'base_commit': subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'subject_invocations': 0, 'errors': [], 'checks': [], 'offline_inspections': []}
    try:
        report.update(cli_checks(config, directory, protocol, report['errors']))
        catalog = subprocess.run(['codex', 'debug', 'models'], capture_output=True, text=True, timeout=60)
        (directory / 'catalog.json').write_text(catalog.stdout)
        (directory / 'catalog.stderr.txt').write_text(catalog.stderr)
        if catalog.returncode or 'fallback metadata' in catalog.stderr.lower():
            report['errors'].append('Refreshed catalog unavailable or fallback metadata')
        try:
            data = json.loads(catalog.stdout)
            inventory = {m['slug']: m for m in (data if isinstance(data, list) else data.get('models', []))}
        except (ValueError, TypeError, KeyError):
            inventory = {}
            report['errors'].append('Malformed refreshed catalog')
        for c in config['configurations']:
            if c['model'] not in inventory or c['effort'] not in [
                    r['effort'] for r in inventory[c['model']].get('supported_reasoning_levels', [])]:
                report['errors'].append('Unavailable model/effort: ' + c['configuration_id'])
        report['catalog_sha256'] = digest(directory / 'catalog.json')
        write_json(directory / 'readiness.json', report)
        if not report['errors']:
            transport = CodexTransport(protocol, config['turn_deadline_seconds'])
            for c in config['configurations']:
                inspection = inspect_request(protocol, c, directory / 'offline-isolation' / c['configuration_id'], directory / 'catalog.json')
                report['offline_inspections'].append(inspection)
                report['errors'].extend(inspection['errors'])
                if not inspection['passed']:
                    report['errors'].append('Offline native isolation failed: ' + c['configuration_id'])
                    break
                request = 'Reply with the JSON object {"ready":true}.'
                schema = {'type': 'object', 'additionalProperties': False, 'required': ['ready'],
                          'properties': {'ready': {'type': 'boolean'}}}
                report['subject_invocations'] += 1
                write_json(directory / 'readiness.json', report)
                native = ROOT / 'work/service-preflight' / config['run_id'] / str(uuid.uuid4())
                requested_at = now()
                result = transport.request(c, request, schema, None, native, 1)
                result.update(prompt=request, schema=schema, requested_at=requested_at, received_at=now(),
                    raw_files=archive_native(native, directory / 'native-raw' / c['configuration_id'], directory))
                write_json(directory / (c['configuration_id'] + '.json'), result)
                passed = result['ok'] and json.loads(result['text'] or 'null') == {'ready': True}
                report['checks'].append({'configuration_id': c['configuration_id'], 'passed': bool(passed)})
                if not passed:
                    report['errors'].append('Live inference access failed: ' + c['configuration_id'])
                    break
                write_json(directory / 'readiness.json', report)
    except Exception as error:
        report['errors'].append(f'{type(error).__name__}: {error}')
    report.update(ready=not report['errors'] and len(report['checks']) == 21, ended_at=now())
    write_json(directory / 'readiness.json', report)
    return report


def worker(manifest_path, directory, shared_path):
    frozen_hashes()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    config, manifest, protocol = read_json(CONFIG), read_json(manifest_path), RepeatedProtocol()
    service = read_json(shared_path)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    report = {'run_id': config['run_id'], 'worker_id': manifest['worker_id'],
        'started_at': now(), 'ready': False, 'errors': [], 'subject_invocations': 0,
        'freeze_sha256': digest(FREEZE), 'manifest_sha256': digest(manifest_path),
        'shared_service_sha256': digest(shared_path), 'base_commit': service['base_commit'],
        'execution_commit': revision}
    try:
        expected = ROOT / 'manifests' / config['run_id'] / f"worker-{manifest['worker_id']}.json"
        if digest(manifest_path) != digest(expected) or manifest['run_id'] != config['run_id']:
            report['errors'].append('Manifest differs from assigned shard')
        if not service['ready'] or service['freeze_sha256'] != digest(FREEZE):
            report['errors'].append('Shared live readiness does not match this source')
        if subprocess.run(['git', 'merge-base', '--is-ancestor', service['base_commit'], revision], cwd=ROOT).returncode:
            report['errors'].append('Worker source is not descended from the approved common source')
        report.update(cli_checks(config, directory, protocol, report['errors']))
        index = config['workers'].index(manifest['worker_id'])
        c = config['configurations'][index % 21]
        report['calibration_configuration'] = c['configuration_id']
        trial = next(t for t in manifest['trials'] if t['configuration_id'] == c['configuration_id'])
        catalog = Path(shared_path).parent / 'catalog.json'
        if digest(catalog) != service['catalog_sha256']:
            report['errors'].append('Shared catalog changed')
        if not report['errors']:
            inspection = inspect_request(protocol, c, directory / 'offline-isolation', catalog)
            report['offline_inspection'] = inspection
            report['errors'].extend(inspection['errors'])
            if not inspection['passed']:
                report['errors'].append('Worker operational isolation failed')
        write_json(directory / 'readiness.json', report)
        if not report['errors']:
            trial = {**trial, 'trial_id': 'calibration/' + config['run_id'] + '/' + manifest['worker_id']}
            state = run_trial(trial, protocol, CodexTransport(protocol, config['turn_deadline_seconds']),
                directory / 'native-session-check.json', ROOT / 'work/worker-preflight' / config['run_id'] / manifest['worker_id'])
            report['subject_invocations'] = len(state['turns']) + int(state.get('pending_turn') is not None)
            report['session_id'] = state['session_id']
            if state['status'] != 'complete' or len(state['turns']) != 9:
                report['errors'].append('Native nine-turn session/schema/resume check failed')
    except Exception as error:
        report['errors'].append(f'{type(error).__name__}: {error}')
    report.update(ready=not report['errors'] and report['subject_invocations'] == 9, ended_at=now())
    write_json(directory / 'readiness.json', report)
    return report


def release(readiness_paths, shared_path, output):
    frozen_hashes()
    config, service = read_json(CONFIG), read_json(shared_path)
    if Path(output).exists():
        raise ValueError('Coordinator release already exists')
    reports = [read_json(p) for p in readiness_paths]
    if (not service['ready'] or service['freeze_sha256'] != digest(FREEZE) or
            len(reports) != 20 or {r['worker_id'] for r in reports} != set(config['workers']) or
            any(not r['ready'] or r['base_commit'] != service['base_commit'] or
                r['freeze_sha256'] != digest(FREEZE) or r['shared_service_sha256'] != digest(shared_path)
                for r in reports)):
        raise ValueError('All 20 workers must be ready at the same frozen source and service gate')
    if len({r['session_id'] for r in reports}) != 20:
        raise ValueError('Worker calibration sessions are not unique')
    for r in reports:
        manifest = ROOT / 'manifests' / config['run_id'] / f"worker-{r['worker_id']}.json"
        if digest(manifest) != r['manifest_sha256']:
            raise ValueError('Readiness manifest differs')
    report = {'run_id': config['run_id'], 'released_at': now(), 'base_commit': service['base_commit'],
        'freeze_sha256': digest(FREEZE), 'workers_ready': config['workers'],
        'shared_service_sha256': digest(shared_path),
        'readiness_sha256': {r['worker_id']: digest(p) for p, r in zip(readiness_paths, reports)},
        'non_evaluation_invocations': service['subject_invocations'] + sum(r['subject_invocations'] for r in reports)}
    write_json(output, report)
    return report
