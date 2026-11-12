"""Opt-in installed OpenCode API test. No provider or model inference."""
import os
from pathlib import Path
import tempfile
import unittest
import uuid

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
