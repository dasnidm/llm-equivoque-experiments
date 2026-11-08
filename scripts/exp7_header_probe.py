"""Explicitly authorized, separate native-CLI response-header diagnostic.

The loopback relay forwards opaque native auth only to the fixed official Codex
endpoint, inheriting the managed proxy and CA. It never records request headers
or bodies. First upstream error stops new upstream admissions; no replay.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import http.server
import json
import logging
import os
from pathlib import Path
import re
import ssl
import threading
import time
import urllib.parse

import httpx

from exp7_cli_upgrade_probe import select_adapter, isolated_sqlite_launcher, initialize_sqlite_without_inference
from exp7_main_v2.coordination import GitCoordinator
from exp7_main_v2.protocol import MainProtocol
from exp7_main_v2.schedule import load_bundle
from exp7_main_v2.worker import verify_freeze
from exp7_main_v2.runner import run_trial
from exp7_pre.runner import CallBudget, atomic_json
from exp7_native_retry_audit import audit_native_retries
import exp7_persistent.transport as native

REPO = Path(__file__).resolve().parents[1]
BUNDLE = REPO / 'manifests/equivoque-2026-11-08-exp7-persistent-v1'
UPSTREAM = 'https://chatgpt.com/backend-api/codex'
HOP = {'host', 'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
       'te', 'trailer', 'transfer-encoding', 'upgrade', 'content-length'}
SAFE_HEADERS = {'retry-after', 'retry-after-ms', 'x-request-id', 'x-oai-request-id',
                'cf-ray', 'server', 'via', 'date', 'content-type', 'content-encoding',
                'openai-processing-ms', 'x-envoy-ratelimited', 'x-envoy-upstream-service-time'}


def now():
    return datetime.now(timezone.utc).isoformat()


def safe_headers(headers, secrets=()):
    out = {}
    for name, value in headers.items():
        key = name.lower()
        if (key in SAFE_HEADERS or key.startswith(('x-ratelimit-', 'ratelimit-'))
                or (key.startswith('x-codex-') and any(x in key for x in ('limit', 'window', 'percent', 'plan-type', 'reset')))):
            if any(x in key for x in ('token-value', 'authorization', 'cookie', 'credential', 'credits', 'balance', 'secret')):
                continue
            out[key] = '[omitted credential match]' if any(s and s in value.encode() for s in secrets) else value
    return out


class Gate:
    def __init__(self, root, interval, limit):
        self.root, self.interval, self.limit = Path(root), interval, limit
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.next_start = 0.
        self.count = 0
        self.reason = None

    def halt(self, reason):
        with self.lock:
            if self.reason is None:
                self.reason = reason
                with (self.root / 'HEADER_STOP.json').open('x') as out:
                    json.dump({'at': now(), 'reason': reason, 'upstream_started': self.count}, out, indent=2)
            self.stop.set()

    def admit(self):
        while True:
            with self.lock:
                if self.stop.is_set() or (self.root / 'HALT').exists():
                    return None
                if self.count >= self.limit:
                    break
                delay = self.next_start - time.monotonic()
                if delay <= 0:
                    self.count += 1
                    self.next_start = time.monotonic() + self.interval
                    return self.count
            if self.stop.wait(min(delay, .1)):
                return None
        self.halt('Prespecified upstream request budget reached')
        return None


class Relay:
    def __init__(self, root, gate, upstream=UPSTREAM, *, offline=False):
        if not offline and upstream != UPSTREAM:
            raise ValueError('Live credentials may only reach the fixed official upstream')
        parsed = urllib.parse.urlsplit(upstream)
        if offline and parsed.hostname not in ('127.0.0.1', 'localhost'):
            raise ValueError('Offline upstream must be loopback')
        self.root, self.gate, self.upstream = Path(root), gate, upstream.rstrip('/')
        self.lock = threading.Lock()
        self.records = []
        self._credential_values = set()
        self.received_requests = 0
        self.locally_denied_requests = 0
        # Default HTTPX transport has zero transport retries. trust_env=True
        # preserves the managed proxy, and the default SSL context uses its CA.
        self.client = httpx.Client(verify=ssl.create_default_context(), trust_env=True,
                                   follow_redirects=False, timeout=httpx.Timeout(100, connect=20))
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *args):
                pass

            def do_GET(self):
                with owner.lock:owner.received_requests += 1
                self.send_error(405)

            def do_POST(self):
                with owner.lock:owner.received_requests += 1
                if self.path != '/responses':
                    self.send_error(404)
                    return
                length = self.headers.get('Content-Length')
                if length is not None:
                    body = self.rfile.read(int(length))
                elif self.headers.get('Transfer-Encoding', '').lower() == 'chunked':
                    chunks = []
                    while True:
                        size = int(self.rfile.readline().split(b';', 1)[0].strip(), 16)
                        if not size:
                            while self.rfile.readline() not in (b'\r\n', b'\n', b''):
                                pass
                            break
                        chunks.append(self.rfile.read(size))
                        if self.rfile.read(2) != b'\r\n':
                            raise ValueError('Invalid chunk boundary')
                    body = b''.join(chunks)
                else:
                    self.send_error(411)
                    return
                if len(body) > 8 * 1024 * 1024:
                    self.send_error(413)
                    return
                ticket = owner.gate.admit()
                if ticket is None:
                    with owner.lock:owner.locally_denied_requests += 1
                    payload = b'{"error":{"type":"diagnostic_stopped","message":"Header diagnostic intake stopped; no upstream request sent"}}'
                    self.send_response(503)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                started = time.monotonic()
                entry = {'ticket': ticket, 'started_at': now(), 'started_monotonic': started,
                         'request_body_sha256': hashlib.sha256(body).hexdigest(),
                         'request_body_bytes': len(body), 'origin': 'upstream'}
                headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
                headers['Accept-Encoding'] = 'identity'
                # Auth values stay in memory only, including when validating an
                # unexpected error body before it is allowed onto disk.
                secrets = [v.encode() for k, v in headers.items()
                           if any(x in k.lower() for x in ('authorization', 'cookie', 'api-key'))]
                secrets += [v.split(b' ', 1)[1] for v in secrets if b' ' in v]
                with owner.lock:
                    owner._credential_values.update(secrets)
                def contains_secret(data):
                    return any(secret and secret in data for secret in secrets)
                def retain_error(data, kind):
                    if contains_secret(data):
                        entry['error_body_omitted_due_credential_match'] = True
                        return False
                    suffix=len(entry.get('error_bodies',[]))+1
                    path = owner.root / 'http' / f'{ticket:04d}-{kind}-{suffix}.body'
                    path.parent.mkdir(exist_ok=True)
                    with path.open('xb') as out:
                        out.write(data); out.flush(); os.fsync(out.fileno())
                    entry.setdefault('error_bodies', []).append({'path': path.name, 'sha256': hashlib.sha256(data).hexdigest()})
                    try:
                        data_json = json.loads(data.removeprefix(b'data:').strip())
                        error = data_json.get('error') or (data_json.get('response') or {}).get('error')
                        if isinstance(error, dict):
                            entry['error'] = {k: error[k] for k in ('type', 'code', 'message') if k in error}
                    except (ValueError, TypeError):
                        pass
                    return True
                try:
                    with owner.client.stream('POST', owner.upstream + '/responses', headers=headers, content=body) as response:
                        entry.update(status=response.status_code, headers_at=now(),
                                     header_latency_seconds=time.monotonic()-started,
                                     headers=safe_headers(response.headers,secrets),
                                     response_header_names=sorted(response.headers.keys()))
                        if response.status_code >= 300:
                            owner.gate.halt(f'First upstream HTTP {response.status_code}; no automatic replay')
                            data = response.read()
                            if not retain_error(data, 'http-error'):
                                data=b'{"error":{"type":"diagnostic_redaction","message":"Error body withheld because it echoed credentials"}}'
                            self.send_response(response.status_code)
                            for name, value in response.headers.items():
                                if name.lower() not in HOP | {'content-encoding', 'set-cookie', 'location'} and not contains_secret(value.encode()):
                                    self.send_header(name, value)
                            self.send_header('Content-Length', str(len(data)))
                            self.end_headers(); self.wfile.write(data); self.wfile.flush()
                        else:
                            self.send_response(response.status_code)
                            for name, value in response.headers.items():
                                if name.lower() not in HOP | {'content-encoding', 'set-cookie'} and not contains_secret(value.encode()):
                                    self.send_header(name, value)
                            self.send_header('Transfer-Encoding', 'chunked')
                            self.end_headers()
                            pending = b''
                            digest, size = hashlib.sha256(), 0
                            for chunk in response.iter_bytes():
                                digest.update(chunk); size += len(chunk)
                                if size > 8 * 1024 * 1024:
                                    raise ValueError('Response exceeds diagnostic bound')
                                pending += chunk
                                while b'\n' in pending:
                                    line, pending = pending.split(b'\n', 1)
                                    if line.startswith(b'data:'):
                                        try:
                                            event = json.loads(line[5:].strip())
                                            if event.get('type') in ('error', 'response.failed', 'response.incomplete'):
                                                owner.gate.halt('Upstream streaming error; preserve headers and stop new intake')
                                                retain_error(line, 'stream-error')
                                        except (ValueError, TypeError):
                                            pass
                                    if contains_secret(line):
                                        owner.gate.halt('Response echoed credentials; withheld before native logging')
                                        line=b'data: {"type":"error","error":{"message":"Diagnostic redaction"}}'
                                    payload=line+b'\n'
                                    self.wfile.write(f'{len(payload):x}\r\n'.encode()+payload+b'\r\n'); self.wfile.flush()
                            if pending:
                                if contains_secret(pending):
                                    raise ValueError('Unterminated response data contains a credential')
                                self.wfile.write(f'{len(pending):x}\r\n'.encode()+pending+b'\r\n')
                            self.wfile.write(b'0\r\n\r\n'); self.wfile.flush()
                            entry.update(decoded_response_bytes=size, decoded_response_sha256=digest.hexdigest())
                except Exception as error:
                    owner.gate.halt('Relay transport exception; completion is uncertain, no replay')
                    entry['relay_exception_type'] = type(error).__name__
                    self.close_connection = True
                finally:
                    entry.update(ended_at=now(), duration_seconds=time.monotonic()-started)
                    with owner.lock:
                        owner.records.append(entry)
                        with (owner.root / 'http-responses.jsonl').open('a') as out:
                            out.write(json.dumps(entry)+'\n'); out.flush(); os.fsync(out.fileno())

        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self):
        return f'http://127.0.0.1:{self.server.server_port}'

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown(); self.server.server_close(); self.thread.join(3); self.client.close()


def provider_config(url):
    return {'model_provider': 'header_diagnostic',
            'model_providers.header_diagnostic.name': 'OpenAI',
            'model_providers.header_diagnostic.base_url': url,
            'model_providers.header_diagnostic.requires_openai_auth': True,
            'model_providers.header_diagnostic.wire_api': 'responses',
            'model_providers.header_diagnostic.supports_websockets': False,
            'model_providers.header_diagnostic.request_max_retries': 0,
            'model_providers.header_diagnostic.stream_max_retries': 0}


def header_transport(binary, url):
    base = select_adapter('0.167.0', binary)
    class HeaderTransport(base):
        def _command(self, trial, system_path):
            command = super()._command(trial, system_path)
            for key, value in provider_config(url).items():
                command += ['-c', key+'='+json.dumps(value)]
            return command
    return HeaderTransport(timeout=110, catalog_path=BUNDLE/'model-catalog.json')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', required=True, type=Path)
    p.add_argument('--binary', required=True, type=Path)
    p.add_argument('--phase', choices=('canary', 'load'), required=True)
    args = p.parse_args()
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    logging.getLogger('httpx').setLevel(logging.ERROR)
    coordinator = GitCoordinator('https://github.com/dasnidm/llm-equivoque-experiments.git',
                                 'exp7/persistent-v1-coordination',root/'main-status.git')
    board = coordinator.status()
    if not board['global_stop'] or not Path('/workspace/work/exp7-cli-upgrade-20261108/HALT').is_file():
        raise RuntimeError('Previous scientific and technical STOPs must remain active')
    _, freeze = verify_freeze(BUNDLE/'freeze.json')
    bundle = load_bundle(BUNDLE)
    models = ['gpt-6-astra','gpt-5.6-sol']
    templates = [next(t for t in bundle['trials'] if t['model']==m and t['effort']=='medium'
                      and t['arm']=='en_schema' and t['frame']=='cards' and t['game']=='seq') for m in models]
    limit, pool, interval = (2,1,2.) if args.phase=='canary' else (144,8,.375)
    gate = Gate(root,interval,limit)
    launcher, database = isolated_sqlite_launcher(root,'native',args.binary.resolve())
    profile = {'run_id':'equivoque-2026-11-08-exp7-header-probe-v1-'+args.phase,
               'created_at':now(),'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'binary':str(args.binary.resolve()),'binary_sha256':hashlib.sha256(args.binary.read_bytes()).hexdigest(),
               'cli_version':'0.167.0','upstream':UPSTREAM,'transport':'HTTP/SSE via loopback relay; original study uses WS',
               'purpose':'User-authorized response header and error-body diagnosis, excluded from main samples',
               'old_STOPs_preserved':True,'main_freeze_sha256':freeze,
               'upstream_request_limit':limit,'pool':pool,'minimum_upstream_start_interval':interval,
               'request_max_retries':0,'stream_max_retries':0,'implicit_replacement':False,
               'auth':'Existing native CLI authentication; no auth file copied or extracted',
               'response_header_policy':'Allowlisted operational headers; no cookies, bearer credentials or balances',
               'request_logging':'SHA256 and byte count only; request headers and body never retained by relay'}
    atomic_json(root/'profile.json',profile)
    with Relay(root,gate) as relay, closing(header_transport(launcher,relay.base_url)) as transport:
        initialize_sqlite_without_inference(root,'serial-db')
        transport.before_send = lambda: (_ for _ in ()).throw(RuntimeError('Header diagnostic intake stopped; no replay')) if gate.stop.is_set() else None
        if args.phase=='canary':
            for i, template in enumerate(templates):
                if gate.stop.is_set():break
                trial={**template,'trial_id':f'header-canary-{i+1}','run_id':profile['run_id'],'cohort':'technical_headers'}
                protocol=MainProtocol()
                directory=root/'native'/trial['trial_id']
                prompt=protocol.prompt(trial,1,remaining=list(trial['order']))
                schema=protocol.schema(1,list(trial['order']),trial['frame'],trial)
                result=transport.request(trial,prompt,schema,protocol.system(trial),None,directory,1)
                atomic_json(root/f'canary-{i+1}.json',{k:v for k,v in result.items() if k not in ('events','stderr')})
                transport.close_trial(trial['trial_id'])
                if not result['ok']:gate.halt('Canary CLI failure; no further requests')
        else:
            budget=CallBudget(root/'budget.json',profile['run_id'],limit)
            trials=[{**templates[i%2],'trial_id':f'header-load-{i+1:02d}','run_id':profile['run_id'],
                     'cohort':'technical_headers'} for i in range(pool)]
            with ThreadPoolExecutor(max_workers=pool) as executor:
                futures=[executor.submit(run_trial,t,MainProtocol(),transport,root/'states'/(t['trial_id']+'.json'),
                                         root/'native',budget,freeze) for t in trials]
                for future in futures:
                    future.result()
        records=relay.records
    import shutil
    shutil.copytree(database,root/'native-sqlite')
    credential_matches=[]
    credential_skipped=[]
    for path in root.rglob('*'):
        if path.is_file() and path.stat().st_size<200_000_000:
            data=path.read_bytes()
            if any(value and value in data for value in relay._credential_values):
                credential_matches.append(path.relative_to(root).as_posix())
        elif path.is_file():credential_skipped.append(path.relative_to(root).as_posix())
    atomic_json(root/'credential-scan.json',{'matched_files':credential_matches,
                'skipped_files':credential_skipped,'scanned_values_kept_in_memory_only':True,
                'relay_policy':'No request headers/bodies logged; credential-bearing error bodies withheld'})
    atomic_json(root/'native-retry-audit.json',audit_native_retries(root))
    summary={'phase':args.phase,'ended_at':now(),'upstream_requests':len(records),
             'loopback_http_attempts':relay.received_requests,'locally_denied_requests':relay.locally_denied_requests,
             'credential_scan_clean':not credential_matches and not credential_skipped,
             'status_counts':{str(code):sum(r.get('status')==code for r in records) for code in sorted({r.get('status') for r in records if r.get('status') is not None})},
             'upstream_429':[r for r in records if r.get('status')==429],
             'stream_errors':[r for r in records if r.get('error_bodies') and r.get('status',0)<400],
             'stop_reason':gate.reason,'main_STOP_unchanged':coordinator.status()['global_stop'],
             'samples_in_main':0}
    atomic_json(root/'summary.json',summary)
    print(json.dumps(summary),flush=True)


if __name__=='__main__':
    main()
