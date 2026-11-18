"""Check rolling slot reuse and held-session accounting without model calls."""
import threading
import unittest

from .rolling_dispatch import dispatch


class DispatchTests(unittest.TestCase):
    def test_completed_slot_is_reused_while_another_session_is_running(self):
        third_started = threading.Event()
        trials = [{'trial_id': str(i)} for i in range(3)]
        def run(trial):
            if trial['trial_id'] == '0':
                self.assertTrue(third_started.wait(3), 'Third trial did not start while first was running')
            if trial['trial_id'] == '2':
                third_started.set()
            return {'trial': trial, 'status': 'complete'}
        states, errors = dispatch(trials, 2, run, lambda _: None,
                                  lambda *args: None, poll_seconds=.01)
        self.assertEqual(len(states), 3)
        self.assertFalse(errors)

    def test_held_live_session_retains_its_slot_until_reconciled(self):
        may_release = threading.Event()
        later_started = threading.Event()
        trials = [{'trial_id': str(i)} for i in range(2)]
        def run(trial):
            if trial['trial_id'] == '0':
                return {'trial': trial, 'status': 'held'}
            later_started.set()
            return {'trial': trial, 'status': 'complete'}
        def reconcile(trial):
            return {'trial': trial, 'status': 'failed'} if may_release.is_set() else None
        result = []
        thread = threading.Thread(target=lambda: result.append(dispatch(
            trials, 1, run, reconcile, lambda *args: None, poll_seconds=.01)))
        thread.start()
        self.assertFalse(later_started.wait(.1))
        may_release.set()
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertTrue(later_started.is_set())
        self.assertEqual(len(result[0][0]), 2)


if __name__ == '__main__':
    unittest.main()
