"""Read-only local throughput audit for Exp 7 evaluation or technical sessions.

No inference, Git access, source mutation or answer scoring occurs. JSON is
written to stdout. Request overlap is reconstructed from durable local request
and response timestamps, not inferred from the configured worker count.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from statistics import mean, median
import tarfile


def seconds(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timestamp requires an explicit timezone')
    return parsed.timestamp()


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def descriptive(values):
    values = sorted(values)
    if not values:
        return {'n': 0, 'mean': None, 'median': None, 'min': None, 'max': None}
    return {'n': len(values), 'mean': mean(values), 'median': median(values),
            'min': values[0], 'max': values[-1]}


def overlap_segments(intervals, start=None, end=None):
    """Half-open [request,response) intervals; ties never cause a false peak."""
    events = defaultdict(int)
    for a, b in intervals:
        if b < a:
            raise ValueError('Response predates request')
        if b == a:
            continue
        events[a] += 1
        events[b] -= 1
    if start is not None:
        events[start] += 0
    if end is not None:
        events[end] += 0
    points = sorted(events)
    segments, active = [], 0
    for i, t in enumerate(points):
        active += events[t]
        if active < 0:
            raise ValueError('Negative reconstructed request count')
        if i + 1 < len(points) and points[i + 1] > t:
            segments.append((t, points[i + 1], active))
    if active != 0:
        raise ValueError('Unclosed reconstructed request intervals')
    return segments


def loaded_window(segments, accepted_times, concurrency, minimum_seconds=120,
                  minimum_fraction=.9, minimum_completions=50):
    """Longest event-boundary window with >=90% time at N-1 local requests.

    Selection optimizes duration, not the observed throughput. Ties select the
    earliest start. Unlike historical one-second sampling, the integration uses
    exact saved checkpoint intervals; the two methods are not identical.
    """
    if not segments or concurrency < 1:
        return None
    threshold = max(1, concurrency - 1)
    points = [segments[0][0]] + [b for _, b, _ in segments]
    good = [0.0]
    for a, b, active in segments:
        good.append(good[-1] + (b - a if active >= threshold else 0))
    completions = sorted(accepted_times)
    best = None
    for i, first in enumerate(points[:-1]):
        if best and points[-1] - first <= best['duration_seconds'] + 1e-9:
            break
        left_count = bisect_right(completions, first)
        for j in range(len(points) - 1, i, -1):
            duration = points[j] - first
            if duration + 1e-9 < minimum_seconds:
                break
            if best and duration <= best['duration_seconds'] + 1e-9:
                break
            accepted = bisect_right(completions, points[j]) - left_count
            if accepted < minimum_completions:
                break
            high_seconds = good[j] - good[i]
            if high_seconds / duration + 1e-12 < minimum_fraction:
                continue
            best = {'start_utc': iso(first), 'end_utc': iso(points[j]),
                    'duration_seconds': duration, 'accepted_completions': accepted,
                    'pending_threshold': threshold, 'high_pending_seconds': high_seconds,
                    'high_pending_time_fraction': high_seconds / duration,
                    'successful_calls_per_minute': accepted / duration * 60,
                    'selection': 'Longest qualifying event-boundary window; earliest on duration tie.'}
    return best


def summarize(states, reserved_calls=None, expected_sessions=None, concurrency=3,
              snapshot=None, minimum_seconds=120, minimum_completions=50):
    """Summarize metadata only. Native acceptance and conversation completion differ."""
    snapshot = snapshot if snapshot is not None else datetime.now(timezone.utc).timestamp()
    if len({s['trial']['trial_id'] for s in states}) != len(states):
        raise ValueError('Duplicate conversation in metrics input')
    statuses = Counter(s['status'] for s in states)
    terminal = {'complete', 'failed', 'interrupted', 'budget_exhausted'}
    active_states = [s for s in states if s['status'] not in terminal]
    completed = [s for s in states if s['status'] == 'complete']
    intervals, accepted_times, recorded, known_pending, unknown_pending = [], [], [], 0, 0
    for state in states:
        seen_turns = set()
        for turn in state.get('turns', []):
            if turn['turn'] in seen_turns:
                raise ValueError('Duplicate recorded turn')
            seen_turns.add(turn['turn'])
            a, b = seconds(turn['requested_at']), seconds(turn['received_at'])
            if b > snapshot + 1:
                raise ValueError('Response timestamp is later than snapshot')
            intervals.append((a, b))
            recorded.append(turn)
            if turn.get('ok') is True:
                accepted_times.append(b)
        pending = state.get('pending_turn')
        if pending is not None:
            if pending['turn'] in seen_turns:
                raise ValueError('Turn is both pending and recorded')
            if state['status'] not in terminal:
                known_pending += 1
                intervals.append((seconds(pending['requested_at']), snapshot))
            else:
                # A terminal uncertain request has no measured response/end.
                unknown_pending += 1
    starts = [seconds(s['started_at']) for s in states if s.get('started_at')]
    ends = [seconds(s['ended_at']) for s in states if s.get('ended_at')]
    first = min(starts) if starts else None
    last = snapshot if active_states else max(ends, default=first)
    duration = last - first if first is not None and last is not None else 0
    segments = overlap_segments(intervals, first, last) if intervals else []
    peak = max((n for _, _, n in segments), default=0)
    occupancy = defaultdict(float)
    for a, b, n in segments:
        occupancy[str(n)] += b - a
    effort = defaultdict(lambda: {'statuses': Counter(), 'durations': [], 'recorded_calls': 0, 'successful_calls': 0})
    completed_durations = []
    for s in states:
        e = effort[s['trial']['effort']]
        e['statuses'][s['status']] += 1
        e['recorded_calls'] += len(s.get('turns', []))
        e['successful_calls'] += sum(t.get('ok') is True for t in s.get('turns', []))
        if s['status'] == 'complete':
            elapsed = seconds(s['ended_at']) - seconds(s['started_at'])
            completed_durations.append(elapsed)
            e['durations'].append(elapsed)
    per_effort = {k: {'statuses': dict(v['statuses']), 'recorded_calls': v['recorded_calls'],
                      'successful_calls': v['successful_calls'],
                      'complete_conversation_seconds': descriptive(v['durations'])}
                  for k, v in sorted(effort.items())}
    return {
        'snapshot_utc': iso(snapshot), 'observed_sessions': len(states),
        'expected_sessions': expected_sessions, 'statuses': dict(statuses),
        'unstarted_expected_sessions': max(0, expected_sessions - len(states)) if expected_sessions is not None else None,
        'all_expected_complete': bool(expected_sessions and len(completed) == expected_sessions),
        'recorded_calls': len(recorded), 'successful_calls': len(accepted_times),
        'failed_recorded_calls': sum(t.get('ok') is False for t in recorded),
        'unclassified_recorded_calls': sum(type(t.get('ok')) is not bool for t in recorded),
        'reserved_calls': reserved_calls, 'active_pending_requests': known_pending,
        'terminal_uncertain_pending_requests': unknown_pending,
        'reserved_minus_recorded_calls': reserved_calls - len(recorded) if reserved_calls is not None else None,
        'whole_batch': {
            'start_utc': iso(first) if first is not None else None,
            'end_utc': iso(last) if last is not None else None,
            'end_basis': 'snapshot_while_active' if active_states else 'last_observed_terminal_conversation',
            'duration_seconds': duration,
            'successful_calls_per_minute': len(accepted_times) / duration * 60 if duration else None,
            'recorded_calls_per_minute': len(recorded) / duration * 60 if duration else None,
            'completed_conversations_per_hour': len(completed) / duration * 3600 if duration else None},
        'request_overlap': {
            'configured_concurrency_for_comparison': concurrency,
            'observed_local_pending_peak': peak,
            'observed_peak_exceeds_requested_cap': peak > concurrency,
            'seconds_at_each_pending_count': dict(sorted(occupancy.items(), key=lambda item: int(item[0]))),
            'active_pending_intervals_right_censored_at_snapshot': known_pending,
            'terminal_uncertain_pending_intervals_excluded': unknown_pending,
            'definition': 'Half-open local requested_at→received_at checkpoint intervals; active pending ends at snapshot. These include local gating/recording time and do not identify simultaneous provider executions.'},
        'loaded_window': loaded_window(segments, accepted_times, concurrency,
                                       minimum_seconds=minimum_seconds,
                                       minimum_completions=minimum_completions),
        'loaded_window_criteria': {'minimum_duration_seconds': minimum_seconds,
                                   'minimum_accepted_completions': minimum_completions,
                                   'minimum_time_fraction_at_N_minus_1_pending': .9},
        'complete_conversation_seconds': descriptive(completed_durations),
        'recorded_call_duration_seconds': descriptive([t['duration_seconds'] for t in recorded
                                                       if isinstance(t.get('duration_seconds'), (int, float))]),
        'per_effort': per_effort,
        'interpretation': ['Reservations, recorded responses, native successful calls and completed conversations are different counts.',
                           'Live state and budget reads are not an atomic multi-file snapshot; small differences can reflect concurrent writes.',
                           'Loaded-window rate is descriptive and not a causal comparison with historical or other-model runs.',
                           'A missing qualifying window is not a capacity failure; this command does not authorize or stop collection.',
                           'No response judgments or scientific outcome values are inspected for these metrics.'],
    }


def load_observations(work_dir, scope='evaluation', attempt='01', first_jobs=None, job_ids=None):
    """Read completed state archives and current states, deduplicated by trial."""
    work_dir = Path(work_dir)
    source_metadata, selected_states, budgets, planned = [], {}, [], None
    if scope == 'calibration':
        if Path(attempt).name != attempt:
            raise ValueError('Calibration attempt must be one path component')
        directories = [work_dir / 'calibration' / ('attempt-' + attempt)]
        planned = 18
    elif scope == 'evaluation':
        directories = sorted(p for p in (work_dir / 'jobs').iterdir() if p.is_dir())
        if job_ids:
            wanted = set(job_ids)
            directories = [p for p in directories if p.name in wanted]
            if {p.name for p in directories} != wanted:
                raise ValueError('A requested job directory is missing')
        if first_jobs is not None:
            if first_jobs < 1:
                raise ValueError('first_jobs must be positive')
            directories = directories[:first_jobs]
        planned = 0
    else:
        raise ValueError('Unknown scope')

    def read_archive(path):
        with tarfile.open(path, 'r:gz') as archive:
            for member in archive:
                parts = Path(member.name).parts
                if member.isfile() and 'states' in parts and member.name.endswith('.json'):
                    state = json.load(archive.extractfile(member))
                    selected_states[state['trial']['trial_id']] = state
        source_metadata.append({'kind': 'archive', 'path': str(path.resolve()), 'sha256': digest(path)})

    for directory in directories:
        if not directory.is_dir():
            raise ValueError(f'Missing local work directory: {directory}')
        archive_path = work_dir / 'archives' / (directory.name + '.tar.gz')
        had_archive = scope == 'evaluation' and archive_path.is_file()
        if had_archive:
            read_archive(archive_path)
        for path in sorted((directory / 'states').glob('*.json')):
            try:
                content = path.read_bytes()
            except FileNotFoundError:
                continue  # An archive may have replaced loose files during this read.
            state = json.loads(content)
            selected_states[state['trial']['trial_id']] = state
            source_metadata.append({'kind': 'state', 'path': str(path.resolve()),
                                    'sha256': hashlib.sha256(content).hexdigest()})
        if scope == 'evaluation' and not had_archive and archive_path.is_file():
            read_archive(archive_path)
        budget_path = directory / 'budget.json'
        if budget_path.is_file():
            content = budget_path.read_bytes()
            budgets.append(json.loads(content)['used'])
            source_metadata.append({'kind': 'budget', 'path': str(budget_path.resolve()),
                                    'sha256': hashlib.sha256(content).hexdigest()})
        if scope == 'evaluation':
            claim_path = directory / 'claim.private.json'
            if claim_path.is_file():
                if planned is not None:
                    planned += len(json.loads(claim_path.read_text())['trial_ids'])
            else:
                planned = None
    reserved = sum(budgets) if len(budgets) == len(directories) else None
    return list(selected_states.values()), reserved, planned, source_metadata, [p.name for p in directories]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work-dir', type=Path, required=True)
    p.add_argument('--scope', choices=('evaluation', 'calibration'), default='evaluation')
    p.add_argument('--attempt', default='01')
    p.add_argument('--first-jobs', type=int)
    p.add_argument('--job-id', action='append')
    p.add_argument('--concurrency', type=int, default=3)
    p.add_argument('--expected-sessions', type=int)
    p.add_argument('--minimum-loaded-seconds', type=float, default=120)
    p.add_argument('--minimum-loaded-completions', type=int, default=50)
    args = p.parse_args()
    if args.concurrency < 1 or args.minimum_loaded_seconds <= 0 or args.minimum_loaded_completions < 1:
        p.error('Concurrency and loaded-window thresholds must be positive')
    begun = datetime.now(timezone.utc).isoformat()
    states, reserved, expected, sources, units = load_observations(
        args.work_dir, args.scope, args.attempt, args.first_jobs, args.job_id)
    expected = args.expected_sessions if args.expected_sessions is not None else expected
    summary = summarize(states, reserved, expected, args.concurrency,
                        minimum_seconds=args.minimum_loaded_seconds,
                        minimum_completions=args.minimum_loaded_completions)
    summary.update({'scope': args.scope, 'selected_units': units,
                    'work_directory': str(args.work_dir.resolve()),
                    'read_started_utc': begun, 'sources': sources,
                    'source_metadata_sha256': hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest(),
                    'measure_script_sha256': digest(__file__),
                    'new_model_calls': 0, 'mutations': 0})
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
