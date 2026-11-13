#!/usr/bin/env python3
"""Deterministic CLI fixture. No network or model calls."""
import json
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

scenario = os.environ.get("FAKE_SCENARIO", "success")
if len(sys.argv) > 1 and sys.argv[1] == 'serve':
    inbox, attempts = {}, 0
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            data = {'id': 'ses_fixture', 'location': {'directory': str(Path.cwd())}, 'agent': 'sage-research'}
            if self.path == '/api/session/active':
                data = {'ses_fixture': {'type': 'running'}} if scenario == 'active_recovery' else {}
            elif self.path.startswith('/api/session?'):
                data = [{'id': 'ses_child'}] if scenario == 'child_recovery' else []
            elif self.path.startswith('/api/shell?'):
                data = [{'id': 'sh_live', 'status': 'running'}] if scenario == 'shell_recovery' else []
            elif self.path.endswith('/inbox'):
                data = list(inbox.values())
                if scenario == 'stale_control':
                    run = next(p for p in Path(os.environ['OC_RUN_STATE_DIR']).iterdir() if p.is_dir())
                    prefix = 'msg_ocrun_' + hashlib.sha256(os.fsencode(run)).hexdigest()[:12] + '_'
                    data = [{'id': prefix + 'old'}, {'id': 'msg_unrelated'}]
            elif '/message/' in self.path:
                self.send_response(404); self.end_headers(); return
            self.send_response(200); self.end_headers()
            self.wfile.write(json.dumps({'data': data}).encode())
        def do_DELETE(self):
            with Path('cancelled.txt').open('a') as out:
                out.write(self.path + '\n')
            self.send_response(204); self.end_headers()
        def do_POST(self):
            global attempts
            attempts += 1
            message = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            with Path('notifications.jsonl').open('a') as out:
                out.write(json.dumps(message) + '\n')
            if scenario in ('supervisor_unavailable', 'stop_offline') or (scenario == 'stop_recovery' and attempts == 1):
                self.send_response(503); self.end_headers(); return
            if scenario == 'stop_rejected':
                self.send_response(403); self.end_headers(); return
            inbox[message['id']] = message
            if scenario == 'stop_unknown_ack':
                self.close_connection = True
                return
            self.send_response(200); self.end_headers()
            self.wfile.write(json.dumps({'data': {'id': message['id']}}).encode())
    server = HTTPServer(('127.0.0.1', 0), Handler)
    print(f'server listening on http://127.0.0.1:{server.server_port}', flush=True)
    print('server password fixture-only', flush=True)
    server.serve_forever()

prompt = sys.stdin.read()
previous = Path('prompts.txt').read_text().count('\n---\n') if Path('prompts.txt').exists() else 0
Path('arguments.json').write_text(json.dumps(sys.argv[1:]))
session = "ses_fixture"
if "--session" in sys.argv:
    assert sys.argv[sys.argv.index("--session") + 1] == session
Path("prompts.txt").open("a").write(prompt + "\n---\n")
call_index = 0

def emit(kind, part=None, **extra):
    print(json.dumps({"type": kind, "sessionID": session, "part": part or {}, **extra}), flush=True)


def tool(name, inputs, output, bad=False):
    global call_index
    call_index += 1
    emit("tool_use", {"id": "call_" + str(call_index), "tool": name, "state": {
        "status": "error" if bad else "completed", "input": inputs,
        "output": output, "error": output if bad else None,
        "metadata": {"exit": 1 if bad else 0}}})


emit("step_start")
recovery = scenario in ('oom', 'oom_repeat', 'unsafe_oom', 'transport_recovery', 'auth_failure',
                        'active_recovery', 'child_recovery', 'shell_recovery')
