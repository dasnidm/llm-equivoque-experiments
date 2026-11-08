"""Separate technical CLI comparison; never modifies a scientific freeze.

The original persistent adapter, prompts, schemas and audits remain unchanged.
Only an explicit CLI version/binary and initialize client-version metadata are
adapted. Each invocation has fresh trials, an immutable profile and no replay.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import unittest

import exp7_persistent.transport as native
from equivoque.transport import overrides

BASE_TRANSPORT = native.PersistentTransport
BASE_CONVERSATION = native._Conversation
ALLOWED = {'0.159.0-alpha.3', '0.167.0', '0.169.0-alpha.3'}


def isolated_sqlite_launcher(root, stage, binary):
    """Use the supported DB-only override in the child, retaining native auth."""
    database = (root / 'native-dbs' / stage).resolve()
    shims = root / 'shims'
    shims.mkdir(exist_ok=True)
    launcher = shims / (stage + '.py')
    source = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
settings = %r
env = os.environ.copy()
if 'app-server' in sys.argv[1:]:
    database = Path(settings['database'])
    database.mkdir(parents=True, exist_ok=True)
    env['CODEX_SQLITE_HOME'] = str(database)
    env['RUST_LOG'] = env.get('RUST_LOG', 'error') + ',codex_core::responses_retry=warn'
    launches = database / 'launches'
    launches.mkdir(exist_ok=True)
    with (launches / (str(os.getpid()) + '.json')).open('x') as out:
        json.dump({'pid': os.getpid(), 'sqlite_home': str(database),
                   'native_home_preserved': True, 'proxy_environment_inherited': True,
                   'native_retry_log_level': 'warn'}, out)
os.execve(settings['binary'], [settings['binary']] + sys.argv[1:], env)
""" % {'binary': str(binary), 'database': str(database)}
    with launcher.open('x') as out:
        out.write(source)
    launcher.chmod(0o700)
    return launcher, database


def initialize_sqlite_without_inference(root, stage):
    """One serial app-server initialize; no thread/start or turn/start."""
    directory = root / 'warmups' / stage
    directory.mkdir(parents=True, exist_ok=False)
    subject = directory / 'subject'
    subject.mkdir()
    native.isolation_preflight(subject)
    system = directory / 'subject-system.txt'
    native._write(system, 'Technical startup only. No model request is submitted.')
    catalog = Path(__file__).resolve().parents[1] / 'manifests/equivoque-2026-11-08-exp7-persistent-v1/model-catalog.json'
    transport = native.PersistentTransport(catalog_path=catalog)
    command = transport._command({'effort': 'medium'}, system)
    conversation = native._Conversation(command, subject, directory, ())
    try:
        with (directory / 'rpc-sent.jsonl').open('xb') as sent, (directory / 'rpc-received.jsonl').open('xb') as received:
            conversation.rpc('initialize', {'clientInfo': {'name': 'codex_exec', 'version': ''},
                             'capabilities': {'experimentalApi': True}}, time.monotonic() + 30, sent, received, [])
            conversation.send({'method': 'initialized'}, sent)
    finally:
        conversation.close()
    if conversation.process.returncode not in (0, -15):
        raise RuntimeError('Serial SQLite initialization did not exit normally')
    with (directory / 'summary.json').open('x') as out:
        json.dump({'success': True, 'model_requests': 0, 'methods': ['initialize', 'initialized']}, out)
    return directory


