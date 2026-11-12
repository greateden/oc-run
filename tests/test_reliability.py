"""Bounded synthetic logs and explicit non-Git workspaces. No model calls."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tracemalloc
import unittest
from unittest import mock

from test_oc_run import ROOT, oc


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.project = self.base / 'project'
        self.project.mkdir()
        self.nested = self.project / 'nested'
        self.nested.mkdir()
        self.state = self.base / 'state'
        self.fake = self.base / 'opencode'
        self.fake.write_text((ROOT / 'tests/fake_opencode.py').read_text())
        self.fake.chmod(0o700)
        self.env = {**os.environ, 'OC_RUN_STATE_DIR': str(self.state), 'OC_RUN_BIN': str(self.fake)}

    def run_cli(self, cwd, *args, env=None):
        return subprocess.run([sys.executable, str(ROOT / 'oc-run'), *args], cwd=cwd,
                              env=env or self.env, capture_output=True, text=True, timeout=10)

    def test_summary_memory_is_bounded_and_raw_log_unchanged(self):
        path = self.base / 'large.jsonl'
        peaks = []
        for count in (2000, 20000):
            with path.open('w') as handle:
                for i in range(count):
                    handle.write(json.dumps({'type': 'text', 'part': {'text': 'x' * 1000}}) + '\n')
                    handle.write(json.dumps({'type': 'tool_use', 'part': {'id': str(i), 'tool': 'read',
                        'state': {'status': 'completed', 'input': {'path': 'x'}}}}) + '\n')
            before = self.digest(path)
            tracemalloc.start()
            try:
                facts = oc.events(path)
                peaks.append(tracemalloc.get_traced_memory()[1])
            finally:
                tracemalloc.stop()
            self.assertEqual(facts['successful_tools'], count)
            self.assertLessEqual(len(facts['text']), oc.TEXT_LIMIT)
            self.assertLessEqual(len(facts['successes']), oc.SUMMARY_ITEMS)
            self.assertIn('summary limited', str(facts['diagnostics']))
            self.assertEqual(before, self.digest(path))
        self.assertLess(peaks[1], peaks[0] + 2 * 1024 * 1024, peaks)
        self.assertLess(peaks[1], 8 * 1024 * 1024, peaks)

    @staticmethod
    def digest(path):
        with path.open('rb') as handle:
            digest = hashlib.sha256()
            while chunk := handle.read(65536):
                digest.update(chunk)
            return digest.hexdigest()

    def test_live_tail_discards_oversized_records_and_keeps_later_events(self):
        peaks = []
        for size in (2, 20):
            observed = []
            summary = oc.EventSummary()
            @contextmanager
            def guarded(command, output, *args):
                block = b'x' * 65536
                for _ in range(size * 16):
                    output.write(block)
                output.write(b'\n{"type":"text","sessionID":"ses_after","part":{"text":"after"}}\n')
                yield mock.Mock(poll=lambda: 0, returncode=0)
            with mock.patch.object(oc, 'guarded', guarded):
                tracemalloc.start()
                try:
                    rc = oc.invoke('fixture', 'prompt', self.base, str(size), None,
                                   lambda: None, observed.append, summary=summary)
                    peaks.append(tracemalloc.get_traced_memory()[1])
                finally:
                    tracemalloc.stop()
            facts = summary.finish()
            self.assertEqual(rc, 0)
            self.assertEqual(observed[-1]['sessionID'], 'ses_after')
            self.assertEqual(facts['text'], 'after')
            self.assertIn('oversized', str(facts['diagnostics']))
            self.assertEqual((self.base / f'{size}.jsonl').stat().st_size,
                             size * 1024 * 1024 + 65)
            self.assertEqual(oc.events(self.base / f'{size}.jsonl')['text'], 'after')
        self.assertLess(peaks[1], peaks[0] + 1024 * 1024, peaks)
        self.assertLess(peaks[1], 4 * 1024 * 1024, peaks)

    def test_partial_and_malformed_records_preserve_later_events(self):
        path = self.base / 'partial'
        path.touch()
        with path.open('rb') as handle:
            reader = oc.RecordReader(handle)
            for chunk, expected in [(b'{"type":', []), (b'"text"}\n', [{'type': 'text'}]),
                                    (b'bad json\n[]\n{"type":"step_start"}\n', [[], {'type': 'step_start'}])]:
                with path.open('ab') as output:
                    output.write(chunk)
                self.assertEqual(list(reader.events()), expected)
            for _ in range(20):
                with path.open('ab') as output:
                    output.write(b'x' * 65536)
                self.assertEqual(list(reader.events()), [])
                self.assertLessEqual(len(reader.pending), oc.MAX_EVENT_BYTES)
            with path.open('ab') as output:
                output.write(b'\n{"type":"text"}\n{"torn":')
            self.assertEqual(list(reader.events()), [None, {'type': 'text'}])

    def test_summary_retains_fatal_errors_and_latest_call_update(self):
        path = self.base / 'events'
        rows = [{'type': 'tool_use', 'part': {'id': 'same', 'state': {'status': status}}}
                for status in ('running', 'error', 'completed')]
        rows += [{'type': 'error', 'error': 'fatal'}]
        rows += [{'type': 'text', 'part': {'text': 'x'}}] * 100
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        facts = oc.events(path)
        self.assertEqual(facts['successful_tools'], 1)
        self.assertEqual(facts['failures'], [])
        self.assertEqual(facts['errors'], ['fatal'])

    def test_non_git_requires_root_and_declared_root_locks_nested_worker(self):
        result = self.run_cli(self.project, '5s', 'fixture')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('--project-root', result.stderr)
        self.assertFalse(self.state.exists())
        proc = subprocess.Popen([sys.executable, str(ROOT / 'oc-run'), '5s', 'fixture',
            '--project-root', str(self.project)], cwd=self.project,
            env={**self.env, 'FAKE_SCENARIO': 'long'}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            until = time.monotonic() + 5
            while not (self.project / 'action-started').exists() and time.monotonic() < until:
                time.sleep(.01)
            self.assertTrue((self.project / 'action-started').exists())
            result = self.run_cli(self.nested, '5s', 'fixture', '--project-root', str(self.project))
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn('another oc-run', result.stderr)
            other = self.base / 'other'; other.mkdir()
            result = self.run_cli(other, '5s', 'fixture', '--project-root', str(other))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        finally:
            proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 0)
        result = self.run_cli(self.nested, 'resume', '5s', '--latest', '--project-root', str(self.project))
        self.assertEqual(result.returncode, 2)  # Existing controls remain cwd-local.
        result = self.run_cli(self.project, 'resume', '5s', '--latest', '--project-root', str(self.project))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_private_state_rejects_nested_paths_and_resolved_symlinks(self):
        alias = self.base / 'alias'; alias.symlink_to(self.project, target_is_directory=True)
        for state in (self.project / 'private', self.nested / 'a' / 'b', alias / 'private'):
            with self.subTest(state=state):
                result = self.run_cli(self.nested, '5s', 'fixture', '--project-root', str(self.project),
                    env={**self.env, 'OC_RUN_STATE_DIR': str(state)})
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn('outside the project', result.stderr)
                self.assertFalse(state.exists())
        existing = self.project / 'existing'; existing.mkdir(mode=0o700)
        evidence = existing / 'keep'; evidence.write_text('private evidence')
        result = self.run_cli(self.project, '5s', 'fixture', '--project-root', str(self.project),
                              env={**self.env, 'OC_RUN_STATE_DIR': str(existing)})
        self.assertEqual(result.returncode, 2)
        self.assertEqual(evidence.read_text(), 'private evidence')
        invalid = self.run_cli(self.project, '5s', 'fixture', '--project-root', str(self.nested))
        self.assertEqual(invalid.returncode, 2)
        self.assertIn('containing', invalid.stderr)

    def test_startup_log_above_one_mib_is_read_incrementally(self):
        path = self.base / 'server.log'
        path.write_bytes(b'x' * (2 * 1024 * 1024) + b'\nserver listening on http://127.0.0.1:12345\n')
        ticks = []
        def tick():
            ticks.append(1)
            with path.open('ab') as handle:
                handle.write(b'server password fixture-only\n')
        api = oc.NativeServer()
        with mock.patch.object(oc, 'read', side_effect=AssertionError('whole-log read')), \
                mock.patch.object(oc.time, 'sleep'):
            api.connect(path, mock.Mock(poll=lambda: None), tick)
        self.assertEqual(api.url, 'http://127.0.0.1:12345')
        self.assertEqual(api.password, 'fixture-only')
        self.assertEqual(len(ticks), 1)
        link = self.base / 'server-link'; link.symlink_to(path)
        with self.assertRaises(OSError):
            oc.NativeServer().connect(link, mock.Mock(poll=lambda: None), lambda: None)

    def test_recovery_orders_invocations_numerically(self):
        for number in (9999, 10000):
            (self.base / f'{number:04d}-work.jsonl').write_text(json.dumps({
                'type': 'text', 'sessionID': f'ses_{number}', 'part': {'text': str(number)}}) + '\n')
        state = {'invocations': 0, 'status': 'incomplete', 'incidents': []}
        oc.recover(self.base, state)
        self.assertEqual(state['invocations'], 10000)
        self.assertEqual(state['session'], 'ses_10000')
        self.assertEqual(state['last_work'], '10000')