if recovery:
    if previous == 0:
        Path('experiment.txt').write_text('unique completed result\n')
        tool('shell', {'command': 'one experiment'}, 'unique completed result')
    if previous == 0 or scenario == 'oom_repeat':
        if scenario == 'unsafe_oom':
            emit('tool_use', {'id': 'call_timeout', 'tool': 'shell', 'state': {
                'status': 'completed', 'input': {'command': 'uncertain experiment'},
                'output': 'Command timed out', 'metadata': {'metadata': {'timeout': True}}}})
        error = {'type': 'provider.internal', 'message': 'insufficient memory: the request exceeded available GPU memory during prefill. The engine shed its caches and stays up; this request failed.',
                 'status': 200, 'response': {'body': '{"error":{"code":"insufficient_memory"}}'}}
        if scenario == 'transport_recovery':
            error = {'type': 'provider.transport', 'message': 'Connection lost while reading the response'}
        if scenario == 'auth_failure':
            error = {'type': 'provider.auth', 'message': 'Unauthorised', 'status': 401}
        emit('error', error=error)
        sys.exit(1)
if scenario == 'bad_events':
    emit('tool_use', {'state': {'metadata': 'unexpected'}})
    emit('tool_use', {'state': ['unexpected']})
    emit('text', {'text': None})
if scenario == 'bad_event_then_error':
    emit('error', ['unexpected part'], error={'message': 'real fatal error'})
    sys.exit(0)
if scenario in ("stall", "crash", "stop_offline"):
    emit('tool_use', {'id': 'call_external', 'tool': 'shell', 'state': {
        'status': 'running', 'input': {'command': 'external non-idempotent action'}}})
    child = subprocess.Popen([sys.executable, "-c",
                              "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(120)"])
    Path("child.pid").write_text(str(child.pid))
    if scenario == "crash":
        Path("partial.txt").write_text("Useful output before runner crash\n")
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while True:
        time.sleep(.1)
if scenario in ('long', 'soft_stop', 'stop_recovery', 'stop_unknown_ack', 'stop_rejected'):
    Path('action-started').touch()
    time.sleep(3 if scenario.startswith('stop_') else .8)
    Path('action-finished').touch()
if scenario in ('repeat', 'supervisor_unavailable', 'changed', 'progress'):
    for i in range(6):
        tool('shell', {'command': 'bad-command' + (str(i) if scenario == 'changed' else '')}, 'Tool unavailable', True)
        if scenario == 'progress':
            tool('read', {'path': 'changing.txt'}, str(i))
        time.sleep(.12)
if scenario == 'tool_failure':
    tool('shell', {'command': 'bad-command'}, 'Tool unavailable', True)
if scenario == "transport":
    emit("error", error={"message": "socket closed"})
    sys.exit(0)
if scenario == "nonzero":
    emit("text", {"text": "Useful partial work survived."})
    sys.exit(7)
if scenario != 'premature':
    Path("answer.txt").write_text("12\n")
    tool("read", {"path": str(Path("answer.txt").absolute())}, "12")
if scenario == 'milestones':
    for i in range(3):
        emit('text', {'text': f'Milestone {i} complete; continuing without review.'})
        tool('read', {'path': 'facts.txt'}, str(i))
if scenario == 'handoff_stall' and previous:
    time.sleep(30)
if scenario == "malformed" or (scenario in ('repair_final', 'repair_invalid', 'handoff_stall') and previous == 0):
    emit('text', {'text': 'cd /research && run-experiment'})
    emit("text", {"text": "Milestone complete; not a valid final result"})
    sys.exit(0)
if scenario == 'repair_invalid':
    emit('text', {'text': 'OC_RUN_RESULT {"decision":"STOP"}'})
    sys.exit(0)
report = {"decision": "STOP", "complete": True, "reason": "Required work checked",
          "summary": "Completed: read/write fixture. Failed: unavailable tool; later read succeeded. Unverified: none in fixture.",
          "evidence": ["read answer.txt: 12"], "next": "none"}
if scenario in ('incomplete', 'repair_final'):
    report['complete'] = False
if scenario == 'no_evidence':
    report['evidence'] = []
emit("text", {"text": 'OC_RUN_RESULT ' + json.dumps(report)})
