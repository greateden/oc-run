"""Opt-in installed OpenCode tests with local fixtures; no live-model inference."""
import os
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import time
import unittest
import uuid
from unittest import mock

from test_oc_run import oc


@unittest.skipUnless(os.environ.get('OC_RUN_NATIVE_BIN'), 'set OC_RUN_NATIVE_BIN for the installed CLI API test')
class NativeTests(unittest.TestCase):
    def test_durable_steering_inbox_survives_private_server_restart(self):
        binary = os.environ['OC_RUN_NATIVE_BIN']
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            session, message = None, 'msg_' + uuid.uuid4().hex
            for attempt in range(2):
                log_path = project / f'server-{attempt}.log'
                with log_path.open('xb', buffering=0) as log:
                    with oc.guarded([binary, 'serve', '--hostname', '127.0.0.1', '--port', '0'], log) as proc:
                        api = oc.NativeServer()
                        api.connect(log_path, proc, lambda: None)
                        if attempt == 0:
                            session = api.request('session', {'title': 'OC Run inbox test',
                                'location': {'directory': str(project)}})['data']['id']
                            api.request(f'session/{session}/prompt', {'id': message,
                                'text': 'STOP: final handoff only.', 'delivery': 'steer', 'resume': False})
                            # Native admission is idempotent for a caller-supplied ID.
                            api.request(f'session/{session}/prompt', {'id': message,
                                'text': 'STOP: final handoff only.', 'delivery': 'steer', 'resume': False})
                            self.assertFalse(api.request(f'session/{session}/interrupt?resume=false', {})['interrupted'])
                        self.assertEqual(api.request(f'session/{session}')['data']['id'], session)
                        pending = api.request(f'session/{session}/inbox')['data']
                        self.assertTrue(any(x['id'] == message and x['delivery'] == 'steer' for x in pending))
                        self.assertEqual(sum(x['id'] == message for x in pending), 1)
                        if attempt == 1:
                            api.request(f'session/{session}/inbox/{message}', method='DELETE')
                            pending = api.request(f'session/{session}/inbox')['data']
                            self.assertFalse(any(x['id'] == message for x in pending))
                            api.request(f'session/{session}', method='DELETE')

    def test_cli_omits_linked_child_session_events(self):
        """Installed CLI + local protocol fixture, not live-model inference."""
        entered, release = threading.Event(), threading.Event()
        class Provider(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                entered.set()
                release.wait(10)
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                chunks = [{'role': 'assistant', 'content': 'parent-only-marker'}, {}]
                for i, delta in enumerate(chunks):
                    data = {'id': 'fixture', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'mock',
                            'choices': [{'index': 0, 'delta': delta, 'finish_reason': 'stop' if i else None}]}
                    self.wfile.write(('data: ' + json.dumps(data) + '\n\n').encode())
                self.wfile.write(b'data: [DONE]\n\n')
        provider = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        thread = threading.Thread(target=provider.serve_forever, daemon=True); thread.start()
        self.addCleanup(provider.server_close)
        self.addCleanup(provider.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            config = run / 'opencode.json'
            config.write_text(json.dumps({'model': 'fixture/mock', 'small_model': 'fixture/mock',
                'provider': {'fixture': {'npm': '@ai-sdk/openai-compatible',
                    'options': {'baseURL': f'http://127.0.0.1:{provider.server_port}/v1', 'apiKey': 'fixture'},
                    'models': {'mock': {'name': 'mock', 'limit': {'context': 32768, 'output': 4096}}}}},
                'permission': {'*': 'allow'}}))
            env = {'OPENCODE_CONFIG': str(config), 'XDG_CONFIG_HOME': str(run / 'config'),
                   'XDG_DATA_HOME': str(run / 'data'), 'XDG_CACHE_HOME': str(run / 'cache')}
            with mock.patch.dict(os.environ, env):
                log_path = run / 'server.log'
                with log_path.open('xb', buffering=0) as log:
                    binary = os.environ['OC_RUN_NATIVE_BIN']
                    with oc.guarded([binary, 'serve', '--hostname', '127.0.0.1', '--port', '0'], log) as proc:
                        api = oc.NativeServer(); api.connect(log_path, proc, lambda: None)
                        parent = api.request('session', {'title': 'parent fixture',
                            'location': {'directory': tmp}})['data']['id']
                        child = api.request('session', {'title': 'child fixture', 'parentID': parent})['data']['id']
                        started, sent = time.monotonic(), False
                        def tick():
                            nonlocal sent
                            if entered.is_set() and not sent:
                                sent = True
                                api.request(f'session/{child}/shell', {'command': 'printf child-only-marker; exit 7'})
                                release.set()
                            if time.monotonic() - started > 15:
                                release.set()
                                raise ValueError('native fixture timed out')
                        rc = oc.invoke(binary, 'Reply parent-only-marker.', run, 'parent', parent, tick, server=api)
                        self.assertEqual(rc, 0, (run / 'parent.jsonl').read_text())
                        self.assertTrue(sent)
                        transcript = json.dumps(api.request(f'session/{child}/message'))
                        self.assertIn('child-only-marker', transcript)
                        self.assertIn('"exit": 7', transcript)
                        raw = (run / 'parent.jsonl').read_text()
                        self.assertIn('parent-only-marker', raw)
                        self.assertNotIn('child-only-marker', raw)
                        api.request(f'session/{parent}', method='DELETE')
