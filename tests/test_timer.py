"""Budget behaviour with a deterministic CLI fixture; no model or research work."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


WRAPPER = Path(__file__).resolve().parents[1] / "oc-run"
loader = importlib.machinery.SourceFileLoader("timer", str(WRAPPER))
spec = importlib.util.spec_from_loader(loader.name, loader)
timer = importlib.util.module_from_spec(spec)
loader.exec_module(timer)

FAKE = '''#!/usr/bin/env python3
import json, os, pathlib, signal, sys, time
root = pathlib.Path(os.environ['FIXTURE_ROOT'])
calls = root / 'calls.jsonl'
n = len(calls.read_text().splitlines()) if calls.exists() else 0
sid = sys.argv[sys.argv.index('--session') + 1]
with calls.open('a') as f: f.write(json.dumps(sys.argv[1:] + [sys.stdin.read()]) + '\\n')
print(json.dumps({'type': 'step_start', 'sessionID': sid}), flush=True)
mode = os.environ.get('FIXTURE_MODE', '')
if mode == 'interrupt':
    def stop(*_):
        print('interrupted natively', file=sys.stderr, flush=True)
        sys.exit(130)
    signal.signal(signal.SIGINT, stop)
    (root / 'work.txt').write_text('preserved')
    (root / 'ready').touch()
    time.sleep(30)
time.sleep(float(os.environ.get('FIXTURE_DELAY', '.06')))
if mode == 'ambiguous': sys.exit(7)
if mode == 'error':
    print(json.dumps({'type': 'error', 'sessionID': sid, 'error': 'OOM'}))
    sys.exit(0)
if mode == 'different' and n:
    print(json.dumps({'type': 'text', 'sessionID': 'ses_wrong'}))
if mode == 'text':
    print(json.dumps({'type': 'text', 'sessionID': sid, 'part': {'text': 'A thoughtful text-only result.'}}))
if mode != 'text':
    print(json.dumps({'type': 'tool_use', 'sessionID': sid,
                     'part': {'state': {'status': 'error', 'error': 'tool failed'}}}))
print(json.dumps({'type': 'step_finish', 'sessionID': sid}))
'''


class Timer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.binary = self.root / "opencode"
        self.binary.write_text(FAKE)
        self.binary.chmod(0o755)
        self.env = {**os.environ, "PATH": str(self.root) + os.pathsep + os.environ['PATH'],
                    "XDG_STATE_HOME": str(self.root / 'state'), "FIXTURE_ROOT": str(self.root)}

    def invoke(self, budget="0.25s", prompt="Original task", **env):
        return subprocess.run([sys.executable, str(WRAPPER), budget, prompt],
                              env={**self.env, **env}, capture_output=True, text=True, timeout=15)

    def calls(self):
        return [json.loads(line) for line in (self.root / 'calls.jsonl').read_text().splitlines()]

    def logs(self):
        return next((self.root / 'state' / 'oc-run').iterdir())

    def test_duration_validation(self):
        for value, expected in [('15m', 900), ('2h', 7200), ('10h', 36000), ('0.1s', .1)]:
            self.assertEqual(timer.duration(value), expected)
        for value in ['0h', '-1h', 'NaN', 'infh', '10', '9' * 1000 + 'h']:
            with self.assertRaises(Exception):
                timer.duration(value)

    def test_multiple_same_session_turns_and_prompt_preservation(self):
        result = self.invoke('0.4s', '- exact original\nwith Unicode: ü $`')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.calls()
        self.assertGreaterEqual(len(calls), 2)
        sid = calls[0][calls[0].index('--session') + 1]
        self.assertEqual(calls[0][-1], '- exact original\nwith Unicode: ü $`')
        self.assertEqual((self.logs() / 'prompt.txt').read_text(), calls[0][-1])
        for call in calls[1:]:
            self.assertEqual(call[call.index('--session') + 1], sid)
            self.assertEqual(call[-1], timer.CONTINUATION)
        self.assertIn('Budget elapsed', result.stdout)

    def test_deadline_allows_slow_turn_to_finish(self):
        start = time.monotonic()
        result = self.invoke('0.05s', FIXTURE_DELAY='0.3')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertGreater(time.monotonic() - start, .3)
        self.assertEqual(len(self.calls()), 1)
        self.assertIn('step_finish', (self.logs() / '0001.stdout.jsonl').read_text())

    def test_terminal_errors_and_ambiguous_exit_are_not_retried(self):
        for mode in ['error', 'ambiguous']:
            with self.subTest(mode=mode):
                (self.root / 'calls.jsonl').unlink(missing_ok=True)
                result = self.invoke('1s', FIXTURE_MODE=mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(len(self.calls()), 1)
                self.assertIn('failure', result.stdout)

    def test_changed_session_stops(self):
        result = self.invoke('1s', FIXTURE_MODE='different')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(self.calls()), 2)
        self.assertIn('continuity is unconfirmed', result.stdout)

    def test_three_rapid_empty_turns_stop(self):
        result = self.invoke('10s', FIXTURE_MODE='text')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(self.calls()), 3)
        self.assertIn('three consecutive', result.stdout)

    def test_slow_text_only_turns_are_allowed(self):
        result = self.invoke('6.5s', FIXTURE_MODE='text', FIXTURE_DELAY='2.05')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertGreaterEqual(len(self.calls()), 3)
        self.assertNotIn('three consecutive', result.stdout)

    def test_ctrl_c_preserves_logs_and_work(self):
        proc = subprocess.Popen([sys.executable, str(WRAPPER), '10s', 'Original task'],
                                env={**self.env, 'FIXTURE_MODE': 'interrupt'},
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            until = time.monotonic() + 5
            while not (self.root / 'ready').exists() and time.monotonic() < until:
                time.sleep(.01)
            self.assertTrue((self.root / 'ready').exists())
            proc.send_signal(signal.SIGINT)
            out, err = proc.communicate(timeout=5)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        self.assertEqual(proc.returncode, 130, out + err)
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual((self.root / 'work.txt').read_text(), 'preserved')
        self.assertEqual((self.logs() / 'session-id').read_text().strip(),
                         self.calls()[0][self.calls()[0].index('--session') + 1])
        self.assertIn('interrupted natively', (self.logs() / '0001.stderr.log').read_text())

    def test_hangup_preserves_logs_and_work(self):
        proc = subprocess.Popen([sys.executable, str(WRAPPER), '10s', 'Original task'],
                                env={**self.env, 'FIXTURE_MODE': 'interrupt'},
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            until = time.monotonic() + 5
            while not (self.root / 'ready').exists() and time.monotonic() < until:
                time.sleep(.01)
            self.assertTrue((self.root / 'ready').exists())
            proc.send_signal(signal.SIGHUP)
            out, err = proc.communicate(timeout=5)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        self.assertEqual(proc.returncode, 129, out + err)
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual((self.root / 'work.txt').read_text(), 'preserved')
        self.assertIn('interrupted natively', (self.logs() / '0001.stderr.log').read_text())

    def test_wall_clock_does_not_control_deadline(self):
        logdir = self.root / 'direct'
        logdir.mkdir()
        with patch.object(timer.time, 'time', side_effect=AssertionError('wall clock budget')):
            with patch.dict(os.environ, self.env):
                code = timer.run(.05, 'Original task', str(self.binary), logdir)
        self.assertEqual(code, 0)


if __name__ == '__main__':
    unittest.main()
