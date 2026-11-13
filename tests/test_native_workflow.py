"""Opt-in installed CLI checks with a loopback provider; no research or inference.

Copies the existing project agent into an isolated project. Fixtures exercise
native execution and persistence without interpreting scientific completion.
"""
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@unittest.skipUnless(os.environ.get('OC_NATIVE_BIN'), 'set OC_NATIVE_BIN to the installed OpenCode')
class NativeWorkflow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='native-opencode-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        self.requests = []
        self.blocked = threading.Event()
        self.release = threading.Event()
        self.addCleanup(self.release.set)
        case = self

        class Provider(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                messages = body['messages']
                title = 'You are a title generator' in json.dumps(messages[:1])
                if not title:
                    case.requests.append(body)
                text = json.dumps(messages)
                if '[oom]' in text:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': {'message': 'fixture provider out of memory',
                        'type': 'insufficient_memory', 'code': 'insufficient_memory'}}).encode())
                    return
                tool_done = any(m.get('role') == 'tool' for m in messages)
                delta = {'role': 'assistant', 'content': 'Useful partial output; no completion contract.'}
                finish = 'stop'
                if title:
                    delta['content'] = 'Native fixture'
                elif '[empty]' in text:
                    delta['content'] = ''
                elif '[resume]' in text:
                    delta['content'] = 'Resumed the same native session.'
                elif not tool_done:
                    command = "printf 'fixture stdout'; printf 'fixture stderr' >&2; exit 7"
                    if '[interrupt]' in text:
                        command = "printf 'preserved before interruption' > interrupted.txt"
                    elif '[detached]' in text:
                        child = "import time; from pathlib import Path; time.sleep(1); Path('detached.txt').write_text('finished')"
                        launch = ('import subprocess,sys; p=subprocess.Popen([sys.executable,"-c",'
                                  + repr(child) + '],start_new_session=True,stdin=subprocess.DEVNULL,'
                                  'stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); print(p.pid)')
                        command = shlex.join([sys.executable, '-c', launch])
                    delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'call_native',
                        'type': 'function', 'function': {'name': 'shell',
                        'arguments': json.dumps({'command': command})}}]}
                    finish = 'tool_calls'
                elif '[interrupt]' in text:
                    case.blocked.set()
                    case.release.wait(15)
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                try:
                    for value, reason in [(delta, None), ({}, finish)]:
                        chunk = {'id': 'native-fixture', 'object': 'chat.completion.chunk',
                                 'created': 1, 'model': 'mock', 'choices': [
                                     {'index': 0, 'delta': value, 'finish_reason': reason}]}
                        self.wfile.write(('data: ' + json.dumps(chunk) + '\n\n').encode())
                    self.wfile.write(b'data: [DONE]\n\n')
                except (BrokenPipeError, ConnectionResetError):
                    pass

        provider = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        threading.Thread(target=provider.serve_forever, daemon=True).start()
        self.addCleanup(provider.server_close)
        self.addCleanup(provider.shutdown)
        self.config = self.project / 'opencode.jsonc'
        self.config.write_text(json.dumps({'model': 'fixture/mock', 'small_model': 'fixture/mock',
            'default_agent': 'sage-research', 'permission': {'*': 'allow'},
            'provider': {'fixture': {'npm': '@ai-sdk/openai-compatible', 'options': {
                'baseURL': f'http://127.0.0.1:{provider.server_port}/v1', 'apiKey': 'fixture'},
                'models': {'mock': {'name': 'mock', 'limit': {'context': 32768, 'output': 4096}}}}}}))
        agent = Path(os.environ['OC_NATIVE_AGENT'])
        self.agent_text = agent.read_text()
        agents = self.project / '.opencode' / 'agents'
        agents.mkdir(parents=True)
        (agents / 'sage-research.md').write_text(self.agent_text)
        self.env = {**os.environ, 'OPENCODE_CONFIG': str(self.config),
                    'PWD': str(self.project),
                    'XDG_CONFIG_HOME': str(self.root / 'config'),
                    'XDG_DATA_HOME': str(self.root / 'data'),
                    'XDG_STATE_HOME': str(self.root / 'state'),
                    'XDG_CACHE_HOME': str(self.root / 'cache'), 'NO_COLOR': '1'}

    def cli(self, args):
        return subprocess.run([os.environ['OC_NATIVE_BIN'], *args], cwd=self.project,
                              env=self.env, capture_output=True, text=True, timeout=20)

    def run_args(self, prompt, session=None):
        args = ['run', '--standalone', '--format', 'json', '--print-logs',
                '--title', 'Native workflow fixture']
        if session:
            args += ['--session', session]
        return args + [prompt]

    def test_tool_failure_partial_answer_and_resume(self):
        first = self.cli(self.run_args('[normal]'))
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn('fixture stdout', first.stdout)
        self.assertIn('fixture stderr', first.stdout)
        self.assertIn('Useful partial output', first.stdout)
        self.assertTrue(first.stderr, 'native diagnostic stderr captured')
        events = [json.loads(line) for line in first.stdout.splitlines()]
        session = events[0]['sessionID']
        tools = [e for e in events if e['type'] == 'tool_use']
        metadata = [e['part']['state'].get('metadata', {}) for e in tools]
        self.assertTrue(any(m.get('exit', m.get('metadata', {}).get('exit')) == 7 for m in metadata))
        self.assertEqual(len(self.requests), 2, 'no handoff repair request')
        self.assertIn('Maximise scientific information gained', json.dumps(self.requests[0]))
        shell = next(t['function'] for t in self.requests[0]['tools'] if t['function']['name'] == 'shell')
        self.assertIn('background', shell['parameters']['properties'])
        self.assertIn('timeout', shell['parameters']['properties'])
        resumed = self.cli(self.run_args('[resume]', session))
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertIn('Resumed the same native session', resumed.stdout)
        self.assertEqual({json.loads(l)['sessionID'] for l in resumed.stdout.splitlines()}, {session})
        exported = self.cli(['session', 'export', '--standalone', session])
        self.assertEqual(exported.returncode, 0, exported.stderr)
        self.assertIn('fixture stderr', exported.stdout)
        self.assertIn('sage-research', exported.stdout)
        print('native: tool exit 7, partial answer, same-session resume and export; CLI exits 0')

    def test_empty_final_answer(self):
        result = self.cli(self.run_args('[empty]'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.requests), 1, 'no repair inference for an empty answer')
        print('native: empty final answer; CLI exit 0, no completion judgement')

    def test_provider_error_is_transparent(self):
        result = self.cli(self.run_args('[oom]'))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('fixture provider out of memory', result.stdout + result.stderr)
        self.assertEqual(len(self.requests), 1)
        print('native: terminal provider error; CLI exit 1, no external retry')

    def test_interrupt_preserves_tool_output(self):
        out, err = self.root / 'stdout.jsonl', self.root / 'stderr.log'
        with out.open('wb') as stdout, err.open('wb') as stderr:
            proc = subprocess.Popen([os.environ['OC_NATIVE_BIN'], *self.run_args('[interrupt]')],
                                    cwd=self.project, env=self.env, stdout=stdout, stderr=stderr)
            try:
                self.assertTrue(self.blocked.wait(10), 'second provider request reached')
                proc.send_signal(signal.SIGINT)
                code = proc.wait(timeout=10)
            finally:
                self.release.set()
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=5)
        self.assertEqual((self.project / 'interrupted.txt').read_text(), 'preserved before interruption')
        self.assertIn('tool_use', out.read_text())
        self.assertNotEqual(code, 0)
        print(f'native: SIGINT exit {code}; completed tool file and raw events preserved')

    def test_detached_job_survives_native_exit(self):
        result = self.cli(self.run_args('[detached]'))
        exited = time.time_ns()
        self.assertEqual(result.returncode, 0, result.stderr)
        until = time.monotonic() + 5
        marker = self.project / 'detached.txt'
        while not marker.exists() and time.monotonic() < until:
            time.sleep(.05)
        self.assertEqual(marker.read_text(), 'finished')
        self.assertGreater(marker.stat().st_mtime_ns, exited, 'job completes after CLI exit')
        print('native: short detached fixture finished after launch; no controller cleanup')


if __name__ == '__main__':
    unittest.main()
