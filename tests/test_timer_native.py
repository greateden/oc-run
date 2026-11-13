"""Opt-in timer checks against the installed CLI and an isolated local provider."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import unittest

import test_native_workflow as native


WRAPPER = Path(__file__).resolve().parents[1] / 'oc-run'


@unittest.skipUnless(os.environ.get('OC_NATIVE_BIN'), 'set OC_NATIVE_BIN to installed OpenCode')
class NativeTimer(unittest.TestCase):
    setUp = native.NativeWorkflow.setUp
    cli = native.NativeWorkflow.cli

    def launch(self, budget, prompt):
        bindir = self.root / 'bin'
        bindir.mkdir(exist_ok=True)
        binary = bindir / 'opencode'
        if not binary.exists():
            binary.symlink_to(os.environ['OC_NATIVE_BIN'])
        self.env['PATH'] = str(bindir) + os.pathsep + os.environ['PATH']
        return subprocess.Popen([sys.executable, str(WRAPPER), budget, prompt], cwd=self.project,
                                env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True)

    def finish(self, proc):
        try:
            out, err = proc.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            proc.send_signal(signal.SIGINT)
            proc.communicate(timeout=10)
            raise
        self.logdir = next((self.root / 'state' / 'oc-run').iterdir())
        evidence = os.environ.get('OC_RUN_TEST_EVIDENCE')
        if evidence:
            target = Path(evidence) / self._testMethodName
            shutil.copytree(self.logdir, target, dirs_exist_ok=True)
            (target / 'wrapper.stdout').write_text(out)
            (target / 'wrapper.stderr').write_text(err)
        return proc.returncode, out, err

    def export(self):
        sid = (self.logdir / 'session-id').read_text().strip()
        result = self.cli(['session', 'export', '--standalone', sid])
        self.assertEqual(result.returncode, 0, result.stderr)
        evidence = os.environ.get('OC_RUN_TEST_EVIDENCE')
        if evidence:
            (Path(evidence) / self._testMethodName / 'session.json').write_text(result.stdout)
        return sid, result.stdout

    def test_multiple_turns_same_session_agent_and_original_prompt(self):
        self.provider_delay = .35
        code, out, err = self.finish(self.launch('2s', '[normal] Original research fixture'))
        self.assertEqual(code, 0, out + err)
        files = list(self.logdir.glob('*.stdout.jsonl'))
        self.assertGreaterEqual(len(files), 2)
        sid, exported = self.export()
        ids = {json.loads(line)['sessionID'] for p in files for line in p.read_text().splitlines()}
        self.assertEqual(ids, {sid})
        self.assertIn('[normal] Original research fixture', exported)
        users = [m['text'] for m in json.loads(exported)['messages'] if m['type'] == 'user']
        self.assertEqual(users[0], '[normal] Original research fixture')
        self.assertEqual(len(users), len(files))
        self.assertTrue(all(t == users[1] for t in users[1:]), 'stable continuation text')
        self.assertIn('Review the work completed so far', exported)
        self.assertIn('sage-research', exported)
        self.assertIn('Maximise scientific information gained', json.dumps(self.requests[0]))
        self.assertIn('fixture stderr', exported, 'tool failure remains visible, does not stop timer')
        print(f'timer/native: {len(files)} turns; one session {sid}; project agent and original prompt retained')

    def test_deadline_does_not_interrupt_blocked_active_turn(self):
        proc = self.launch('0.1s', '[interrupt] finish the active turn')
        try:
            self.assertTrue(self.blocked.wait(10), 'native shell ran and second provider request started')
            time.sleep(.2)
            self.assertIsNone(proc.poll(), 'wrapper remains alive beyond deadline')
        finally:
            self.release.set()
        code, out, err = self.finish(proc)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(len(list(self.logdir.glob('*.stdout.jsonl'))), 1)
        self.assertEqual((self.project / 'interrupted.txt').read_text(), 'preserved before interruption')
        self.assertIn('Useful partial output', (self.logdir / '0001.stdout.jsonl').read_text())
        self.export()
        print('timer/native: deadline passed during active turn; full answer retained; no second turn')

    def test_empty_final_answer_is_not_rejected(self):
        self.provider_delay = .65
        code, out, err = self.finish(self.launch('2s', '[empty]'))
        self.assertEqual(code, 0, out + err)
        self.assertGreaterEqual(len(self.requests), 2, 'empty first answer permits continuation')
        self.export()

    def test_provider_oom_is_not_retried(self):
        code, out, err = self.finish(self.launch('10s', '[oom]'))
        self.assertEqual(code, 1, out + err)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(len(list(self.logdir.glob('*.stdout.jsonl'))), 1)
        self.assertIn('fixture provider out of memory', (self.logdir / '0001.stdout.jsonl').read_text())
        self.export()

    def test_ctrl_c_uses_native_interruption_and_preserves_work(self):
        proc = self.launch('10s', '[interrupt]')
        try:
            self.assertTrue(self.blocked.wait(10))
            proc.send_signal(signal.SIGINT)
            code, out, err = self.finish(proc)
        finally:
            self.release.set()
        self.assertEqual(code, 130, out + err)
        self.assertEqual((self.project / 'interrupted.txt').read_text(), 'preserved before interruption')
        self.assertIn('tool_use', (self.logdir / '0001.stdout.jsonl').read_text())
        self.assertEqual(len(list(self.logdir.glob('*.stdout.jsonl'))), 1)
        self.export()


if __name__ == '__main__':
    unittest.main()
