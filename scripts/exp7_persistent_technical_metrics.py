"""Summarize technical request timing and rate-limit diagnostics without outcomes."""
import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from exp7_ops_v1.measure import load_observations, summarize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--attempt', default='01')
    parser.add_argument('--concurrency', type=int, default=1)
    args = parser.parse_args()
    root = args.work_dir / 'calibration' / ('attempt-' + args.attempt)
    intervals, durations, session_spans = [], [], []
    for path in sorted((root / 'states').glob('*.json')):
        state = json.loads(path.read_text())
        session_intervals = []
        for turn in state.get('turns', []):
            if turn.get('requested_at') and turn.get('received_at'):
                entry = {'start': turn['requested_at'], 'end': turn['received_at'],
                         'ok': turn.get('ok') is True}
                intervals.append(entry)
                session_intervals.append(entry)
            if turn.get('duration_seconds') is not None:
                durations.append(float(turn['duration_seconds']))
        if session_intervals:
            start = datetime.fromisoformat(session_intervals[0]['start'])
            end = datetime.fromisoformat(session_intervals[-1]['end'])
            session_spans.append((end - start).total_seconds())
    counts = {'catalog_429_lines': 0, 'response_429_lines': 0, 'unclassified_429_lines': 0}
    expression = re.compile(r'\b429\b|too many requests', re.IGNORECASE)
    for path in (root / 'native').rglob('process.stderr.log'):
        for line in path.read_text(errors='replace').splitlines():
            if not expression.search(line):
                continue
            text = line.lower()
            if any(s in text for s in ('/models', 'models/list', 'model catalog', 'model list')):
                counts['catalog_429_lines'] += 1
            elif any(s in text for s in ('/responses', 'response request', 'turn/start')):
                counts['response_429_lines'] += 1
            else:
                counts['unclassified_429_lines'] += 1
    counts['rpc_error_429_records'] = 0
    for path in (root / 'native').rglob('rpc-received.jsonl'):
        for line in path.read_text(errors='replace').splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue  # An actively written line may be incomplete.
            error = record.get('error')
            if error is None and record.get('method') == 'error':
                error = record.get('params')
            if error is not None and expression.search(json.dumps(error)):
                counts['rpc_error_429_records'] += 1
    states, reserved, expected, _, _ = load_observations(args.work_dir, 'calibration', args.attempt)
    summary = summarize(states, reserved, expected, args.concurrency)
    durations.sort()
    result = {'snapshot_utc': datetime.now(timezone.utc).isoformat(),
              'configured_pool': args.concurrency, 'successful_turns': summary['successful_calls'],
              'observed_local_pending_peak': summary['request_overlap']['observed_local_pending_peak'],
              'successful_turns_per_minute': (sum(x['ok'] for x in intervals) * 60 / sum(session_spans)
                                              if sum(session_spans) > 0 and args.concurrency == 1 else None),
              'wall_clock_turns_per_minute_including_stoppages': summary['whole_batch']['successful_calls_per_minute'],
              'p95_recorded_duration_seconds': durations[math.ceil(.95 * len(durations)) - 1] if durations else None,
              'diagnostics': counts, 'completed_request_intervals': intervals,
              'diagnostic_note': '429 counts are diagnostic lines/records, not distinct HTTP requests; RPC and unclassified entries require review.',
              'overlap_note': 'Local checkpoint intervals include gating and are not provider-internal concurrency.',
              'rate_note': 'Single-pool rate sums observed session spans; excludes gaps between sessions including STOP.'}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
