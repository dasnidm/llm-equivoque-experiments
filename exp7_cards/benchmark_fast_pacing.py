"""Synthetic multiprocessing benchmark; numbers are not live-model throughput."""
import json
import multiprocessing
from pathlib import Path
import tempfile
import time

from .fast_pacing import SharedTurnPacer, shared_lock


def worker(mode, path, count, queue):
    def permission():
        time.sleep(.04)  # stand-in for a slow dashboard lookup
    pacer = SharedTurnPacer(path, 1000)
    for _ in range(count):
        if mode == 'new':
            pacer.send(permission, lambda: queue.put(time.monotonic()))
        else:
            with shared_lock(path) as lock:
                lock.seek(0)
                raw = lock.read().strip()
                previous = float(raw) if raw else 0
                time.sleep(max(0, previous+.06-time.monotonic()))
                permission()
                now = time.monotonic()
                lock.seek(0);lock.truncate();lock.write(str(now));lock.flush()
                queue.put(now)


def run(mode):
    with tempfile.TemporaryDirectory() as d:
        ctx = multiprocessing.get_context('fork')
        queue = ctx.Queue()
        workers = [ctx.Process(target=worker, args=(mode, str(Path(d)/'pace'), 4, queue)) for _ in range(5)]
        for w in workers:w.start()
        stamps = sorted(queue.get(timeout=15) for _ in range(20))
        for w in workers:
            w.join(10)
            if w.exitcode != 0:raise RuntimeError('synthetic worker failed')
        duration = stamps[-1]-stamps[0]
        return {'mode': mode, 'requests': len(stamps), 'elapsed_seconds': duration,
                'completed_per_minute': 60*(len(stamps)-1)/duration}


if __name__ == '__main__':
    old, new = run('old'), run('new')
    print(json.dumps({'scope': 'synthetic local timing; not provider capacity', 'old': old,
                      'new': new, 'relative_speed': new['completed_per_minute']/old['completed_per_minute']}, indent=2))
