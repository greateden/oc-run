import argparse
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
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LOADER = importlib.machinery.SourceFileLoader("oc_run", str(ROOT / "oc-run"))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
oc = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(oc)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.project = self.base / "project"
        self.project.mkdir()
        self.state = self.base / "state"
        self.fake = self.base / "opencode"
        self.fake.write_text((ROOT / "tests/fake_opencode.py").read_text())
        self.fake.chmod(0o700)
        self.env = {**os.environ, "OC_RUN_BIN": str(self.fake), "OC_RUN_STATE_DIR": str(self.state),
                    "NO_COLOR": "1"}

    def launch(self, scenario="success", *args):
        env = {**self.env, "FAKE_SCENARIO": scenario}
        return subprocess.Popen([sys.executable, str(ROOT / "oc-run"), *args], cwd=self.project,
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def run_fake(self, scenario="success", *args):
        proc = self.launch(scenario, *(args or ("5s", "test fixture")))
        output, _ = proc.communicate(timeout=15)
        runs = sorted(p for p in self.state.iterdir() if p.is_dir())
        run = max(runs, key=lambda p: (p / 'run.json').stat().st_mtime_ns)
        return proc.returncode, output, run, json.loads((run / "run.json").read_text())

    def wait_file(self, name):
        until = time.monotonic() + 8
        while time.monotonic() < until:
            if (self.project / name).exists():
                return self.project / name
            time.sleep(.03)
        self.fail(f"fixture did not create {name}")

    def assert_gone(self, pid):
        until = time.monotonic() + 6
        while time.monotonic() < until:
            info = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True)
            if info.returncode or info.stdout.strip().startswith("Z"):
                return
            time.sleep(.05)
        self.fail(f"child {pid} survived cleanup")

    def test_success_and_same_session_review(self):
        code, output, run, state = self.run_fake()
        self.assertEqual(code, 0, output)
        self.assertEqual(state["status"], "reviewed-complete")
        self.assertEqual(state["invocations"], 2)
        self.assertEqual(state["session"], "ses_fixture")
        self.assertEqual((self.project / "answer.txt").read_text(), "12\n")
        self.assertIn("not independent proof", (run / "HANDOFF.md").read_text())
        self.assertEqual(run.stat().st_mode & 0o777, 0o700)
        self.assertEqual((run / "run.json").stat().st_mode & 0o777, 0o600)
        self.assertNotIn("\033[", output)

    def test_long_work_survives_budget(self):
        code, output, run, state = self.run_fake("long", "0.2s", "long action")
        self.assertEqual(code, 0, output)
        self.assertGreater(state["elapsed"], .5)
        self.assertIn("STOP", (run / "CONTROL.md").read_text())
        self.assertIn("budget ended", output)

    def test_no_old_25_minute_limit_accelerated_clock(self):
        # Exercise the production wait loop with >25 minutes of virtual elapsed time.
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            process = mock.Mock(pid=999999, returncode=0)
            process.poll.side_effect = [None, None, None, 0]
            ticks = []
            with mock.patch.object(oc.subprocess, "Popen", return_value=process), \
                    mock.patch.object(oc, "cleanup"), mock.patch.object(oc.time, "sleep"), \
                    mock.patch.object(oc.time, "monotonic", side_effect=[0, 1501, 7200]):
                code = oc.invoke("fixture", "prompt", run, "long", None,
                                 lambda: ticks.append(oc.time.monotonic()))
            self.assertEqual(code, 0)
            self.assertEqual(ticks, [0, 1501, 7200])

    def test_tool_failure_keeps_success_and_disclosure(self):
        code, output, run, state = self.run_fake("tool_failure")
        self.assertEqual(code, 0, output)
        self.assertEqual(len(state["incidents"]), 1)
        text = (run / "HANDOFF.md").read_text()
        self.assertIn("Tool unavailable", text)
        self.assertIn("later read succeeded", text)

    def test_final_review_can_use_prior_tool_evidence(self):
        code, output, run, state = self.run_fake('prior_evidence')
        self.assertEqual(code, 0, output)
        self.assertEqual(state['invocations'], 4)
        self.assertEqual(state['successful_tools'], 1)

    def test_repeated_unproductive_action_stops(self):
        code, output, run, state = self.run_fake("repeat")
        self.assertEqual(code, 3, output)
        self.assertEqual(state["invocations"], 4)
        self.assertIn("repeated", state["reason"])

    def test_pivot_carries_different_action(self):
        code, output, run, state = self.run_fake("pivot")
        self.assertEqual(code, 0, output)
        self.assertIn("PIVOT", output)
        self.assertEqual(state["invocations"], 4)

    def test_premature_completion_is_unverified(self):
        code, output, run, state = self.run_fake("premature")
        self.assertEqual(code, 3, output)
        self.assertFalse(state["review"]["complete"])
        self.assertIn("lacks observed", state["reason"])

    def test_interruption_and_resistant_grandchild(self):
        proc = self.launch("stall", "1h", "test")
        child = int(self.wait_file("child.pid").read_text())
        proc.send_signal(signal.SIGINT)
        output, _ = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 130, output)
        self.assert_gone(child)
        run = next(p for p in self.state.iterdir() if p.is_dir())
        state = json.loads((run / "run.json").read_text())
        self.assertEqual(state["status"], "interrupted")
        self.assertIn("in-flight", (run / "HANDOFF.md").read_text())

    def test_stalled_child_sigterm_is_bounded(self):
        proc = self.launch("stall", "1h", "test")
        child = int(self.wait_file("child.pid").read_text())
        start = time.monotonic()
        proc.terminate()
        output, _ = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 143, output)
        self.assertLess(time.monotonic() - start, 6)
        self.assert_gone(child)

    def test_runner_crash_guard_and_resume(self):
        proc = self.launch("crash", "1h", "test")
        child = int(self.wait_file("child.pid").read_text())
        self.wait_file("partial.txt")
        proc.kill()
        proc.communicate(timeout=10)
        self.assert_gone(child)
        code, output, run, state = self.run_fake("success", "resume", "5s", "--latest")
        self.assertEqual(code, 0, output)
        self.assertEqual((self.project / "partial.txt").read_text(), "Useful output before runner crash\n")
        self.assertIn("Resumed", str(state["incidents"]))
        self.assertEqual(state["invocations"], 3)
        self.assertEqual(len(list(run.glob("*.jsonl"))), 3)

    def test_transport_error_is_not_success(self):
        code, output, run, state = self.run_fake("transport")
        self.assertEqual(code, 1, output)
        self.assertIn("socket closed", (run / "HANDOFF.md").read_text())

    def test_nonzero_exit_keeps_work(self):
        code, output, run, state = self.run_fake("nonzero")
        self.assertEqual(code, 1, output)
        self.assertIn("Useful partial work", (run / "HANDOFF.md").read_text())
        self.assertIn("exit=7", str(state["incidents"]))

    def test_bad_review_preserves_useful_work(self):
        code, output, run, state = self.run_fake("malformed")
        self.assertEqual(code, 1, output)
        self.assertTrue((self.project / "answer.txt").exists())
        self.assertIn("Milestone complete", (run / "HANDOFF.md").read_text())

    def test_git_dirty_and_push_authorisation(self):
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.project, check=True)
        (self.project / "private.txt").write_text("pre-existing uncommitted work")
        code, output, run, state = self.run_fake()
        self.assertEqual(code, 0, output)
        self.assertIn("Do not git push", (self.project / "prompts.txt").read_text())
        self.assertIn("private.txt", state["git_before"]["changes"])
        self.assertEqual((self.project / "private.txt").read_text(), "pre-existing uncommitted work")
        code, output, run, state = self.run_fake("success", "5s", "--push", "test")
        self.assertEqual(code, 0, output)
        self.assertTrue(state["push"])
        self.assertIn("Push is permitted only after checks", (self.project / "prompts.txt").read_text())
        self.assertEqual(subprocess.run(["git", "remote"], cwd=self.project, capture_output=True).stdout, b"")

    def test_dry_run_no_subprocess_or_state(self):
        with mock.patch.dict(os.environ, self.env), mock.patch.object(oc.subprocess, "run") as command:
            self.assertEqual(oc.main(["10h", "test", "--dry-run"]), 0)
        command.assert_not_called()
        self.assertFalse(self.state.exists())

    def test_handoff_read_only_and_no_model(self):
        _, _, run, _ = self.run_fake()
        before = {p.name: p.read_bytes() for p in run.iterdir() if p.is_file()}
        proc = self.launch("stall", "handoff", "--latest")
        output, _ = proc.communicate(timeout=5)
        self.assertEqual(proc.returncode, 0, output)
        self.assertIn("Original task", output)
        self.assertEqual(before, {p.name: p.read_bytes() for p in run.iterdir() if p.is_file()})

    def test_duration_validation(self):
        self.assertEqual(oc.duration("10h"), 36000)
        for bad in ("0", "nan", "-1h", "infs", "1e999s"):
            with self.assertRaises(argparse.ArgumentTypeError):
                oc.duration(bad)

    def test_atomic_write_and_no_symlink_reads(self):
        path = self.base / "state.txt"
        oc.atomic_write(path, "first")
        oc.atomic_write(path, "second")
        link = self.base / "link"
        link.symlink_to(path)
        self.assertEqual(oc.read(path), "second")
        self.assertEqual(oc.read(link), "")
        self.assertFalse(list(self.base.glob(".write-*")))

    def test_repository_lock(self):
        proc = self.launch("stall", "1h", "test")
        child = int(self.wait_file("child.pid").read_text())
        other = self.launch("success", "5s", "test")
        output, _ = other.communicate(timeout=5)
        self.assertEqual(other.returncode, 2, output)
        self.assertIn("another oc-run", output)
        proc.terminate()
        proc.communicate(timeout=10)
        self.assert_gone(child)

    def test_insecure_state_root_is_rejected(self):
        self.state.mkdir(mode=0o755)
        self.state.chmod(0o755)
        proc = self.launch('success', '5s', 'test')
        output, _ = proc.communicate(timeout=5)
        self.assertEqual(proc.returncode, 2, output)
        self.assertIn('private directory', output)
        self.assertFalse((self.project / 'prompts.txt').exists())

    def test_historical_handoff_keeps_rejected_state_unverified(self):
        self.state.mkdir(mode=0o700)
        run = self.state / 'historical'
        run.mkdir(mode=0o700)
        (run / 'STATE.md').write_text('Old model claim')
        (run / 'RESULT.txt').write_text('SAFETY_TIMEOUT; finalisation=failed; exit=124')
        (run / 'final.log.unverified-state').write_text('Useful but unverified final candidate')
        before = {p.name: p.read_bytes() for p in run.iterdir()}
        proc = self.launch('stall', 'handoff', '--latest')
        output, _ = proc.communicate(timeout=5)
        self.assertEqual(proc.returncode, 0, output)
        self.assertIn('completion unverified', output)
        self.assertIn('exit=124', output)
        self.assertIn('UNVERIFIED final candidate', output)
        self.assertEqual(before, {p.name: p.read_bytes() for p in run.iterdir()})

    def test_long_handoff_excerpts_keep_full_state(self):
        _, _, run, state = self.run_fake()
        long = 'x' * 30000
        oc.atomic_write(run / 'task.txt', long)
        state.update(last_work=long, incidents=[long])
        state['review'].update(summary=long, next=long, evidence=[long])
        oc.save(run, state)
        self.assertLess(len((run / 'HANDOFF.md').read_text()), 16000)
        self.assertEqual((run / 'task.txt').read_text(), long)
        self.assertEqual(json.loads((run / 'run.json').read_text())['incidents'], [long])


if __name__ == "__main__":
    unittest.main()
