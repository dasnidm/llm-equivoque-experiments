"""Metadata-only persistent evaluation throughput and RPC overlap snapshot."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re

from exp7_ops_v1.measure import load_observations, summarize


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--work-dir', required=True, type=Path)
    p.add_argument('--concurrency', required=True, type=int)
    args = p.parse_args()
    states, reserved, expected, _, _ = load_observations(args.work_dir, 'evaluation')
    summary = summarize(states, reserved, expected, args.concurrency)
    durations = sorted(float(t['duration_seconds']) for s in states for t in s.get('turns', [])
                       if t.get('duration_seconds') is not None)
    counts = {'catalog_429_lines': 0, 'response_429_lines': 0, 'unclassified_429_lines': 0,
              'rpc_error_429_records': 0}
    pattern = re.compile(r'\b429\b|too many requests', re.I)
    events, running = [], {}
    native = args.work_dir / 'jobs'
    for path in native.rglob('process.stderr.log'):
        for line in path.read_text(errors='replace').splitlines():
            if not pattern.search(line):
                continue
            value = line.lower()
            if any(x in value for x in ('/models', 'models/list', 'model catalog', 'model list',
                                         'failed to refresh available models')):
                counts['catalog_429_lines'] += 1
            elif any(x in value for x in ('/responses', 'response request', 'turn/start')):
                counts['response_429_lines'] += 1
            else:
                counts['unclassified_429_lines'] += 1
    for path in native.rglob('rpc-received.jsonl'):
        for line in path.read_text(errors='replace').splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            method = record.get('method')
            error = record.get('error')
            if error is None and method == 'error':
                error = record.get('params')
            if error is not None and pattern.search(json.dumps(error)):
                counts['rpc_error_429_records'] += 1
            if method not in ('turn/started', 'turn/completed') or not isinstance(record.get('emittedAtMs'), int):
                continue
            params = record.get('params') or {}
            turn = params.get('turn') or {}
            key = (params.get('threadId'), turn.get('id'))
            if not all(key):
                continue
            if method == 'turn/started':
                running[key] = record['emittedAtMs']
            elif key in running:
                events.extend(((running.pop(key), 1), (record['emittedAtMs'], -1)))
    for start in running.values():
        events.append((start, 1))
    current = peak = 0
    for _, change in sorted(events):
        current += change
        peak = max(peak, current)
    output = {'snapshot_utc': datetime.now(timezone.utc).isoformat(), 'pool': args.concurrency,
              'successful_turns': summary['successful_calls'], 'failed_recorded_turns': summary['failed_recorded_calls'],
              'successful_turns_per_minute': summary['whole_batch']['successful_calls_per_minute'],
              'p95_recorded_duration_seconds': durations[math.ceil(.95*len(durations))-1] if durations else None,
              'checkpoint_pending_now': summary['active_pending_requests'],
              'checkpoint_pending_peak': summary['request_overlap']['observed_local_pending_peak'],
              'app_server_started_turns_now': len(running), 'app_server_started_turns_peak': peak,
              'diagnostics': counts, 'job_statuses': summary['statuses'],
              'note': 'App-server started/completed notifications measure visible turn overlap, not internal provider execution; includes only loose current job logs. 429 counts are diagnostic lines/records.'}
    print(json.dumps(output))


if __name__ == '__main__':
    main()
