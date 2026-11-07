"""Opt-in real Codex integration against a loopback-only fake model service.

Run with CODEX_TEST_BINARY=/path/to/frozen/codex python -m unittest
exp7_persistent.test_real_cli. No model service credentials or model calls are
used: the child gets an isolated home, a dummy API key, and a loopback base URL.
The fake service speaks both Responses SSE and WebSockets using the stdlib.
"""
from __future__ import annotations

import base64
import hashlib
import gzip
import http.server
import json
import os
from pathlib import Path
import subprocess
import struct
import tempfile
import threading
import unittest


class LocalResponses:
    """Capture actual Codex wire requests and return deterministic assistant text."""
    def __init__(self, *, schema_answers=False):
        self.schema_answers = schema_answers
        self.requests = []
        self.warmups = []
        self.websocket_connections = 0
        self._lock = threading.Lock()
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path != "/v1/responses" or self.headers.get("Upgrade", "").lower() != "websocket":
                    self.send_error(404)
                    return
                key = self.headers["Sec-WebSocket-Key"]
                accept = base64.b64encode(hashlib.sha1(
                    (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
                self.send_response(101)
                self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade")
                self.send_header("Sec-WebSocket-Accept", accept)
                self.end_headers()
                with owner._lock:
                    owner.websocket_connections += 1
                    connection_id = owner.websocket_connections
                self.connection.settimeout(15)
                try:
                    while True:
                        frame = self._receive_frame()
                        if frame is None:
                            return
                        opcode, data = frame
                        if opcode == 8:
                            self._send_frame(b"", 8)
                            return
                        if opcode == 9:
                            self._send_frame(data, 10)
                            continue
                        if opcode != 1:
                            raise ValueError("Unexpected mock WebSocket opcode")
                        body = json.loads(data)
                        for event in owner.events(body, "websocket", connection_id):
                            self._send_frame(json.dumps(event).encode())
                except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
                    return
                finally:
                    self.close_connection = True

            def _receive_frame(self):
                first = self.rfile.read(2)
                if len(first) != 2:
                    return None
                opcode = first[0] & 15
                if not first[0] & 128:
                    raise ValueError("Fragmented mock WebSocket messages are unsupported")
                masked = bool(first[1] & 128)
                length = first[1] & 127
                if length == 126:
                    length = struct.unpack("!H", self.rfile.read(2))[0]
                elif length == 127:
                    length = struct.unpack("!Q", self.rfile.read(8))[0]
                if length > 16 * 1024 * 1024:
                    raise ValueError("Unexpected large mock request")
                mask = self.rfile.read(4) if masked else None
                data = self.rfile.read(length)
                if len(data) != length:
                    return None
                if mask:
                    data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
                return opcode, data

            def _send_frame(self, data, opcode=1):
                prefix = bytes([128 | opcode])
                if len(data) < 126:
                    prefix += bytes([len(data)])
                elif len(data) < 65536:
                    prefix += bytes([126]) + struct.pack("!H", len(data))
                else:
                    prefix += bytes([127]) + struct.pack("!Q", len(data))
                self.wfile.write(prefix + data)
                self.wfile.flush()

            def do_POST(self):
                if self.path != "/v1/responses":
                    self.send_error(404)
                    return
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                events = owner.events(body, "https", None)
                payload = "".join("data: " + json.dumps(e) + "\n\n" for e in events).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                self.wfile.flush()

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def events(self, body, transport, connection_id):
        with self._lock:
            warmup = body.get("generate") is False
            number = len(self.requests) + 1
            entry = {"body": body, "transport": transport, "connection_id": connection_id}
            (self.warmups if warmup else self.requests).append(entry)
        response_id = f"resp_warmup_{number}" if warmup else f"resp_mock_{number}"
        text = f"ACK{number}"
        if self.schema_answers and not warmup:
            schema = body.get("text", {}).get("format", {}).get("schema")
            if not isinstance(schema, dict):
                raise ValueError("The scientific runner must submit a schema for this fixture")
            text = json.dumps(schema_example(schema))
        item = {"id": f"msg_mock_{number}", "type": "message", "role": "assistant",
                "status": "completed", "content": [{"type": "output_text", "text": text, "annotations": []}]}
        if warmup:
            return [{"type": "response.created", "response": {"id": response_id, "object": "response", "status": "in_progress", "output": []}},
                    {"type": "response.completed", "response": {"id": response_id, "object": "response", "status": "completed", "output": [],
                     "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                               "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}}}]
        return [
            {"type": "response.created", "response": {"id": response_id, "object": "response", "status": "in_progress", "output": []}},
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {"type": "response.completed", "response": {"id": response_id, "object": "response", "status": "completed", "output": [item],
                "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12,
                          "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}}},
        ]

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


def schema_example(schema):
    """Deterministic legal participant answers; no inference or scoring logic."""
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object":
        return {key: schema_example(schema["properties"][key]) for key in schema.get("required", [])}
    if kind == "array":
        count = schema.get("minItems", 0)
        item = schema["items"]
        # The choice prompt requires distinct members, including when the
        # provider schema omits its unsupported uniqueItems annotation.
        if "enum" in item:
            return item["enum"][:count]
        return [schema_example(item) for _ in range(count)]
    if kind in ("integer", "number"):
        return schema.get("minimum", 1)
    if kind == "boolean":
        return True
    if kind == "string":
        return "Synthetic offline explanation."
    raise ValueError("Unsupported synthetic schema: " + str(kind))


def make_cli_wrapper(directory, binary, base_url):
    """Apply fixture-only provider/home settings to the *child* process."""
    directory = Path(directory)
    native_home = directory / "native-home"
    native_home.mkdir()
    wrapper = directory / "codex-local-test"
    # The wrapper is an executable test fixture, not a production auth/home adapter.
    source = """#!/usr/bin/env python3
import os
import sys
import json
settings = %r
env = os.environ.copy()
env['CODEX_HOME'] = settings['home']
env['OPENAI_API_KEY'] = 'local-test-key-not-a-credential'
env['NO_PROXY'] = '127.0.0.1,localhost'
env['no_proxy'] = env['NO_PROXY']
env['RUST_LOG'] = 'error'
# Block accidental non-loopback HTTP(S), even if a future CLI ignores the URL override.
for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
    env[key] = 'http://127.0.0.1:1'
# Pin the built-in provider's API URL; no reserved provider override is needed.
args = [settings['binary']] + sys.argv[1:]
if 'app-server' in sys.argv or 'exec' in sys.argv:
    # Keep these in the subcommand's -c list; a second list can replace global overrides.
    args[2:2] = ['-c', 'openai_base_url=' + json.dumps(settings['url']),
                  '-c', 'analytics.enabled=false']
os.execve(settings['binary'], args, env)
""" % {"binary": str(Path(binary).absolute()), "home": str(native_home), "url": base_url}
    wrapper.write_text(source)
    wrapper.chmod(0o700)
    return wrapper


def prompt_texts(body):
    return [part.get("text", "") for item in body.get("input", [])
            if item.get("role") == "user" for part in item.get("content", [])
            if part.get("type") == "input_text"]


@unittest.skipUnless(os.environ.get("CODEX_TEST_BINARY"), "set CODEX_TEST_BINARY for offline real-CLI integration")
class RealCliIntegrationTests(unittest.TestCase):
    def test_full_conversation_reuses_process_and_preserves_isolation(self):
        from exp7_persistent.transport import PersistentTransport
        root = Path(__file__).resolve().parents[1]
        catalog = root / "preparation/current-runtime/post-login-model-catalog.json"
        self.assertTrue(catalog.is_file(), "offline static metadata fixture missing")
        binary = os.environ["CODEX_TEST_BINARY"]
        with tempfile.TemporaryDirectory(prefix="persistent-real-cli-") as temp, LocalResponses() as service:
            directory = Path(temp)
            wrapper = make_cli_wrapper(directory, binary, service.base_url)
            transport = PersistentTransport(timeout=30, codex_binary=str(wrapper), catalog_path=catalog)
            trial = {"trial_id": "offline-trial-a", "model": "gpt-6.1-sol", "effort": "low"}
            system = "Reply with the single acknowledgment provided by the test service."
            session_id = None
            pids = set()
            first_schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"], "additionalProperties": False}
            try:
                for turn in range(1, 35):
                    schema = first_schema if turn == 1 else None
                    result = transport.request(trial, f"TRIAL_A_TURN_{turn:02d}", schema, system, session_id, directory / "a", turn)
                    self.assertTrue(result["ok"], result)
                    if session_id:
                        self.assertEqual(result["session_id"], session_id)
                    session_id = result["session_id"]
                    pids.add(result["process_pid"])
                    self.assertEqual(result["text"], f"ACK{turn}")
                    self.assertEqual(result["usage"]["input_tokens"], 10 * turn)
                    self.assertEqual(result["tool_events"], 0)
                self.assertEqual(len(pids), 1, "a single trial must keep one real CLI process")
                self.assertEqual(len(service.requests), 34, "the client must not replay turns")
                self.assertEqual(service.websocket_connections, 1, "turns should reuse the live WS connection")
                for n, request in enumerate(service.requests, 1):
                    body = request["body"]
                    self.assertIn(f"TRIAL_A_TURN_{n:02d}", prompt_texts(body))
                    if n > 1:
                        has_history = "TRIAL_A_TURN_01" in prompt_texts(body)
                        self.assertTrue(has_history or body.get("previous_response_id"), "history or cached response linkage must survive")
                    self.assertEqual(body["model"], "gpt-6.1-sol")
                    instruction_text = body.get("instructions", "") + "\n".join(
                        part.get("text", "") for item in body.get("input", []) if item.get("role") == "developer"
                        for part in item.get("content", []))
                    # A linked WS delta need not resend the already cached instructions.
                    if not body.get("previous_response_id"):
                        self.assertIn(system, instruction_text)
                first_body = service.requests[0]["body"]
                self.assertEqual(first_body["text"]["format"]["schema"], first_schema)
                self.assertNotEqual(service.requests[1]["body"].get("text", {}).get("format", {}).get("type"), "json_schema")
                transport.close_trial(trial["trial_id"])
                other = {**trial, "trial_id": "offline-trial-b"}
                result = transport.request(other, "TRIAL_B_ONLY", None, system, None, directory / "b", 1)
                self.assertTrue(result["ok"], result)
                self.assertNotEqual(result["session_id"], session_id)
                self.assertNotIn(result["process_pid"], pids)
                self.assertNotIn("TRIAL_A_TURN_01", prompt_texts(service.requests[-1]["body"]))
                self.assertNotEqual(service.requests[-1]["body"].get("previous_response_id"), "resp_mock_34")
            finally:
                transport.close()


    def test_wire_instructions_and_tool_surface_match_frozen_exec(self):
        """Compare what the model sees, including the separate WS warmup payload."""
        from exp7_persistent.transport import PersistentTransport
        from exp7_pre.transport import command_for, subject_directory
        root = Path(__file__).resolve().parents[1]
        catalog = root / "preparation/current-runtime/post-login-model-catalog.json"
        with tempfile.TemporaryDirectory(prefix="persistent-parity-") as temp, LocalResponses() as service:
            directory = Path(temp)
            wrapper = make_cli_wrapper(directory, os.environ["CODEX_TEST_BINARY"], service.base_url)
            transport = PersistentTransport(timeout=30, codex_binary=str(wrapper), catalog_path=catalog)
            trial = {"trial_id": "offline-parity", "model": "gpt-6.1-sol", "effort": "low"}
            system, prompt = "Exact offline comparison instruction.", "Exact offline comparison question."
            raw = directory / "raw"
            try:
                result = transport.request(trial, prompt, None, system, None, raw, 1)
                self.assertTrue(result["ok"], result)
            finally:
                transport.close()
            persistent = service.requests[-1]["body"]
            persistent_warmup = service.warmups[-1]["body"] if service.warmups else {}
            subject = subject_directory(raw.resolve())
            command = command_for(trial, raw / "subject-system.txt", subject, None, None)
            command[0] = str(wrapper)
            command[-1:-1] = ["-c", "model_catalog_json=" + json.dumps(str(catalog))]
            baseline = subprocess.run(command, input=prompt, text=True, capture_output=True,
                                      timeout=30, cwd=subject)
            self.assertEqual(baseline.returncode, 0, baseline.stderr)
            events = [json.loads(line) for line in baseline.stdout.splitlines()]
            self.assertEqual(sum(e.get("type") == "turn.completed" for e in events), 1)
            native = service.requests[-1]["body"]
            native_warmup = service.warmups[-1]["body"] if service.warmups else {}

            def visible(body):
                return {"instructions": body.get("instructions"), "tools": body.get("tools"),
                        "input": [{k: item.get(k) for k in ("type", "role", "content", "tools")}
                                  for item in body.get("input", [])]}

            # IDs/timestamps are transport metadata. Text, role ordering and tool
            # definitions must match exactly, including content cached in prewarm.
            self.assertEqual(visible(persistent_warmup), visible(native_warmup))
            self.assertEqual(visible(persistent), visible(native))
            self.assertEqual(persistent["model"], native["model"])
            self.assertEqual(persistent.get("reasoning"), native.get("reasoning"))
            self.assertEqual(persistent.get("text"), native.get("text"))


    def test_full_scientific_runner_audit_archive_and_private_backup_contract(self):
        from exp7_main.protocol import MainProtocol
        from exp7_main.test_protocol import example
        from exp7_main_v2.runner import run_trial, CallBudget, atomic_json
        from exp7_main_v2.worker import public_state, ResultPublisher
        from exp7_main_v2.storage import _collect, archive_completed_job, verify_archive
        from exp7_backup_v1.sidecar import backup_job
        from exp7_persistent.transport import PersistentTransport
        from exp7_persistent.audit import audit_trial

        root = Path(__file__).resolve().parents[1]
        catalog = root / "preparation/current-runtime/post-login-model-catalog.json"
        with tempfile.TemporaryDirectory(prefix="persistent-scientific-") as temp, LocalResponses(schema_answers=True) as service:
            work = Path(temp)
            wrapper = make_cli_wrapper(work, os.environ["CODEX_TEST_BINARY"], service.base_url)
            transport = PersistentTransport(timeout=30, codex_binary=str(wrapper), catalog_path=catalog)
            trial = example(model="gpt-6.1-sol", trial_id="scientific-trial-001")
            job_id, freeze = "job-001", "a" * 64
            job = work / "jobs" / job_id
            job.mkdir(parents=True)
            state_path = job / "states" / (trial["trial_id"] + ".json")
            protocol = MainProtocol()
            budget = CallBudget(job / "budget.json", trial["run_id"], 34)
            try:
                state = run_trial(trial, protocol, transport, state_path, job / "native", budget, freeze)
            finally:
                transport.close()
            self.assertEqual(state["status"], "complete", state.get("error"))
            self.assertEqual(len(state["turns"]), 34)
            self.assertEqual(len(service.requests), 34)
            self.assertEqual(len({turn["process_pid"] for turn in state["turns"]}), 1)
            final_names = {Path(ref["path"]).name for ref in state["turns"][-1]["raw_files"]}
            self.assertIn("process.stderr.log", final_names)
            self.assertIn("close-diagnostics.json", final_names)
            report = audit_trial(trial, protocol, state_path, freeze)
            self.assertTrue(report["integrity_ok"], report)
            entries, statuses = _collect(job, [trial["trial_id"]])
            self.assertEqual(statuses, {"complete": 1, "failed": 0})
            self.assertTrue(any(path.endswith("process.stderr.log") for path in entries))

            identity = {"run_id": trial["run_id"], "model": trial["model"],
                        "owner": "offline-test-vm", "model_token": "offline-model-token"}
            claim = {"job_id": job_id, "model": trial["model"], "owner": identity["owner"],
                     "model_token": identity["model_token"], "claim_token": "offline-claim-token",
                     "trial_ids": [trial["trial_id"]]}
            atomic_json(work / "identity.private.json", identity)
            atomic_json(work / "calibration/attempt-01/readiness.json", {
                "passed": True, "model": trial["model"], "worker_owner": identity["owner"], "freeze_sha256": freeze})
            atomic_json(job / "claim.private.json", claim)
            public = gzip.compress((json.dumps(public_state(state)) + "\n").encode(), mtime=0)
            (job / "public.jsonl.gz").write_bytes(public)
            completion = {**claim, "status": "complete", "counts": {"complete": 1, "failed": 0, "interrupted": 0, "unstarted": 0},
                          "result_ref": "offline-commit:results/job-001.jsonl.gz", "result_sha256": hashlib.sha256(public).hexdigest()}
            archived = archive_completed_job(job, work / "archives", completion=completion,
                                             expected_trial_ids=claim["trial_ids"], prune=False)
            self.assertTrue(archived["verified"])
            index = verify_archive(archived["archive"], archived["manifest"])
            self.assertEqual(set(index["files"]), set(entries))
            remote = work / "private-fixture.git"
            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
            state_dir = work / "backup-v1"
            state_dir.mkdir()
            repo = {"id": 123, "full_name": "fixture/private", "private": True, "visibility": "private",
                    "archived": False, "disabled": False, "permissions": {"push": True}}
            publisher = ResultPublisher(str(remote), "raw/offline/scientific", state_dir / "publication.git")
            backup = backup_job(work, identity, job_id, repo, publisher, state_dir, lambda: dict(repo))
            self.assertEqual(backup["status"], "verified")
            self.assertTrue(Path(archived["archive"]).exists(), "backup must retain the source archive")


if __name__ == "__main__":
    unittest.main()