def select_adapter(version, binary):
    """Version-specific adapter in this process, outside the frozen packages."""
    if version not in ALLOWED:
        raise ValueError('CLI version is outside the recorded comparison')
    expected = 'codex-cli ' + version
    binary = str(Path(binary).resolve())
    if subprocess.check_output([binary, '--version'], text=True, timeout=10).strip() != expected:
        raise ValueError('Selected binary version mismatch')

    class VersionedConversation(BASE_CONVERSATION):
        def send(self, message, sent):
            if message.get('method') == 'initialize':
                message = json.loads(json.dumps(message))
                message['params']['clientInfo']['version'] = version
            return super().send(message, sent)

    class VersionedTransport(BASE_TRANSPORT):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault('codex_binary', binary)
            super().__init__(*args, **kwargs)

        def _command(self, trial, system_path):
            if not self._cli_verified:
                actual = subprocess.check_output([self.codex_binary, '--version'], text=True, timeout=10).strip()
                if actual != expected:
                    raise ValueError('Comparison CLI version changed')
                self._cli_verified = True
            command = [self.codex_binary, 'app-server', '--stdio']
            command += overrides(system_path, trial['effort'])
            if self.catalog_path:
                if native.digest(self.catalog_path) != self.catalog_sha256:
                    raise ValueError('Original model catalog changed')
                snapshot = system_path.parent / 'model-catalog.json'
                if not snapshot.exists():
                    native._write(snapshot, self.catalog_path.read_text())
                if native.digest(snapshot) != self.catalog_sha256:
                    raise ValueError('Conversation catalog differs from source')
                command += ['-c', 'model_catalog_json=' + json.dumps(str(snapshot))]
            return command

    native.PersistentTransport = VersionedTransport
    native._Conversation = VersionedConversation
    return VersionedTransport


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version', required=True, choices=sorted(ALLOWED))
    p.add_argument('--binary', required=True, type=Path)
    p.add_argument('--root', required=True, type=Path)
    p.add_argument('--stage', required=True)
    p.add_argument('--offline', action='store_true')
    p.add_argument('--sqlite-isolation', action='store_true',
                   help='Supported child-only CODEX_SQLITE_HOME, with serial migration and unchanged auth')
    p.add_argument('--pool', type=int, default=4)
    p.add_argument('--sessions', type=int, default=4)
    p.add_argument('--account-interval', type=float, default=.75)
    p.add_argument('--models', nargs='+', default=['gpt-6-astra', 'gpt-5.6-sol'])
    args = p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.stage):
        p.error('Invalid stage name')
    if not args.offline and not args.sqlite_isolation:
        p.error('Live comparison requires isolated native SQLite retry telemetry')
    args.root.mkdir(parents=True, exist_ok=True)
    if not args.offline and (args.root / 'HALT').exists():
        raise RuntimeError('Technical STOP is active; no startup or inference is permitted')
    profile_path = args.root / (args.stage + '.comparison-profile.json')
    if profile_path.exists():
        raise FileExistsError('A comparison stage cannot be replayed')
    binary = args.binary.resolve()
    effective_binary, database = binary, None
    if args.sqlite_isolation:
        effective_binary, database = isolated_sqlite_launcher(args.root, args.stage, binary)
    select_adapter(args.version, effective_binary)
    profile = {'version': args.version, 'binary': str(binary),
               'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
               'comparison_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'original_transport_source_sha256': hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest(),
               'offline': args.offline, 'sample_inclusion': False,
               'changes': ['CLI binary and supported version', 'initialize clientInfo.version'],
               'preserved': ['frozen system and prompts', 'schemas', 'model catalog', 'effort',
                             '34-turn order', 'original RPC retention', 'independent fresh process and thread',
                             'tool use rejection', 'no request replay', 'main STOP'],
               'pool': args.pool, 'sessions': args.sessions, 'models': args.models,
               'account_interval_seconds': args.account_interval}
    if database:
        profile.update(sqlite_home=str(database), sqlite_isolation=True,
                       launcher=str(effective_binary), launcher_sha256=hashlib.sha256(effective_binary.read_bytes()).hexdigest())
        profile['changes'].append('Child-only supported CODEX_SQLITE_HOME; serial DB migration before pool launch')
        profile['changes'].append('Expose codex_core::responses_retry warnings in child stderr; does not disable retries')
    with profile_path.open('x') as out:
        json.dump(profile, out, indent=2); out.write('\n')
    if args.offline:
        # Existing fixture uses dummy auth, a child-only home and loopback;
        # real authentication is never copied, modified or read by this test.
        os.environ['CODEX_TEST_BINARY'] = str(effective_binary)
        from exp7_persistent import test_real_cli
        original_events = test_real_cli.LocalResponses.events
        wire_path = args.root / (args.stage + '.offline-wire.jsonl')
        def retain_wire(service, body, transport, connection_id):
            with wire_path.open('a') as wire:
                wire.write(json.dumps({'body': body, 'transport': transport,
                                       'connection_id': connection_id}) + '\n')
            return original_events(service, body, transport, connection_id)
        test_real_cli.LocalResponses.events = retain_wire
        tests = unittest.defaultTestLoader.loadTestsFromTestCase(test_real_cli.RealCliIntegrationTests)
        with (args.root / (args.stage + '.offline.log')).open('x') as log:
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(tests)
        summary = {'tests_run': result.testsRun, 'passed': result.wasSuccessful(),
                   'errors': len(result.errors), 'failures': len(result.failures)}
        with (args.root / (args.stage + '.offline-summary.json')).open('x') as out:
            json.dump(summary, out, indent=2); out.write('\n')
        print(json.dumps(summary), flush=True)
        if not result.wasSuccessful():
            raise SystemExit(2)
        return
    import exp7_persistent_capacity_study as study
    study.MODELS = tuple(args.models)
    warmup = initialize_sqlite_without_inference(args.root, args.stage) if database else None
    # The measured harness meters turn/start admissions across all selected
    # models; no model-specific or provider-internal quota is inferred.
    sys.argv = [sys.argv[0], '--root', str(args.root), '--stage', args.stage,
                '--pool', str(args.pool), '--sessions', str(args.sessions),
                '--account-interval', str(args.account_interval), '--per-model-workers']
    try:
        study.main()
    finally:
        stage = args.root / args.stage
        if stage.is_dir():
            shutil.copyfile(profile_path, stage / 'version-profile.json')
            if database:
                shutil.copyfile(effective_binary, stage / 'cli-launcher.py')
                shutil.copytree(database, stage / 'native-sqlite')
            if warmup:
                shutil.copytree(warmup, stage / 'serial-db-initialization')
            from exp7_native_retry_audit import audit_native_retries
            native_audit = audit_native_retries(stage)
            with (stage / 'native-retry-audit.json').open('x') as out:
                json.dump(native_audit, out, indent=2); out.write('\n')
    if (not native_audit['available'] or native_audit['native_429_retry_log_records']
            or native_audit['other_native_retry_log_records']):
        raise SystemExit('Native telemetry did not establish a retry-free stage; preserve evidence and keep STOP')


if __name__ == '__main__':
    main()
