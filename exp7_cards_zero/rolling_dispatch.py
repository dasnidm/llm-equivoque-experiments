"""Bounded rolling dispatch; preserve slots for unresolved live sessions."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import time


def dispatch(trials, concurrency, run_one, reconcile, progress, poll_seconds=1):
    """Run assigned trials once; reconcile(held_trial) returns terminal state or None."""
    if type(concurrency) is not int or concurrency < 1:
        raise ValueError('Concurrency must be a positive integer')
    pending = iter(trials)
    active, held, done, exceptions = {}, {}, [], []
    exhausted = False
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        while active or held or not exhausted:
            for key, trial in list(held.items()):
                resolved = reconcile(trial)
                if resolved is not None:
                    done.append(resolved)
                    del held[key]
            while not exhausted and len(active) + len(held) < concurrency:
                try:
                    trial = next(pending)
                except StopIteration:
                    exhausted = True
                    break
                active[pool.submit(run_one, trial)] = trial
            progress(done, held, active, exceptions)
            if active:
                finished, _ = wait(active, timeout=poll_seconds, return_when=FIRST_COMPLETED)
                for future in finished:
                    trial = active.pop(future)
                    try:
                        state = future.result()
                    except Exception as exc:
                        exceptions.append({'trial': trial['trial_id'], 'type': type(exc).__name__})
                        state = reconcile(trial)
                    if state is None or state.get('status') == 'held':
                        held[trial['trial_id']] = trial
                    else:
                        done.append(state)
            elif held:
                time.sleep(poll_seconds)
    progress(done, held, active, exceptions)
    return done, exceptions
