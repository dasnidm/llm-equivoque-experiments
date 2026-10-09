"""Bounded worker access checks, distinct from the 2,100 evaluation trials."""
import json
from pathlib import Path
import subprocess
import uuid

from .core import ROOT, Protocol, digest, frozen_hashes, read_json, write_json
from .runner import now, run_trial
from .transport import CodexTransport, DISABLED_FEATURES, overrides


def preflight(manifest_path, directory, live=False):
    frozen_hashes()
    manifest = read_json(manifest_path)
    config = read_json(ROOT / 'protocol/run.v1.json')
    protocol = Protocol()
    directory = Path(directory)
    report_path = directory / 'readiness.json'
    if report_path.exists():
        raise ValueError('Preflight already recorded; inspect it rather than silently repeating checks')
    directory.mkdir(parents=True, exist_ok=True)
    report = {'worker_id': manifest['worker_id'], 'run_id': manifest['run_id'],
              'manifest_sha256': digest(manifest_path),
              'freeze_sha256': digest(ROOT / 'protocol/freeze.json'),
              'base_commit': subprocess.check_output(
                  ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'started_at': now(), 'ready': False, 'live': live,
              'subject_invocations': 0, 'checks': [], 'errors': []}
    version = subprocess.run(['codex', '--version'], text=True,
                             capture_output=True, timeout=10)
    report['codex_version'] = version.stdout.strip()
    if version.returncode or version.stdout.strip() != config['codex_version']:
        report['errors'].append('Codex CLI version differs from the frozen version')
    catalog_command = ['codex', 'debug', 'models']
    if not live:
        catalog_command.append('--bundled')
    catalog_result = subprocess.run(catalog_command, capture_output=True,
                                    text=True, timeout=60)
    (directory / 'catalog.stderr.txt').write_text(catalog_result.stderr)
    try:
        catalog = json.loads(catalog_result.stdout)
        models = catalog if isinstance(catalog, list) else catalog.get('models', [])
    except json.JSONDecodeError:
        models = []
    inventory = {m.get('slug'): m for m in models}
    report['catalog'] = [{'model': m.get('slug'),
                         'efforts': [x['effort'] for x in m.get('supported_reasoning_levels', [])]}
                        for m in models]
    for configuration in config['configurations']:
        metadata = inventory.get(configuration['model'])
        if not metadata:
            report['errors'].append('Model missing from catalog: ' + configuration['model'])
        elif configuration['effort'] not in [
                x['effort'] for x in metadata.get('supported_reasoning_levels', [])]:
            report['errors'].append('Unsupported effort: ' + configuration['configuration_id'])
    sandbox = ROOT / 'work' / 'preflight-subjects' / str(uuid.uuid4())
    sandbox.mkdir(parents=True)
    system_path = sandbox.parent / (sandbox.name + '.system.txt')
    system_path.write_text(protocol.data['system'])
    options = overrides(system_path, 'low')
    effective = subprocess.run(['codex', 'features', 'list', *options],
                               capture_output=True, text=True, timeout=20)
    (directory / 'effective-features.txt').write_text(effective.stdout)
    feature_lines = {line.split()[0]: line.split()[-1]
                     for line in effective.stdout.splitlines() if line.split()}
    for feature in DISABLED_FEATURES:
        if feature_lines.get(feature) != 'false':
            report['errors'].append('Subject feature not disabled: ' + feature)
    prompt = 'Reply with the JSON object {"ready":true}.'
    debug = subprocess.run(['codex', 'debug', 'prompt-input', *options, prompt],
                           cwd=sandbox, capture_output=True, text=True, timeout=60)
    (directory / 'debug-input.json').write_text(debug.stdout)
    (directory / 'debug-input.stderr.txt').write_text(debug.stderr)
    try:
        visible = json.loads(debug.stdout)
        texts = [block.get('text', '') for item in visible
                 for block in item.get('content', [])]
        if len(texts) != 2 or texts[-1] != prompt or not texts[0].startswith('<environment_context>'):
            report['errors'].append('Unexpected repository/harness prompt context')
    except (json.JSONDecodeError, TypeError, AttributeError):
        report['errors'].append('Cannot inspect subject prompt context')
    report['checks'].append({'name': 'offline-config-and-catalog',
                             'passed': not report['errors']})
    write_json(report_path, report)
    if live and not report['errors']:
        # One full trial checks native resume plus both response-schema families.
        configuration = next(c for c in config['configurations']
                             if c['model'] == 'gpt-6-sol' and c['effort'] == 'low')
        trial = next(t for t in manifest['trials']
                     if t['configuration_id'] == configuration['configuration_id'])
        calibration_trial = {**trial, 'trial_id': 'calibration/' + manifest['worker_id']}
        transport = CodexTransport(protocol, config['turn_deadline_seconds'])
        state = run_trial(calibration_trial, protocol, transport,
                          directory / 'native-session-check.json', sandbox.parent)
        report['subject_invocations'] += len(state['turns'])
        report['checks'].append({'name': 'native-four-turn-session',
                                 'passed': state['status'] == 'complete'})
        if state['status'] != 'complete':
            report['errors'].append('Native session/schema/access check failed')
        else:
            for other in config['configurations']:
                if other == configuration:
                    continue
                probe_trial = {**trial, **other}
                result = transport.request(probe_trial, prompt, {
                    'type': 'object', 'additionalProperties': False,
                    'required': ['ready'], 'properties': {'ready': {'type': 'boolean'}}},
                    None, sandbox.parent / str(uuid.uuid4()), 1)
                report['subject_invocations'] += 1
                write_json(directory / ('access-' + other['configuration_id'] + '.json'), result)
                try:
                    passed = result['ok'] and json.loads(result['text']) == {'ready': True}
                except (json.JSONDecodeError, TypeError):
                    passed = False
                report['checks'].append({'name': other['configuration_id'], 'passed': bool(passed)})
                if not passed:
                    report['errors'].append('Inference access failed: ' + other['configuration_id'])
                    break
                write_json(report_path, report)
    report.update(ready=live and not report['errors'], ended_at=now())
    write_json(report_path, report)
    return report
