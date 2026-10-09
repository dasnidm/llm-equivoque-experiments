"""Fair whole-trial permits shared by 20 isolated worker processes."""
import fcntl
import os
from pathlib import Path
import time

from equivoque.core import read_json, write_json
from equivoque.runner import now


class Permit:
    def __init__(self, directory, worker, allowed):
        self.directory = Path(directory)
        self.worker, self.allowed, self.pid = worker, allowed, os.getpid()
        self.lock = (self.directory / 'scheduler.lock').open('a')

    def transact(self, action):
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        try:
            q = read_json(self.directory / 'queue.json')
            result = action(q)
            write_json(self.directory / 'queue.json', q)
            return result
        finally:
            fcntl.flock(self.lock, fcntl.LOCK_UN)

    def acquire(self, trial_id):
        def enqueue(q):
            if any(item['pid'] == self.pid for item in q['queue'] + q['active']):
                raise ValueError('Worker already has a queued or active permit')
            q['queue'].append({'pid': self.pid, 'worker': self.worker,
                              'trial_id': trial_id, 'queued_at': now()})
        self.transact(enqueue)
        while True:
            def grant(q):
                if (self.directory / 'HALT.json').exists():
                    q['queue'] = [item for item in q['queue'] if item['pid'] != self.pid]
                    return False
                limit = read_json(self.directory / 'limit.json')['limit']
                if limit not in self.allowed:
                    raise ValueError('Unapproved concurrency limit')
                if len(q['active']) < limit and q['queue'] and q['queue'][0]['pid'] == self.pid:
                    item = q['queue'].pop(0)
                    item['granted_at'] = now()
                    q['active'].append(item)
                    return True
                return None
            granted = self.transact(grant)
            if granted is not None:
                return granted
            time.sleep(0.05)

    def release(self):
        def remove(q):
            if sum(item['pid'] == self.pid for item in q['active']) != 1:
                raise ValueError('Missing or duplicated active permit')
            q['active'] = [item for item in q['active'] if item['pid'] != self.pid]
        self.transact(remove)

    def halt(self, record):
        def write_once(q):
            if not (self.directory / 'HALT.json').exists():
                write_json(self.directory / 'HALT.json', record)
        self.transact(write_once)
