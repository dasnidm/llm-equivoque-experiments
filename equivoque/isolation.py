"""Offline inspection of native CLI request bodies without provider credentials.

An unauthenticated loopback endpoint rejects each request before inference.
Only JSON bodies are captured; authorization headers are never inspected/stored.
This is a configuration diagnostic, not a replacement evaluation transport.
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import threading

from .core import write_json
from .transport import overrides


def inspect_request(protocol, configuration, directory, catalog_path):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    subject = directory / 'subject'
    subject.mkdir()
    system = directory / 'system.txt'
    system.write_text(protocol.data['system'])
    schema = directory / 'schema.json'
    schema.write_text(json.dumps({'type': 'object', 'additionalProperties': False,
        'required': ['ready'], 'properties': {'ready': {'type': 'boolean'}}}))
    bodies = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            bodies.append(body)
            self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"Intentional offline inspection; no inference"}}')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    options = overrides(system, configuration['effort'])
    local = {
        'model_provider': 'inspection',
        'model_providers.inspection.name': 'Unauthenticated offline inspection',
        'model_providers.inspection.base_url': f'http://127.0.0.1:{server.server_port}/v1',
        'model_providers.inspection.wire_api': 'responses',
        'model_providers.inspection.requires_openai_auth': False,
        'model_catalog_json': str(Path(catalog_path).resolve()),
    }
    for key, value in local.items():
        options.extend(['-c', key + '=' + json.dumps(value)])
    prompt = 'Reply with the JSON object {"ready":true}.'
    command = ['codex', 'exec', '--ignore-user-config', '--ignore-rules',
        '--skip-git-repo-check', '--json', '--model', configuration['model'],
        '--output-schema', str(schema.resolve()), '--sandbox', 'read-only',
        '-C', str(subject.resolve()), *options, prompt]
    try:
        result = subprocess.run(command, cwd=subject, capture_output=True, text=True, timeout=30)
    finally:
        server.shutdown()
        server.server_close()
    (directory / 'events.jsonl').write_text(result.stdout)
    (directory / 'stderr.txt').write_text(result.stderr)
    write_json(directory / 'requests.json', bodies)
    passed = len(bodies) == 1
    errors = []
    if not passed:
        errors.append('Expected exactly one offline inspection request')
    for body in bodies:
        if body.get('tools'):
            errors.append('Native request offers subject tools')
        texts = [b.get('text', '') for i in body.get('input', [])
                 for b in i.get('content', []) if b.get('text')]
        if texts != [protocol.data['system'], next(
                (t for t in texts if t.startswith('<environment_context>')), ''), prompt]:
            errors.append('Native request includes unexpected subject instructions/context')
        if body.get('model') != configuration['model'] or (
                body.get('reasoning', {}).get('effort') != configuration['effort']):
            errors.append('Native request changes model or effort')
        if body.get('text', {}).get('format', {}).get('type') != 'json_schema':
            errors.append('Native request lacks the required output schema')
    report = {'passed': passed and not errors, 'errors': errors,
        'configuration': configuration, 'offline_cli_invocations': 1,
        'live_subject_invocations': 0, 'tool_counts': [len(b.get('tools', [])) for b in bodies],
        'note': 'Loopback inspection uses no credentials and performs no model inference. Evaluation retains the original ChatGPT native-session route.'}
    write_json(directory / 'inspection.json', report)
    return report
