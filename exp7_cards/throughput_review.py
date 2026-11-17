"""Derive aggregate rates from completed technical-stage checkpoints.

No inference, filesystem mutation, prompts, or raw responses are emitted.
The four-minute window starts at the first successful response; it is a
retrospective descriptive window, not evidence of sustained service capacity.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import statistics


def review_stage(root):
    root = Path(root)
    summary = json.loads((root/'summary.json').read_text())
    states = [json.loads(p.read_text()) for p in sorted((root/'states').glob('tech-*.json'))]
    successes, request_waits, fail_429 = [], [], []
    for state in states:
        for turn in state.get('turns', []):
            if turn.get('ok'):
                successes.append(datetime.fromisoformat(turn['received_at']).timestamp())
                request_waits.append(float(turn['duration_seconds']))
            else:
                for ref in turn.get('raw_files', []):
                    path = Path(ref['path'])
                    if path.name != 'events.jsonl' or not path.is_file():
                        continue
                    errors = [json.loads(line) for line in path.read_text().splitlines()]
                    if any('429 Too Many Requests' in str(e.get('message', '')) for e in errors):
                        fail_429.append({'model': state['trial']['model'], 'effort': state['trial']['effort'],
                                         'turn': turn['turn']})
    if len(successes) != summary['successful_calls']:
        raise ValueError('Successful checkpoint count differs from stage summary')
    successes.sort()
    windows = {}
    for secs in (120, 240):
        if len(successes) >= 2 and successes[-1] - successes[0] >= secs:
            count = sum(t < successes[0]+secs for t in successes)
            windows[str(secs)] = {'successful_calls': count, 'duration_seconds': secs,
                                  'successful_calls_per_minute': 60*count/secs}
    return {'stage': summary['stage'], 'target_rpm': summary['target_rpm'],
            'concurrency': summary['concurrency'], 'sessions': len(states),
            'session_statuses': summary['session_statuses'],
            'successful_calls': len(successes), 'span_seconds': summary['elapsed_seconds'],
            'overall_successes_per_minute': summary['observed_successes_per_minute'],
            'windows_from_first_success': windows,
            'duration_seconds_median_including_pacing_and_startup': statistics.median(request_waits) if request_waits else None,
            'native_429_records': summary['native_429_retry_log_records'],
            'observed_terminal_429_errors': fail_429,
            'tool_events': summary['forbidden_tool_events'],
            'compactions': summary['compaction_events'], 'uncertain_sessions': summary['uncertain_sessions']}


def review(root):
    root = Path(root)
    return {'scope': 'independent technical sessions; not scientific samples',
            'method': 'completed response checkpoint timestamps; descriptive windows',
            'stages': [review_stage(root/f'stage-{i:02}') for i in range(1, 4)]}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', required=True)
    print(json.dumps(review(p.parse_args().root), ensure_ascii=False, indent=2))
