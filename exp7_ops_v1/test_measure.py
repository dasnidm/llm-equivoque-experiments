"""Scientific counting and observed-concurrency invariants; no model calls."""
from datetime import datetime, timezone
import unittest

from .measure import iso, loaded_window, overlap_segments, summarize


def state(tid, status, intervals, effort='low', pending=None):
    turns = [{'turn': i, 'requested_at': iso(a), 'received_at': iso(b),
              'ok': ok, 'duration_seconds': b - a}
             for i, (a, b, ok) in enumerate(intervals, 1)]
    return {'trial': {'trial_id': tid, 'effort': effort}, 'status': status,
            'started_at': iso(intervals[0][0] if intervals else pending),
            'ended_at': iso(intervals[-1][1]) if status != 'active' and intervals else None,
            'turns': turns,
            'pending_turn': {'turn': len(turns) + 1, 'requested_at': iso(pending)} if pending is not None else None}


class MeasureTests(unittest.TestCase):
    def test_touching_requests_and_zero_duration_do_not_inflate_peak(self):
        segments = overlap_segments([(0, 10), (10, 20), (10, 10)])
        self.assertEqual(segments, [(0, 10, 1), (10, 20, 1)])
        self.assertEqual(max(n for _, _, n in segments), 1)

    def test_overlapping_success_and_failure_both_count_as_inflight(self):
        states = [state('one', 'complete', [(0, 10, True)]),
                  state('two', 'failed', [(5, 15, False)])]
        result = summarize(states, reserved_calls=2, expected_sessions=2,
                           concurrency=2, snapshot=20, minimum_seconds=1,
                           minimum_completions=1)
        self.assertEqual(result['request_overlap']['observed_local_pending_peak'], 2)
        self.assertEqual(result['recorded_calls'], 2)
        self.assertEqual(result['successful_calls'], 1)
        self.assertEqual(result['failed_recorded_calls'], 1)
        self.assertEqual(result['whole_batch']['end_utc'], iso(15))
        self.assertEqual(result['whole_batch']['successful_calls_per_minute'], 4)
        self.assertFalse(result['all_expected_complete'])

    def test_active_pending_is_censored_and_never_counted_as_success(self):
        item = state('one', 'active', [(0, 5, True)], pending=6)
        result = summarize([item], reserved_calls=2, expected_sessions=18,
                           concurrency=10, snapshot=10, minimum_seconds=1,
                           minimum_completions=1)
        self.assertEqual(result['successful_calls'], 1)
        self.assertEqual(result['reserved_calls'], 2)
        self.assertEqual(result['active_pending_requests'], 1)
        self.assertEqual(result['unstarted_expected_sessions'], 17)
        self.assertEqual(result['request_overlap']['observed_local_pending_peak'], 1)
        self.assertIsNone(result['loaded_window'])

    def test_interrupted_uncertain_request_is_not_assumed_still_running(self):
        item = state('one', 'interrupted', [(0, 5, True)], pending=6)
        result = summarize([item], reserved_calls=2, expected_sessions=1,
                           concurrency=1, snapshot=10000, minimum_seconds=1,
                           minimum_completions=1)
        self.assertEqual(result['terminal_uncertain_pending_requests'], 1)
        self.assertEqual(result['active_pending_requests'], 0)
        self.assertEqual(result['request_overlap']['seconds_at_each_pending_count'], {'1': 5})
        self.assertEqual(result['successful_calls'], 1)

    def test_longest_loaded_window_does_not_choose_short_highest_rate(self):
        # Two occupied lanes: ten quick completions, then two long calls.
        # The tempting first five seconds have much higher throughput.
        lane = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 100)]
        intervals = lane + lane
        segments = overlap_segments(intervals)
        accepted = [end for _, end in intervals]
        result = loaded_window(segments, accepted, 3, minimum_seconds=1,
                               minimum_fraction=.9, minimum_completions=1)
        self.assertEqual(result['duration_seconds'], 100)
        self.assertEqual(result['accepted_completions'], 12)
        self.assertAlmostEqual(result['successful_calls_per_minute'], 7.2)

    def test_negative_intervals_and_duplicate_conversations_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'predates'):
            overlap_segments([(2, 1)])
        item = state('same', 'complete', [(0, 1, True)])
        with self.assertRaisesRegex(ValueError, 'Duplicate conversation'):
            summarize([item, item], snapshot=2)


if __name__ == '__main__':
    unittest.main()
