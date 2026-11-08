"""Offline security and no-retry checks for the response-header relay."""
import http.server
import json
from pathlib import Path
import tempfile
import threading
import unittest

import httpx

from exp7_header_probe import Gate, Relay, header_transport
from exp7_persistent.test_real_cli import LocalResponses, make_cli_wrapper

BINARY=Path('/workspace/work/exp7-cli-upgrade-20261108/cli-0.167.0/codex')


class HeaderProbeTests(unittest.TestCase):
    def test_response_headers_and_body_capture_without_request_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            secret='offline-credential-for-leak-detection-09241'
            class Handler(http.server.BaseHTTPRequestHandler):
                def log_message(self,*args):pass
                def do_POST(self):
                    self.rfile.read(int(self.headers['Content-Length']))
                    body=b'{"error":{"type":"rate_limit_error","code":"turn_rate_limit_exceeded","message":"Synthetic capacity"}}'
                    self.send_response(429)
                    self.send_header('Retry-After','20')
                    self.send_header('X-Request-ID','synthetic-request-id')
                    self.send_header('Set-Cookie','never-persist-this-cookie')
                    self.send_header('Content-Length',str(len(body)))
                    self.end_headers();self.wfile.write(body)
            server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                gate=Gate(root,0,2)
                with Relay(root,gate,f'http://127.0.0.1:{server.server_port}',offline=True) as relay:
                    r=httpx.post(relay.base_url+'/responses',content=b'{}',headers={'Authorization':'Bearer '+secret})
                    self.assertEqual(r.status_code,429)
                self.assertTrue(gate.stop.is_set())
                record=relay.records[0]
                self.assertEqual(record['headers']['retry-after'],'20')
                self.assertEqual(record['error']['code'],'turn_rate_limit_exceeded')
                self.assertNotIn('set-cookie',record['headers'])
                for path in root.rglob('*'):
                    if path.is_file():self.assertNotIn(secret.encode(),path.read_bytes())
            finally:server.shutdown();server.server_close();thread.join(2)

    def test_real_cli_has_exactly_one_http_attempt_on_429(self):
        with tempfile.TemporaryDirectory() as temporary,LocalResponses() as service:
            root=Path(temporary)
            count=[]
            class Limited(service.server.RequestHandlerClass):
                def do_POST(self):
                    self.rfile.read(int(self.headers['Content-Length']))
                    count.append(1)
                    body=b'{"error":{"type":"rate_limit_error","code":"turn_rate_limit_exceeded","message":"Synthetic capacity"}}'
                    self.send_response(429);self.send_header('Retry-After','20')
                    self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)))
                    self.end_headers();self.wfile.write(body);self.wfile.flush()
            service.server.RequestHandlerClass=Limited
            with Relay(root,Gate(root,0,10),service.base_url,offline=True) as relay:
                home=root/'fixture';home.mkdir()
                wrapper=make_cli_wrapper(home,BINARY,relay.base_url)
                transport=header_transport(wrapper,relay.base_url)
                try:
                    result=transport.request({'trial_id':'header-offline','model':'gpt-6.1-sol','effort':'medium'},
                                             'Reply exactly OK.',None,'Synthetic diagnostic.',None,root/'native',1)
                    self.assertFalse(result['ok'])
                finally:transport.close()
            self.assertEqual(len(count),1)
            self.assertEqual(len(relay.records),1)
            self.assertEqual(relay.received_requests,1)
            self.assertEqual(relay.records[0]['status'],429)
            for path in (root/'native').rglob('*'):
                if path.is_file():self.assertNotIn(b'local-test-key-not-a-credential',path.read_bytes())

    def test_real_cli_success_sse_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary,LocalResponses() as service:
            root=Path(temporary)
            with Relay(root,Gate(root,0,2),service.base_url,offline=True) as relay:
                home=root/'fixture';home.mkdir()
                wrapper=make_cli_wrapper(home,BINARY,relay.base_url)
                transport=header_transport(wrapper,relay.base_url)
                try:
                    result=transport.request({'trial_id':'header-success','model':'gpt-6.1-sol','effort':'medium'},
                                             'Reply exactly OK.',None,'Synthetic diagnostic.',None,root/'native',1)
                    self.assertTrue(result['ok'],result.get('protocol_violations'))
                    self.assertEqual(result['text'],'ACK1')
                finally:transport.close()
            self.assertEqual(relay.received_requests,1)

    def test_reflected_credentials_are_not_recorded_or_forwarded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            secret='offline-reflected-credential-842070'
            class Handler(http.server.BaseHTTPRequestHandler):
                def log_message(self,*args):pass
                def do_POST(self):
                    self.rfile.read(int(self.headers['Content-Length']))
                    auth=self.headers['Authorization']
                    body=json.dumps({'error':{'message':auth}}).encode()
                    self.send_response(429)
                    self.send_header('X-RateLimit-Limit-Requests',auth)
                    self.send_header('Content-Length',str(len(body)))
                    self.end_headers();self.wfile.write(body)
            server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with Relay(root,Gate(root,0,2),f'http://127.0.0.1:{server.server_port}',offline=True) as relay:
                    response=httpx.post(relay.base_url+'/responses',content=b'{}',headers={'Authorization':'Bearer '+secret})
                    self.assertNotIn(secret,response.text)
                    self.assertNotIn(secret,str(response.headers))
                self.assertTrue(relay.records[0]['error_body_omitted_due_credential_match'])
                for p in root.rglob('*'):
                    if p.is_file():self.assertNotIn(secret.encode(),p.read_bytes())
            finally:server.shutdown();server.server_close();thread.join(2)


if __name__=='__main__':unittest.main()
