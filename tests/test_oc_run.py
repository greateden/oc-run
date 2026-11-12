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
import urllib.error
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
        subprocess.run(["git", "init", "-q"], cwd=self.project, check=True)
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

    def wait_inactive(self, run):
        until = time.monotonic() + 8
        while oc.active(run) and time.monotonic() < until:
            time.sleep(.03)
        self.assertFalse(oc.active(run), 'guardian still holds run lease')

    def assert_gone(self, pid):
        until = time.monotonic() + 6
        while time.monotonic() < until:
            info = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True)
            if info.returncode or info.stdout.strip().startswith("Z"):
                return
            time.sleep(.05)
        self.fail(f"child {pid} survived cleanup")

    def test_success_without_milestone_review(self):
        code, output, run, state = self.run_fake()
        self.assertEqual(code, 0, output)
        self.assertEqual(state["status"], "reported-complete")
        self.assertEqual(state["invocations"], 1)
        self.assertEqual(state["session"], "ses_fixture")
        self.assertEqual((self.project / "answer.txt").read_text(), "12\n")
        self.assertIn("not independent proof", (run / "HANDOFF.md").read_text())
        self.assertEqual(run.stat().st_mode & 0o777, 0o700)
        self.assertEqual((run / "run.json").stat().st_mode & 0o777, 0o600)
        self.assertNotIn("\033[", output)

    def test_long_work_survives_budget(self):
        code, output, run, state = self.run_fake("long", "0.2s", "long action")
        self.assertEqual(code, 3, output)
        self.assertEqual(state["status"], "stopped")
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
                    mock.patch.object(oc.time, "monotonic", side_effect=iter(range(0, 100000, 1501))):
                code = oc.invoke("fixture", "prompt", run, "long", None,
                                 lambda: ticks.append(oc.time.monotonic()))
            self.assertEqual(code, 0)
            self.assertEqual(len(ticks), 3)
            self.assertGreater(ticks[-1], 7200)

    def test_tool_failure_keeps_success_and_disclosure(self):
        code, output, run, state = self.run_fake("tool_failure")
        self.assertEqual(code, 0, output)
        self.assertEqual(len(state["incidents"]), 1)
        text = (run / "HANDOFF.md").read_text()
        self.assertIn("Tool unavailable", text)
        self.assertIn("later read succeeded", text)

    def test_continuous_milestones_need_no_extra_inference(self):
        code, output, run, state = self.run_fake('milestones')
        self.assertEqual(code, 0, output)
        self.assertEqual(state['invocations'], 1)
        self.assertEqual(state['successful_tools'], 4)
        self.assertNotIn('REVIEW ONLY', (self.project / 'prompts.txt').read_text())

    def test_repeated_failure_warns_without_killing_worker(self):
        code, output, run, state = self.run_fake('repeat')
        self.assertEqual(code, 0, output)
        records = [json.loads(x) for x in (run / 'journal.jsonl').read_text().splitlines()]
        self.assertEqual(sum(x['kind'] == 'warning' for x in records), 1)
        self.assertIn('WARN', (self.project / 'notifications.jsonl').read_text())
        self.assertEqual(state['invocations'], 1)

    def test_changed_inputs_and_successful_progress_do_not_warn(self):
        for scenario in ('changed', 'progress'):
            with self.subTest(scenario=scenario):
                code, output, run, state = self.run_fake(scenario)
                self.assertEqual(code, 0, output)
                self.assertNotIn('"kind": "warning"', (run / 'journal.jsonl').read_text())

    def test_worker_survives_unavailable_native_inbox(self):
        code, output, run, state = self.run_fake('supervisor_unavailable')
        self.assertEqual(code, 0, output)
        self.assertIn('steering_uncertain', (run / 'journal.jsonl').read_text())
        self.assertTrue((self.project / 'answer.txt').exists())

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
        self.wait_inactive(next(p for p in self.state.iterdir() if p.is_dir()))
        code, output, run, state = self.run_fake("success", "resume", "5s", "--latest")
        self.assertEqual(code, 0, output)
        self.assertEqual((self.project / "partial.txt").read_text(), "Useful output before runner crash\n")
        self.assertIn("Resumed", str(state["incidents"]))
        self.assertEqual(state["invocations"], 2)
        self.assertEqual(len(list(run.glob("[0-9]*-*.jsonl"))), 2)

    def test_transport_error_is_not_success(self):
        code, output, run, state = self.run_fake("transport")
        self.assertEqual(code, 1, output)
        self.assertIn("socket closed", (run / "HANDOFF.md").read_text())

    def test_nonzero_exit_keeps_work(self):
        code, output, run, state = self.run_fake("nonzero")
        self.assertEqual(code, 1, output)
        self.assertIn("Useful partial work", (run / "HANDOFF.md").read_text())
        self.assertIn("exit=7", str(state["incidents"]))

    def test_bad_final_report_preserves_useful_work(self):
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

    def test_cooperative_stop_returns_promptly_and_finishes_action(self):
        proc = self.launch('soft_stop', '1h', 'finish fixture')
        self.wait_file('action-started')
        run = next(p for p in self.state.iterdir() if p.is_dir())
        start = time.monotonic()
        stop = self.launch('success', 'stop', '--latest')
        output, _ = stop.communicate(timeout=2)
        self.assertEqual(stop.returncode, 0, output)
        self.assertLess(time.monotonic() - start, 1)
        self.assertIn('stopping', output)
        self.assertTrue((run / 'stop.json').exists())
        output, _ = proc.communicate(timeout=6)
        self.assertEqual(proc.returncode, 3, output)
        self.assertTrue((self.project / 'action-finished').exists())
        self.assertEqual(json.loads((run / 'run.json').read_text())['status'], 'stopped')
        messages = (self.project / 'notifications.jsonl').read_text()
        self.assertIn('steer', messages)
        self.assertIn('STOP', messages)

    def test_soft_stop_never_escalates_a_stalled_action(self):
        proc = self.launch('stall', '1h', 'test')
        child = int(self.wait_file('child.pid').read_text())
        stop = self.launch('success', 'stop', '--latest')
        output, _ = stop.communicate(timeout=2)
        self.assertEqual(stop.returncode, 0, output)
        time.sleep(.5)
        self.assertIsNone(proc.poll())
        proc.terminate(); proc.communicate(timeout=10)
        self.assert_gone(child)

    def test_force_stop_cleans_resistant_process_group(self):
        proc = self.launch('stall', '1h', 'test')
        child = int(self.wait_file('child.pid').read_text())
        stop = self.launch('success', 'stop', '--latest', '--force')
        output, _ = stop.communicate(timeout=10)
        self.assertEqual(stop.returncode, 0, output)
        proc.communicate(timeout=10)
        self.assert_gone(child)
        run = next(p for p in self.state.iterdir() if p.is_dir())
        self.assertEqual(json.loads((run / 'run.json').read_text())['status'], 'forced')
        self.assertIn('external side effects', (run / 'HANDOFF.md').read_text())

    def test_status_and_stop_on_stopped_and_unknown_runs(self):
        _, _, run, _ = self.run_fake()
        for args in [('status',), ('stop', '--latest')]:
            proc = self.launch('success', *args)
            output, _ = proc.communicate(timeout=2)
            self.assertEqual(proc.returncode, 0, output)
            self.assertIn('reported-complete', output)
        self.assertFalse((run / 'stop.json').exists())
        proc = self.launch('success', 'stop', '--run', str(self.base / 'absent'))
        output, _ = proc.communicate(timeout=2)
        self.assertEqual(proc.returncode, 2, output)
        self.assertIn('unknown run', output)

    def test_active_session_is_recorded_before_invocation_ends(self):
        proc = self.launch('stall', '1h', 'test')
        child = int(self.wait_file('child.pid').read_text())
        run = next(p for p in self.state.iterdir() if p.is_dir())
        until = time.monotonic() + 2
        while json.loads((run / 'run.json').read_text())['session'] is None and time.monotonic() < until:
            time.sleep(.03)
        self.assertEqual(json.loads((run / 'run.json').read_text())['session'], 'ses_fixture')
        self.assertIn('"kind": "session"', (run / 'journal.jsonl').read_text())
        proc.terminate(); proc.communicate(timeout=10); self.assert_gone(child)

    def test_recovery_preserves_torn_log_and_non_idempotent_uncertainty(self):
        proc = self.launch('crash', '1h', 'test')
        child = int(self.wait_file('child.pid').read_text())
        proc.kill(); proc.communicate(timeout=10); self.assert_gone(child)
        run = next(p for p in self.state.iterdir() if p.is_dir())
        self.wait_inactive(run)
        raw = run / '0001-work.jsonl'
        with raw.open('ab') as handle:
            handle.write(b'{"type":"tool_use","part":')
        old_bytes = raw.read_bytes()
        status = self.launch('success', 'status')
        output, _ = status.communicate(timeout=2)
        self.assertIn('no live owner', output)
        code, output, _, state = self.run_fake('success', 'resume', '5s', '--latest')
        self.assertEqual(code, 0, output)
        self.assertEqual(raw.read_bytes(), old_bytes)
        self.assertIn('non-idempotent', str(state['incidents']))
        self.assertIn('external non-idempotent action', str(state['incidents']))
        self.assertIn('session_reconciled', (run / 'journal.jsonl').read_text())
        self.assertIn('RECOVERY:', (self.project / 'prompts.txt').read_text())

    def test_state_kept_outside_git_repository(self):
        subprocess.run(['git', 'init', '-q'], cwd=self.project, check=True)
        env = {**self.env, 'OC_RUN_STATE_DIR': str(self.project / 'state')}
        proc = subprocess.run([sys.executable, str(ROOT / 'oc-run'), '5s', 'test'],
                              cwd=self.project, env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn('outside the project', proc.stderr)

    def test_resume_cancels_only_its_own_stale_control_messages(self):
        self.run_fake()
        code, output, run, state = self.run_fake('stale_control', 'resume', '5s', '--latest')
        self.assertEqual(code, 0, output)
        cancelled = (self.project / 'cancelled.txt').read_text()
        self.assertIn('msg_ocrun_', cancelled)
        self.assertNotIn('msg_unrelated', cancelled)
        self.assertIn('stale_control_cancelled', (run / 'journal.jsonl').read_text())

    def test_append_after_torn_control_journal_preserves_later_record(self):
        run = self.base / 'recording'; run.mkdir()
        path = run / 'journal.jsonl'
        path.write_bytes(b'{"kind":"partial')
        oc.journal(run, 'resumed')
        lines = path.read_bytes().splitlines()
        self.assertEqual(lines[0], b'{"kind":"partial')
        self.assertEqual(json.loads(lines[1])['kind'], 'resumed')

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

    def test_long_handoff_excerpts_keep_full_evidence(self):
        _, _, run, state = self.run_fake()
        long = 'x' * 30000
        oc.atomic_write(run / 'task.txt', long)
        state.update(last_work=long, incidents=[long])
        state['review'].update(summary=long, next=long, evidence=[long])
        oc.incident(run, state, long)
        oc.atomic_write(run / '0001-work.md', long)
        oc.save(run, state)
        self.assertLess(len((run / 'HANDOFF.md').read_text()), 16000)
        self.assertEqual((run / 'task.txt').read_text(), long)
        self.assertLess((run / 'run.json').stat().st_size, 16000)
        self.assertIn(long, (run / 'journal.jsonl').read_text())
        self.assertEqual((run / '0001-work.md').read_text(), long)

    def test_oversized_state_remains_stoppable_and_recoverable(self):
        proc = self.launch('crash', '1h', 'test')
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        child = int(self.wait_file('child.pid').read_text())
        run = next(p for p in self.state.iterdir() if p.is_dir())
        until = time.monotonic() + 2
        while oc.load_state(run)['session'] is None and time.monotonic() < until:
            time.sleep(.03)
        state = oc.load_state(run)
        state.pop('compact_state', None)  # simulate a pre-upgrade snapshot
        state['last_work'] = 'retained old output ' * 70000
        old = json.dumps(state)
        oc.atomic_write(run / 'run.json', old)
        self.assertGreater((run / 'run.json').stat().st_size, 1024 * 1024)
        for args in [('status',), ('stop', '--latest')]:
            command = self.launch('success', *args)
            output, _ = command.communicate(timeout=2)
            self.assertEqual(command.returncode, 0, output)
        proc.kill(); proc.communicate(timeout=10)
        self.assert_gone(child); self.wait_inactive(run)
        # The runner may already have compacted at the stop boundary.
        if not (run / 'legacy-state.json').exists():
            oc.atomic_write(run / 'run.json', old)
        code, output, _, state = self.run_fake('success', 'resume', '5s', '--latest')
        self.assertEqual(code, 0, output)
        self.assertEqual((run / 'legacy-state.json').read_text(), old)
        self.assertLess((run / 'run.json').stat().st_size, 64000)

    def test_growing_overnight_journal_keeps_control_state_small(self):
        _, _, run, state = self.run_fake()
        for i in range(1200):
            oc.incident(run, state, str(i) + ': ' + 'x' * 1200)
            if i % 100 == 0:
                oc.save(run, state)
                self.assertLess((run / 'run.json').stat().st_size, 64000)
        oc.save(run, state)
        self.assertGreater((run / 'journal.jsonl').stat().st_size, 1024 * 1024)
        self.assertEqual(len(state['incidents']), 12)
        self.assertEqual(oc.load_state(run)['session'], 'ses_fixture')
        self.assertEqual(len([x for x in (run / 'journal.jsonl').read_text().splitlines()
                              if json.loads(x)['kind'] == 'incident']), 1200)
        # A growing journal must not affect the control command's read path.
        live = self.launch('stall', '1h', 'overnight fixture')
        child = int(self.wait_file('child.pid').read_text())
        live_run = next(p for p in self.state.iterdir() if p.is_dir() and p != run)
        with (live_run / 'journal.jsonl').open('ab') as handle:
            handle.write((run / 'journal.jsonl').read_bytes())
        stop = self.launch('success', 'stop', '--latest')
        output, _ = stop.communicate(timeout=2)
        self.assertEqual(stop.returncode, 0, output)
        self.assertTrue((live_run / 'stop.json').exists())
        live.terminate(); live.communicate(timeout=10); self.assert_gone(child)

    def test_corrupt_or_symlink_state_has_clear_error(self):
        run = self.base / 'bad'; run.mkdir()
        for text in ('{bad', 'null', '[]', '{}'):
            (run / 'run.json').write_text(text)
            with self.assertRaisesRegex(ValueError, 'cannot read state'):
                oc.load_state(run)
        (run / 'run.json').unlink()
        (run / 'run.json').symlink_to(self.base / 'target')
        with self.assertRaisesRegex(ValueError, 'cannot read state'):
            oc.load_state(run)

    def test_malformed_nested_events_do_not_hide_later_valid_events(self):
        bad = [{'type': 'tool_use', 'part': value} for value in ([], 'oops', 42)]
        for keys in [('state',), ('state', 'metadata'), ('state', 'metadata', 'metadata')]:
            for value in ([], 'oops', 42, True):
                event = {'type': 'tool_use', 'part': {}}
                parent = event['part']
                for key in keys[:-1]:
                    parent[key] = {}; parent = parent[key]
                parent[keys[-1]] = value
                bad.append(event)
        bad += [{'type': 'text', 'part': {'text': None}}, {'type': 'tool_use', 'part': {'id': []}}]
        valid = [{'type': 'step_start', 'part': None}, {'type': 'tool_use'},
                 {'type': 'tool_use', 'part': {'id': 'ok', 'tool': 'read', 'state': {
                     'status': 'completed', 'metadata': None, 'output': 'useful'}}},
                 {'type': 'text', 'part': {'text': 'after malformed'}}]
        path = self.base / 'events.jsonl'
        raw = ''.join(json.dumps(x) + '\n' for x in bad + valid)
        path.write_text(raw)
        facts = oc.events(path)
        self.assertEqual(len(facts['diagnostics']), len(bad))
        self.assertEqual(len(facts['successes']), 1)
        self.assertEqual(facts['text'], 'after malformed')
        self.assertEqual(path.read_text(), raw)
        code, output, run, state = self.run_fake('bad_events')
        self.assertEqual(code, 0, output)
        self.assertEqual(state['successful_tools'], 1)
        self.assertIn('malformed_event', (run / 'journal.jsonl').read_text())
        code, output, _, state = self.run_fake('bad_event_then_error')
        self.assertEqual(code, 1, output)
        self.assertEqual(state['status'], 'failed')
        self.assertIn('real fatal error', str(state['incidents']))

    def test_latest_control_does_not_cross_projects(self):
        proc = self.launch('stall', '1h', 'first project')
        child = int(self.wait_file('child.pid').read_text())
        first = next(p for p in self.state.iterdir() if p.is_dir())
        other = self.base / 'other'; other.mkdir()
        subprocess.run(['git', 'init', '-q'], cwd=other, check=True)
        for args in [('status',), ('stop', '--latest'), ('resume', '1s', '--latest')]:
            result = subprocess.run([sys.executable, str(ROOT / 'oc-run'), *args], cwd=other,
                                    env=self.env, capture_output=True, text=True, timeout=2)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn('current project', result.stderr)
        self.assertFalse((first / 'stop.json').exists())
        second = subprocess.Popen([sys.executable, str(ROOT / 'oc-run'), '1h', 'second'], cwd=other,
                    env={**self.env, 'FAKE_SCENARIO': 'stall'}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        until = time.monotonic() + 4
        while not (other / 'child.pid').exists() and time.monotonic() < until:
            time.sleep(.03)
        other_child = int((other / 'child.pid').read_text())
        stop = self.launch('success', 'stop', '--latest')
        output, _ = stop.communicate(timeout=2)
        self.assertEqual(stop.returncode, 0, output)
        self.assertTrue((first / 'stop.json').exists())
        second_run = next(p for p in self.state.iterdir() if p.is_dir() and p != first)
        self.assertFalse((second_run / 'stop.json').exists())
        explicit = subprocess.run([sys.executable, str(ROOT / 'oc-run'), 'status', '--run', str(first)],
                                  cwd=other, env=self.env, capture_output=True, text=True, timeout=2)
        self.assertEqual(explicit.returncode, 0, explicit.stdout + explicit.stderr)
        for process in (proc, second):
            process.terminate(); process.communicate(timeout=10)
        self.assert_gone(child); self.assert_gone(other_child)

    def test_guardian_cleans_descendant_after_immediate_child_exits(self):
        reader, writer = os.pipe()
        path = self.base / 'descendant.pid'
        script = ("import subprocess,sys;from pathlib import Path;"
                  "p=subprocess.Popen([sys.executable,'-c',"
                  "'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(120)']);"
                  "Path(sys.argv[1]).write_text(str(p.pid))")
        proc = subprocess.Popen([sys.executable, str(ROOT / 'oc-run'), '_child', str(reader),
                                 sys.executable, '-c', script, str(path)], pass_fds=(reader,), start_new_session=True)
        os.close(reader)
        try:
            self.assertEqual(proc.wait(timeout=6), 0)
            self.assert_gone(int(path.read_text()))
        finally:
            os.close(writer)

    def test_stop_delivery_reconciles_before_retry_and_reports_unknown(self):
        _, _, run, state = self.run_fake()
        for failure in (OSError('connection dropped'), urllib.error.HTTPError('fixture', 503, 'busy', {}, None)):
            with self.subTest(failure=failure):
                delivery = {'id': 'msg_stop', 'status': 'pending'}
                state['stop_delivery'] = delivery
                server = mock.Mock()
                server.request.side_effect = [failure, {'data': []},
                    urllib.error.HTTPError('fixture', 404, 'absent', {}, None), {'data': {'id': 'msg_stop'}}]
                oc.steer(server, run, state, oc.STOP, delivery)
                self.assertEqual(delivery['status'], 'uncertain')
                oc.steer(server, run, state, oc.STOP, delivery)
                self.assertEqual(delivery['status'], 'confirmed')
                paths = [x.args[0] for x in server.request.call_args_list]
                self.assertTrue(paths[1].endswith('/inbox'))
                self.assertTrue(paths[2].endswith('/message/msg_stop'))
                self.assertEqual(server.request.call_args_list[0].args[1]['id'],
                                 server.request.call_args_list[-1].args[1]['id'])
        for receipt in ({'data': None}, {'data': {'id': 'different'}}, {}):
            delivery = {'id': 'msg_unknown', 'status': 'pending'}
            state['stop_delivery'] = delivery
            server = mock.Mock()
            server.request.side_effect = [receipt, OSError('inbox offline')]
            oc.steer(server, run, state, oc.STOP, delivery)
            self.assertEqual(oc.load_state(run)['stop_delivery']['status'], 'uncertain')
            oc.steer(server, run, state, oc.STOP, delivery)
            self.assertEqual(server.request.call_count, 2)  # one POST, one GET; no blind resend
            server.request.side_effect = None
            server.request.return_value = {'data': [{'id': 'msg_unknown'}]}
            oc.steer(server, run, state, oc.STOP, delivery)
            self.assertEqual(delivery['status'], 'confirmed')
        delivery = {'id': 'msg_promoted', 'status': 'uncertain'}
        state['stop_delivery'] = delivery
        server = mock.Mock()
        server.request.side_effect = [{'data': []}, {'data': {'id': 'msg_promoted'}}]
        oc.steer(server, run, state, oc.STOP, delivery)
        self.assertEqual(delivery['status'], 'confirmed')
        self.assertEqual(server.request.call_count, 2)  # promotion is acceptance, not an absent inbox
        delivery = {'id': 'msg_rejected', 'status': 'pending'}
        state['stop_delivery'] = delivery
        server = mock.Mock()
        server.request.side_effect = urllib.error.HTTPError('fixture', 403, 'denied', {}, None)
        oc.steer(server, run, state, oc.STOP, delivery)
        oc.steer(server, run, state, oc.STOP, delivery)
        self.assertEqual(delivery['status'], 'rejected')
        self.assertEqual(server.request.call_count, 1)

    def test_stop_transport_failure_recovers_without_duplicate_admission(self):
        for scenario, attempts, expected in [('stop_recovery', 2, 'confirmed'),
                                             ('stop_unknown_ack', 1, 'confirmed'),
                                             ('stop_rejected', 1, 'rejected')]:
            with self.subTest(scenario=scenario):
                notifications = self.project / 'notifications.jsonl'
                if notifications.exists():
                    notifications.unlink()
                code, output, run, state = self.run_fake(scenario, '0.2s', 'fixture')
                self.assertEqual(code, 3, output)
                self.assertEqual(state['stop_delivery']['status'], expected)
                messages = [json.loads(x) for x in notifications.read_text().splitlines()]
                self.assertEqual(len(messages), attempts)
                self.assertEqual(len({x['id'] for x in messages}), 1)
                self.assertTrue((self.project / 'action-finished').exists())
                self.assertFalse((run / 'force.json').exists())

    def test_completion_is_reported_not_independently_verified(self):
        for scenario in ('incomplete', 'no_evidence'):
            code, output, run, state = self.run_fake(scenario)
            self.assertEqual(code, 3, output)
            self.assertEqual(state['status'], 'incomplete')
            self.assertGreater(state['successful_tools'], 0)
        code, output, run, state = self.run_fake()
        self.assertEqual(code, 0, output)
        self.assertEqual(state['status'], 'reported-complete')
        self.assertIn('Independent acceptance checks: not run', (run / 'HANDOFF.md').read_text())
        proc = self.launch('success', '5s', '--stop-when-done', 'unused')
        output, _ = proc.communicate(timeout=2)
        self.assertEqual(proc.returncode, 2, output)
        self.assertIn('unrecognized arguments', output)

    def test_unknown_stop_survives_runner_crash(self):
        proc = self.launch('stop_offline', '1h', 'test')
        child = int(self.wait_file('child.pid').read_text())
        run = next(p for p in self.state.iterdir() if p.is_dir())
        stop = self.launch('success', 'stop', '--latest')
        output, _ = stop.communicate(timeout=2)
        self.assertEqual(stop.returncode, 0, output)
        until = time.monotonic() + 3
        while oc.load_state(run).get('stop_delivery', {}).get('status') != 'uncertain' and time.monotonic() < until:
            time.sleep(.03)
        proc.kill(); proc.communicate(timeout=8)
        self.assert_gone(child); self.wait_inactive(run)
        state = oc.load_state(run)
        self.assertEqual(state['stop_delivery']['status'], 'uncertain', output)
        self.assertEqual(json.loads((run / 'stop.json').read_text())['execution'], state['execution'])
        self.assertIn('steering_uncertain', (run / 'journal.jsonl').read_text())
        self.assertTrue((run / 'CONTROL.md').read_text().startswith('STOP'))


if __name__ == "__main__":
    unittest.main()
