"""Package frozen analysis outputs; add accounting and descriptive choice exports.

This post-collection utility does not alter the frozen estimators, stimuli,
roster, or evaluation records. No inference is made here.
"""
import argparse
import collections
import csv
import json
from pathlib import Path
import zipfile

from equivoque.core import ROOT, digest, operate, read_json, write_json
from equivoque2.protocol import CONFIG, RepeatedProtocol, frozen_hashes
from experiment2.explorer import create as create_explorer


def csv_file(path, rows):
    if not rows:
        raise ValueError('Empty export: ' + str(path))
    with path.open('x', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def check_files(record, directory):
    for item in record.get('raw_files', []):
        if digest(directory / item['path']) != item['sha256']:
            raise ValueError('Calibration raw archive changed: ' + item['path'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    frozen_hashes()
    output = Path(args.output)
    config = read_json(CONFIG)
    provenance = read_json(output / 'provenance.json')
    if provenance['run_id'] != config['run_id']:
        raise ValueError('Wrong analysis output')
    baseline = {str(p.relative_to(output)): digest(p) for p in output.rglob('*') if p.is_file()}
    calibration, calibration_sessions, evaluation_sessions, choices, traces = [], set(), set(), [], []
    shared = ROOT / 'experiment2/runtime/shared-preflight-01'
    shared_ready = read_json(shared / 'readiness.json')
    assert shared_ready['ready'] and shared_ready['subject_invocations'] == 21
    for c in config['configurations']:
        source = shared / (c['configuration_id'] + '.json')
        record = read_json(source)
        check_files(record, shared)
        assert record['ok']
        calibration_sessions.add(record['session_id'])
        calibration.append({'category': 'shared_access', 'worker': '',
            'configuration_id': c['configuration_id'], 'turn': 1,
            'session_id': record['session_id'], 'requested_at': record['requested_at'],
            'received_at': record['received_at'], 'duration_seconds': record.get('duration_seconds'),
            'ok': record['ok'], 'source': str(source.relative_to(ROOT)), 'source_sha256': digest(source)})
    protocol = RepeatedProtocol()
    for w in config['workers']:
        directory = ROOT / 'results' / config['run_id'] / f'worker-{w}'
        preflight = directory / 'preflight-01'
        readiness = read_json(preflight / 'readiness.json')
        source = preflight / 'native-session-check.json'
        state = read_json(source)
        assert readiness['ready'] and readiness['subject_invocations'] == 10
        assert state['status'] == 'complete' and len(state['turns']) == 10
        assert state['session_id'] not in calibration_sessions
        calibration_sessions.add(state['session_id'])
        for record in state['turns']:
            check_files(record, preflight)
            calibration.append({'category': 'worker_ten_turn', 'worker': w,
                'configuration_id': readiness['calibration_configuration'], 'turn': record['turn'],
                'session_id': state['session_id'], 'requested_at': record['requested_at'],
                'received_at': record['received_at'], 'duration_seconds': record.get('duration_seconds'),
                'ok': record['ok'], 'source': str(source.relative_to(ROOT)), 'source_sha256': digest(source)})
        for path in sorted((directory / 'trials').glob('*.json')):
            state = read_json(path)
            trial = state['trial']
            if state['session_id']:
                assert state['session_id'] not in evaluation_sessions
                evaluation_sessions.add(state['session_id'])
            remaining = {r: list(trial['round_orders'][r - 1]) for r in (1, 2, 3)}
            for rnd in state['rounds']:
                traces.append({'trial_id': trial['trial_id'], 'case_id': trial['case_id'],
                    'configuration_id': trial['configuration_id'], 'frame': trial['frame'], 'worker': w,
                    'round': rnd['round'], 'display_order_internal': json.dumps(rnd['order']),
                    'recorded_remaining_internal': json.dumps(rnd['remaining']), 'route': rnd['route'],
                    'recorded_choice_steps': len(rnd['route']), 'complete_choice_pair': len(rnd['route']) == 2,
                    'measurement_valid': any(r['turn'] == rnd['round'] * 3 and 'parsed' in r for r in state['turns']),
                    'terminal_trial_status': state['status'], 'source': str(path.relative_to(ROOT)),
                    'source_sha256': digest(path)})
            for record in state['turns']:
                if record['local_turn'] not in (1, 2):
                    continue
                selection = record.get('parsed', {}).get('selection')
                selected = selection if isinstance(selection, list) else [selection] if selection else []
                rnd = record['round']
                before = remaining[rnd]
                after, route = operate(before, selected, trial['target']) if selected else (before, '')
                choices.append({'trial_id': trial['trial_id'], 'case_id': trial['case_id'],
                    'configuration_id': trial['configuration_id'], 'frame': trial['frame'],
                    'worker': w, 'round': rnd, 'step': record['local_turn'], 'turn': record['turn'],
                    'valid_choice': bool(selected), 'remaining_before': json.dumps(before),
                    'selected_internal_labels': json.dumps(selected),
                    'selected_display_names': protocol.display(trial['frame'], selected),
                    'target_selected': trial['target'] in selected if selected else '',
                    'operation': route, 'remaining_after': json.dumps(after),
                    'source': str(path.relative_to(ROOT)), 'source_sha256': digest(path)})
                remaining[rnd] = after
    assert len(calibration) == 221 and len(calibration_sessions) == 41
    assert not calibration_sessions & evaluation_sessions
    csv_file(output / 'tables/calibration_invocations.csv', calibration)
    csv_file(output / 'tables/choices.csv', choices)
    csv_file(output / 'tables/round_traces.csv', traces)
    patterns = collections.Counter((r['configuration_id'], r['frame'], r['round'], r['step'],
        r['remaining_before'], r['selected_internal_labels'], r['operation']) for r in choices if r['valid_choice'])
    csv_file(output / 'tables/choice_patterns.csv', [dict(zip(
        ('configuration_id', 'frame', 'round', 'step', 'remaining_before', 'selected_internal_labels', 'operation', 'count'),
        (*key, count))) for key, count in sorted(patterns.items())])
    ledger = {'run_id': config['run_id'], 'calibration_invocations': 221,
        'shared_access_invocations': 21, 'worker_calibration_invocations': 200,
        'calibration_sessions': 41, 'evaluation_invocations': provenance['evaluation_invocations'],
        'combined_native_invocations': 221 + provenance['evaluation_invocations'],
        'calibration_evaluation_sessions_disjoint': True,
        'accounting_scope': 'Native CLI invocations; actual HTTP attempts and costs remain unknown.',
        'confirmed_measurements': [3, 6, 9, 10], 'planned_evaluation_invocations': 4200,
        'frozen_analysis_outputs_before_packaging': baseline,
        'delivery_source_sha256': digest(Path(__file__)),
        'explorer_source_sha256': digest(ROOT / 'experiment2/explorer.py')}
    recovery_path = ROOT / 'experiment2/runtime/runtime-recovery-01.json'
    recovery = read_json(recovery_path) if recovery_path.exists() else {}
    ledger['recovered_native_turns'] = len(recovery.get('recovered_turns', []))
    ledger['recovery_model_invocations_added'] = recovery.get('model_invocations_added', 0)
    ledger['unknown_exit_status_turns'] = recovery.get('unknown_exit_status_turns', 0)
    ledger['recovery_evidence_sha256'] = digest(recovery_path) if recovery else None
    write_json(output / 'invocation-ledger.json', ledger)
    report = output / 'REPORT.md'
    with report.open('a') as handle:
        handle.write('\n## Calibration accounting and descriptive choice exports\n\n'
            'The 21 shared access probes and 20 separate ten-turn worker sessions contributed\n'
            '221 calibration invocations in 41 sessions, excluded from every evaluation estimate.\n'
            'Calibration archives were reverified, and their session IDs are disjoint from\n'
            'evaluation. The temporary nine-turn preparation draft collected no observations;\n'
            'the owner-confirmed sequence retains Round 3 questions before final disclosure.\n\n'
            'calibration_invocations.csv provides the call ledger. choices.csv,\n'
            'choice_patterns.csv, and round_traces.csv export recorded choices and partial\n'
            'round routes descriptively, including rounds without a valid score. They retain\n'
            'trial/case/round membership and do not add inferential contrasts. The packaging\n'
            'utility leaves the frozen analysis source, estimates, plots, and raw data unchanged.\n')
        handle.write('\nexplorer.html provides an offline configuration/frame selector for recorded\n'
            'endpoint means and trial answers, with visible valid counts. It performs no\n'
            'new inferential analysis; use estimates.csv for paired contrasts and intervals.\n')
        if recovery:
            handle.write(f'\nRuntime reconnection interrupted the original coordinator and workers.\n'
                f'{ledger["recovered_native_turns"]} pending responses were recovered from unique, schema-valid\n'
                'final native completion events with matching sessions, prompts, systems, and\n'
                'schemas, within the frozen deadline. No requests were replayed. Original\n'
                'parent-observed exit statuses and monotonic durations for these turns remain\n'
                'unknown. Their trial observations are retained, while the affected complete\n'
                'trials are excluded from latency summaries requiring all ten durations.\n')
        handle.write('\nTechnical token columns sum the native-reported usage counters across\n'
            'invocations. Counter semantics after native session resumption are not established\n'
            'as marginal billable usage; these sums are not billing estimates. Native WebSocket\n'
            'reconnection diagnostics remain in the raw logs even when a final turn completes.\n')
    create_explorer(output)
    html = output / 'index.html'
    html.write_text(html.read_text().replace('</html>',
        '<p>Calibration: 221 native invocations in 41 separate sessions, excluded from evaluation. '
        'Round 3 questions precede disclosure; four measurements total. '
        'The English report, calibration ledger, and descriptive choice CSVs accompany this visualization. '
        '<a href="explorer.html">Open the offline endpoint explorer</a>.</p></html>'))
    protected = {p:h for p,h in baseline.items() if p not in ('REPORT.md', 'index.html')}
    assert all(digest(output / p) == h for p,h in protected.items())
    files = {str(p.relative_to(output)): digest(p) for p in output.rglob('*') if p.is_file()}
    write_json(output / 'artifact-manifest.json', {'files': files, 'run_id': config['run_id']})
    archive = output.parent / (output.name + '-analysis.zip')
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(output.rglob('*')):
            if path.is_file():
                bundle.write(path, str(path.relative_to(output)))
    write_json(output.parent / (output.name + '-analysis.zip.sha256.json'),
        {'file': archive.name, 'sha256': digest(archive), 'bytes': archive.stat().st_size})
    print(json.dumps({k:v for k,v in ledger.items() if k != 'frozen_analysis_outputs_before_packaging'}, indent=2))


if __name__ == '__main__':
    main()
