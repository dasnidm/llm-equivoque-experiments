"""Offline concurrency and load-policy checks; no provider calls."""
import multiprocessing
import subprocess
from pathlib import Path
import tempfile
import time
import unittest

from .fast_pacing import SharedTurnPacer, StageResult, next_stage
from .fast_coordination import SharedBoardCoordinator
from .coordination import GitCoordinator, new_board
from .fast_profile import FastGatedTransport
from .test_worker import _Gate, _Transport


def _send_worker(path, queue, count):
    pacer = SharedTurnPacer(path, 1000)
    for _ in range(count):
        def permission():
            # Simulate expensive remote permission checks; these must overlap.
            time.sleep(0.02)
        pacer.send(permission, lambda: queue.put(time.monotonic()))


def _board_worker(remote, root, model, queue):
    try:
        coordinator = SharedBoardCoordinator(remote, 'board', Path(root)/('cache-'+model),
                                             shared_board_lock=Path(root)/'board.lock')
        token = coordinator.claim_model(model, 'owner-'+model, concurrency=1)
        coordinator.heartbeat(model, 'owner-'+model, token)
        queue.put((model, 'ok'))
    except Exception as exc:
        queue.put((model, type(exc).__name__))


class FastPacingTests(unittest.TestCase):
    def test_multi_process_actual_send_spacing(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = multiprocessing.get_context('fork')
            queue = ctx.Queue()
            procs = [ctx.Process(target=_send_worker, args=(str(Path(d)/'pace'), queue, 3)) for _ in range(5)]
            for p in procs: p.start()
            stamps = sorted(queue.get(timeout=10) for _ in range(15))
            for p in procs:
                p.join(10)
                self.assertEqual(p.exitcode, 0)
            self.assertTrue(all(b-a >= 0.055 for a,b in zip(stamps, stamps[1:])), stamps)
            # 15 x 60ms slots: overlapping permission checks should avoid
            # adding 15 x 20ms to the admission critical path.
            self.assertLess(stamps[-1]-stamps[0], 1.2)

    def test_sweep_increases_stops_and_reports_plateau(self):
        first = StageResult(100, 150, 90)
        second = StageResult(110, 165, 90)
        plateau = StageResult(120, 166, 90)
        self.assertEqual(next_stage(first)['target_rpm'], 110)
        self.assertEqual(next_stage(second, first)['target_rpm'], 120)
        self.assertEqual(next_stage(plateau, second)['action'], 'plateau')
        self.assertEqual(next_stage(StageResult(130, 120, 91, native_429=1))['action'], 'stop')
        self.assertEqual(next_stage(StageResult(100, 160, 100, telemetry_complete=False))['action'], 'stop')
        self.assertEqual(next_stage(StageResult(100, 149, 90))['action'], 'measure_more')
        underfilled = StageResult(110, 150, 120, concurrency=7)
        self.assertEqual(next_stage(underfilled)['action'], 'increase_concurrency')
        self.assertEqual(next_stage(underfilled)['concurrency'], 14)
        with self.assertRaises(ValueError):
            StageResult(float('nan'), 150, 90)
        with self.assertRaises(ValueError):
            next_stage(first, second)

    def test_seven_concurrent_dashboard_writers_do_not_conflict(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            remote = root/'remote.git'
            subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
            models = [f'model-{i}' for i in range(7)]
            jobs = [{'job_id': 'job-'+m, 'model': m, 'trial_ids': ['trial-'+m],
                     'n_trials': 1, 'call_cap': 34, 'stage': 'initial-50'} for m in models]
            board = new_board('test-run', 'a'*64, 'b'*40, jobs,
                              global_stop=False, global_max_concurrency=7)
            coord = GitCoordinator(str(remote), 'board', root/'bootstrap')
            coord.bootstrap(board)
            ctx = multiprocessing.get_context('fork')
            queue = ctx.Queue()
            workers = [ctx.Process(target=_board_worker, args=(str(remote), str(root), m, queue)) for m in models]
            for w in workers: w.start()
            results = [queue.get(timeout=45) for _ in workers]
            for w in workers:
                w.join(10)
                self.assertEqual(w.exitcode, 0)
            self.assertTrue(all(status == 'ok' for _, status in results), results)
            self.assertEqual(sum(bool(x['owner']) for x in coord.status()['models'].values()), 7)

    def test_fast_profile_halts_on_compaction_or_failed_response(self):
        for response in ({'ok': True, 'compaction_events': 1}, {'ok': False, 'compaction_events': 0}):
            gate = _Gate()
            transport = FastGatedTransport(_Transport(response), gate)
            self.assertEqual(transport.request(), response)
            self.assertTrue(gate.stopped.is_set())
            self.assertTrue(transport.transport.stop_requested())


if __name__ == '__main__':
    unittest.main()
