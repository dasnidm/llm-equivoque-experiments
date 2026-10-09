import collections
import itertools
import json
import multiprocessing
from pathlib import Path
import re
import tempfile
import unittest
import uuid

from equivoque.core import ROOT, branches, read_json, write_json
from equivoque.transport import provider_schema
from equivoque2.audit import audit_worker
from equivoque2.protocol import CONFIG, RepeatedProtocol, phase
from equivoque2.runner import run_trial
from equivoque2.schedule import build
from equivoque2.scheduler import Permit


def scheduling_probe(directory, worker, results, release):
    permit = Permit(directory, worker, [2, 5, 10, 20])
    try:
        granted = permit.acquire('SIMULATION-ONLY/' + worker)
        results.put((worker, granted))
        if granted:
            release.wait(5)
            permit.release()
    finally:
        permit.lock.close()


class SimulationTransport:
    name = 'simulation-only'

    def __init__(self, fail_at=None, native_files=False):
        self.calls, self.fail_at, self.native_files = 0, fail_at, native_files
        if native_files:
            self.name = 'codex-native'

    def request(self, trial, prompt, schema, session_id, directory, attempt):
        self.calls += 1
        session_id = session_id or str(uuid.uuid4())
        r, local = phase(attempt)
        if local == 1:
            answer = {'selection': schema['properties']['selection']['items']['enum'][:2]}
        elif local == 2:
            answer = {'selection': schema['properties']['selection']['enum'][0]}
        else:
            m = 4 if attempt == 10 else r
            answer = {'freedom': 100, 'impact': [100, 60, 30, 1][m - 1],
                      'counterfactual': 'yes' if m < 3 else 'no'}
        text = json.dumps(answer)
        events = [{'type': 'thread.started', 'thread_id': session_id},
                  {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': text}},
                  {'type': 'turn.completed', 'usage': {'input_tokens': 0, 'output_tokens': 0}}]
        result = {'ok': attempt != self.fail_at, 'session_id': session_id, 'text': text,
            'events': events, 'tool_events': [], 'metadata_fallback': False,
            'usage': {'input_tokens': 0, 'output_tokens': 0}, 'duration_seconds': 0.001,
            'provider_schema': provider_schema(schema), 'stderr': 'SIMULATION ONLY\n'}
        if self.native_files:
            directory = Path(directory)
            directory.mkdir(parents=True, exist_ok=True)
            (directory / 'subject-system.txt').write_text(RepeatedProtocol().data['system'])
            (directory / f'turn-{attempt:02d}.schema.json').write_text(json.dumps(provider_schema(schema)))
            (directory / f'turn-{attempt:02d}.events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events))
            (directory / f'turn-{attempt:02d}.stderr.txt').write_text(result['stderr'])
        return result


class Experiment2Tests(unittest.TestCase):
    def setUp(self):
        self.config = read_json(CONFIG)
        self.protocol = RepeatedProtocol()
        self.cases, self.assigned = build(self.config)

    def test_exact_original_base_and_measurement_block(self):
        self.assertEqual(self.protocol.data, read_json(ROOT / 'protocol/prompts.v1.json'))
        trial = self.assigned['a'][0]
        for turn in range(1, 11):
            p = self.protocol.prompt(trial, turn, 'K', ['A', 'B'])
            if turn in (3, 6, 9, 10):
                self.assertTrue(p.endswith(self.protocol.data['frames'][trial['frame']]['evaluation']))
                self.assertEqual(p.count(self.protocol.spec['measurement_scope']), 1)
            self.assertEqual('was fixed' in p, turn == 10)
        disclosure = self.protocol.prompt(trial, 10)
        self.assertEqual(disclosure.count('| --- | --- | --- | --- |'), 3)
        self.assertIn('for all three rounds', disclosure)

    def test_balanced_420_trial_twenty_worker_assignment(self):
        self.assertEqual((self.cases, self.assigned), build(self.config))
        self.assertEqual(sorted(collections.Counter(c['target'] for c in self.cases).values()), [2, 2, 3, 3])
        for r in range(3):
            counts = collections.Counter(c['round_orders'][r].index(c['target']) for c in self.cases)
            self.assertEqual(sorted(counts.values()), [2, 2, 3, 3])
        seen, pairs, frame_loads = set(), collections.defaultdict(list), collections.Counter()
        for worker, trials in self.assigned.items():
            self.assertEqual(len(trials), 21)
            self.assertEqual(len({t['configuration_id'] for t in trials}), 21)
            frame_loads[collections.Counter(t['frame'] for t in trials)['cards']] += 1
            for t in trials:
                self.assertNotIn(t['trial_id'], seen)
                seen.add(t['trial_id'])
                self.assertEqual(len({tuple(o) for o in t['round_orders']}), 3)
                pairs[(t['configuration_id'], t['case_id'])].append(t)
        self.assertEqual(len(seen), 420)
        self.assertEqual(frame_loads, {10: 10, 11: 10})
        for pair in pairs.values():
            self.assertEqual({t['frame'] for t in pair}, {'cards', 'cats'})
            self.assertEqual(pair[0]['round_orders'], pair[1]['round_orders'])
            self.assertEqual(pair[0]['target'], pair[1]['target'])

    def test_all_branches_remain_fixed_and_cards_hide_internal_codes(self):
        for c in self.cases:
            for frame in ('cards', 'cats'):
                trial = {**c, 'frame': frame}
                for r, order in enumerate(c['round_orders'], 1):
                    for branch in branches(order, c['target']):
                        self.assertEqual(branch['final'], c['target'])
                        for local in (1, 2, 3):
                            turn = (r - 1) * 3 + local
                            p = self.protocol.prompt(trial, turn,
                                branch['route'][0 if local == 2 else 1], branch['remaining'])
                            self.assertNotIn('was fixed', p)
                            if frame == 'cards':
                                self.assertIsNone(re.search(r'\b[A-D]\b', p))
                if frame == 'cards':
                    self.assertIsNone(re.search(r'\b[A-D]\b', self.protocol.prompt(trial, 10)))

    def test_full_simulation_4200_turns_and_unique_sessions(self):
        transport, sessions = SimulationTransport(), set()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for worker, trials in self.assigned.items():
                manifest = root / f'{worker}.json'
                write_json(manifest, {'run_id': self.config['run_id'], 'worker_id': worker, 'trials': trials})
                output = root / worker
                for t in trials:
                    path = output / 'trials' / (t['trial_id'].replace('/', '__') + '.json')
                    state = run_trial(t, self.protocol, transport, path, root / 'scratch')
                    self.assertEqual(state['status'], 'complete')
                    self.assertEqual(len(state['turns']), 10)
                    self.assertEqual({record['session_id'] for record in state['turns']}, {state['session_id']})
                    self.assertNotIn(state['session_id'], sessions)
                    sessions.add(state['session_id'])
                    for r in state['rounds']:
                        self.assertEqual(r['remaining'], [t['target']])
                report = audit_worker(manifest, output, allow_simulation=True)
                self.assertTrue(report['integrity_ok'], report['errors'][:3])
                self.assertEqual(report['subject_invocations'], 210)
                self.assertEqual(report['valid_measurements'], {'m1': 21, 'm2': 21, 'm3': 21, 'm4': 21})
                self.assertFalse(audit_worker(manifest, output)['integrity_ok'])
            self.assertEqual(transport.calls, 4200)
            before = transport.calls
            run_trial(t, self.protocol, transport, path, root / 'scratch')
            self.assertEqual(transport.calls, before)

    def test_failed_and_uncertain_turns_never_replayed(self):
        trial = self.assigned['a'][0]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'trials/trial.json'
            transport = SimulationTransport(fail_at=8)
            state = run_trial(trial, self.protocol, transport, path, temporary)
            self.assertEqual(state['status'], 'failed')
            self.assertEqual(state['turns'][2]['parsed']['impact'], 100)
            self.assertEqual(state['turns'][5]['parsed']['impact'], 60)
            run_trial(trial, self.protocol, transport, path, temporary)
            self.assertEqual(transport.calls, 8)
            state.update(status='active', pending_turn={'turn': 9})
            write_json(path, state)
            self.assertEqual(run_trial(trial, self.protocol, transport, path, temporary)['status'], 'interrupted')
            self.assertEqual(transport.calls, 8)

    def test_safe_partial_resume_uses_only_next_unrequested_turn(self):
        trial = self.assigned['b'][0]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'trials/trial.json'
            transport = SimulationTransport()
            state = run_trial(trial, self.protocol, transport, path, temporary)
            state.update(status='active', turns=state['turns'][:6], pending_turn=None)
            state['rounds'][2].update(remaining=list(trial['round_orders'][2]), route='')
            write_json(path, state)
            state = run_trial(trial, self.protocol, transport, path, temporary)
            self.assertEqual(transport.calls, 14)
            self.assertEqual(state['status'], 'complete')

    def test_native_archive_and_journal_tampering_detected(self):
        trial = {**self.assigned['a'][0], 'trial_id': 'SIMULATION-ONLY/native-archive-test'}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / 'manifest.json'
            write_json(manifest, {'run_id': self.config['run_id'], 'worker_id': 'a', 'trials': [trial]})
            state = run_trial(trial, self.protocol, SimulationTransport(native_files=True),
                              root / 'results/trials/trial.json', root / 'scratch')
            report = audit_worker(manifest, root / 'results')
            self.assertTrue(report['integrity_ok'], report['errors'])
            self.assertEqual(report['raw_files_verified'], 31)
            source = root / 'results' / state['turns'][-1]['raw_files'][0]['path']
            source.write_text('TAMPERED')
            self.assertFalse(audit_worker(manifest, root / 'results')['integrity_ok'])

    def test_concurrency_limit_and_halt_preserve_active_trials(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_json(root / 'queue.json', {'queue': [], 'active': []})
            write_json(root / 'limit.json', {'limit': 2})
            results, release = multiprocessing.Queue(), multiprocessing.Event()
            processes = [multiprocessing.Process(target=scheduling_probe, args=(root, str(i), results, release)) for i in range(4)]
            try:
                for p in processes:
                    p.start()
                self.assertTrue(results.get(timeout=4)[1])
                self.assertTrue(results.get(timeout=4)[1])
                self.assertEqual(len(read_json(root / 'queue.json')['active']), 2)
                coordinator = Permit(root, 'coordinator', [2, 5, 10, 20])
                coordinator.halt({'reason': 'SIMULATION ONLY'})
                coordinator.lock.close()
                self.assertFalse(results.get(timeout=4)[1])
                self.assertFalse(results.get(timeout=4)[1])
                self.assertEqual(len(read_json(root / 'queue.json')['active']), 2)
                release.set()
                for p in processes:
                    p.join(4)
                    self.assertEqual(p.exitcode, 0)
                self.assertEqual(read_json(root / 'queue.json'), {'queue': [], 'active': []})
            finally:
                release.set()
                for p in processes:
                    if p.is_alive():
                        p.terminate()
                    p.join(4)


if __name__ == '__main__':
    unittest.main()
