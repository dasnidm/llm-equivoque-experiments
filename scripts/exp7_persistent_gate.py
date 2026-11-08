"""Fail-closed global readiness and measured-load gate; performs no model calls."""
import argparse
from datetime import datetime
import json
from pathlib import Path

from exp7_main_v2.coordination import GitCoordinator
from exp7_main_v2.worker import verify_freeze


def evaluate(board, identity, freeze_hash):
    if board['global_stop']:
        return {'ready': False, 'terminal': True, 'reason': 'global STOP; never clear automatically'}
    if board['run_id'] != identity['run_id'] or board.get('freeze_sha256') != freeze_hash:
        return {'ready': False, 'terminal': True, 'reason': 'run or freeze mismatch'}
    models = board['models']
    own = models[identity['model']]
    if (own.get('owner'), own.get('model_token'), own.get('concurrency')) != (
            identity['owner'], identity['model_token'], identity['concurrency']):
        return {'ready': False, 'terminal': True, 'reason': 'model ownership or reservation mismatch'}
    missing = [name for name, item in models.items()
               if not item.get('technical_status', {}).get('readiness_and_backup_verified')]
    if missing:
        return {'ready': False, 'terminal': False, 'reason': 'model technical readiness incomplete', 'models': missing}
    events = []
    for name, item in models.items():
        tech = item['technical_status']
        intervals = tech.get('completed_request_intervals', [])
        diagnostics = tech.get('diagnostics', {})
        expected_diagnostics = {'catalog_429_lines', 'response_429_lines', 'unclassified_429_lines', 'rpc_error_429_records'}
        if (tech.get('finished') != 18 or tech.get('failed') or len(intervals) != 612
                or item.get('concurrency') != 1 or not tech.get('successful_turns_per_minute')
                or tech.get('p95_seconds') is None or set(diagnostics) != expected_diagnostics or any(diagnostics.values())):
            return {'ready': False, 'terminal': True, 'reason': 'technical metrics require inspection', 'model': name}
        for interval in intervals:
            if interval.get('ok') is not True:
                return {'ready': False, 'terminal': True, 'reason': 'failed technical turn', 'model': name}
            start = datetime.fromisoformat(interval['start']).timestamp()
            end = datetime.fromisoformat(interval['end']).timestamp()
            if end < start:
                return {'ready': False, 'terminal': True, 'reason': 'invalid timing interval', 'model': name}
            events.extend(((start, 1), (end, -1)))
    active = peak = 0
    seconds_at_least = [0.0] * (len(models) + 1)
    completions_at_least = [0] * (len(models) + 1)
    previous = None
    for moment, delta in sorted(events):
        if previous is not None:
            for level in range(1, min(active, len(models)) + 1):
                seconds_at_least[level] += max(0, moment - previous)
        if delta == -1:
            for level in range(1, min(active, len(models)) + 1):
                completions_at_least[level] += 1
        active += delta
        peak = max(peak, active)
        previous = moment
    checkpoint_cap = max((n for n in range(1, len(models) + 1)
                        if seconds_at_least[n] >= 120 and completions_at_least[n] >= 50), default=0)
    if checkpoint_cap < 1:
        return {'ready': False, 'terminal': True, 'reason': 'no 120-second/50-turn measured load'}
    # Checkpoint timestamps include local pacing and do not prove that provider
    # requests overlapped. Only one concurrent evaluation worker is authorized
    # by this gate until stronger shared-account admission evidence exists.
    measured_cap = 1
    unfinished = sorted(name for name in models if any(
        job['model'] == name and job['status'] != 'complete' for job in board['jobs'].values()))
    eligible = unfinished[:measured_cap]
    return {'ready': identity['model'] in eligible, 'terminal': False,
            'reason': 'measured-load wave', 'observed_combined_checkpoint_peak': peak,
            'checkpoint_overlap_cap': checkpoint_cap, 'measured_wave_cap': measured_cap, 'eligible_models': eligible,
            'load_seconds_at_cap': seconds_at_least[measured_cap],
            'successful_completions_at_cap': completions_at_least[measured_cap],
            'note': 'Checkpoint overlap is not provider-internal concurrency; capacity is not guaranteed.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--work-dir', required=True, type=Path)
    args = parser.parse_args()
    work = args.work_dir.resolve()
    identity = json.loads((work / 'identity.private.json').read_text())
    _, digest = verify_freeze('manifests/equivoque-2026-11-08-exp7-persistent-v1/freeze.json')
    c = GitCoordinator('https://github.com/dasnidm/llm-equivoque-experiments.git',
                       'exp7/persistent-v1-coordination', work / 'coordination.git')
    print(json.dumps(evaluate(c.status(), identity, digest)))


if __name__ == '__main__':
    main()
