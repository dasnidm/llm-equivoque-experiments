"""Real CLI + loopback-only HTTP 429: verify native warnings reach stderr.

Dummy API credentials and a child-only test home are used. All non-loopback
HTTP(S) is blocked by the existing fixture. No real model is called.
"""
import argparse
import json
from pathlib import Path
import os
import signal
import tempfile
import threading
import time

from exp7_cli_upgrade_probe import select_adapter, isolated_sqlite_launcher
from exp7_native_retry_audit import RATE
from exp7_persistent.test_real_cli import LocalResponses, make_cli_wrapper
import exp7_persistent.transport as native


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--binary', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='retry-visibility-home-') as temporary, LocalResponses() as service:
        base = service.server.RequestHandlerClass
        counter = []

        class Limited(base):
            def limited(self):
                body = b'{"error":{"type":"rate_limit_error","message":"Synthetic loopback rate limit"}}'
                counter.append(time.monotonic())
                self.send_response(429)
                self.send_header('Retry-After', '20')
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                self.wfile.flush()

            do_GET = limited
            do_POST = limited

        service.server.RequestHandlerClass = Limited
        launcher, _ = isolated_sqlite_launcher(args.output, 'fixture', args.binary.resolve())
        wrapper = make_cli_wrapper(Path(temporary), launcher, service.base_url)
        select_adapter('0.167.0', wrapper)
        catalog = Path(__file__).resolve().parents[1] / 'manifests/equivoque-2026-11-08-exp7-persistent-v1/model-catalog.json'
        transport = native.PersistentTransport(timeout=15, catalog_path=catalog)
        outcome = []

        def request():
            try:
                result = transport.request({'trial_id': 'offline-retry-visibility', 'model': 'gpt-6.1-sol', 'effort': 'medium'},
                                           'Synthetic fixture: say ACK.', None, 'A local transport test.', None,
                                           args.output / 'native', 1)
                outcome.append({'returned_ok': result['ok']})
            except Exception as error:
                outcome.append({'exception_type': type(error).__name__})

        thread = threading.Thread(target=request, daemon=True)
        started = time.monotonic()
        thread.start()
        visible = False
        until = started + 10
        while time.monotonic() < until:
            log = args.output / 'native/process.stderr.log'
            if log.exists() and RATE.search(log.read_text(errors='replace')):
                visible = True
                break
            if not thread.is_alive():
                break
            time.sleep(.05)
        elapsed = time.monotonic() - started
        rpc_errors = 0
        for path in (args.output / 'native').glob('turn-*/rpc-received.jsonl'):
            rpc_errors += sum(json.loads(line).get('method') == 'error'
                              for line in path.read_text().splitlines())
        processes = list(transport._conversations.values())
        for conversation in processes:
            try:
                os.killpg(conversation.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        thread.join(timeout=5)
        transport.close()
        record = {'native_429_warning_visible_on_stderr': visible,
                  'seconds_to_visible_warning': elapsed,
                  'rpc_error_notifications_at_warning': rpc_errors,
                  'local_http_429_responses': len(counter), 'retry_after_seconds': 20,
                  'external_model_requests': 0, 'dummy_auth_and_blocked_external_proxy': True,
                  'request_thread_closed': not thread.is_alive(), 'outcome': outcome,
                  'scope': 'Warning visibility only; no provider at-most-once guarantee or account capacity inference.'}
        with (args.output / 'summary.json').open('x') as out:
            json.dump(record, out, indent=2); out.write('\n')
        print(json.dumps(record), flush=True)
        if not visible or thread.is_alive():
            raise SystemExit(2)


if __name__ == '__main__':
    main()
