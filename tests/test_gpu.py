import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import textwrap
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'oc-run'


def module():
    loader = importlib.machinery.SourceFileLoader('oc_run_under_test', str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class GPUHandoffTests(unittest.TestCase):
    def test_duration_and_requires_explicit_ownership(self):
        m = module()
        self.assertEqual(m.duration('15m'), 900)
        with self.assertRaises(Exception):
            m.duration('0h')
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'lifecycle.json'
            p.write_text(json.dumps({'stop': ['true'], 'start': ['true']}))
            with self.assertRaisesRegex(ValueError, 'exclusive'):
                m.read_lifecycle(p)

    def test_register_without_controller_fails(self):
        p = subprocess.run([sys.executable, str(SCRIPT), 'train', '--', 'python', 'train.py'],
                           capture_output=True, env={k:v for k,v in os.environ.items() if not k.startswith('OC_RUN_')})
        self.assertNotEqual(p.returncode, 0)

    def test_same_session_handoff_and_deadline(self):
        with tempfile.TemporaryDirectory() as td:
            t = Path(td)
            (t / 'server.py').write_text(textwrap.dedent('''
                from http.server import HTTPServer, BaseHTTPRequestHandler
                import sys
                class Handler(BaseHTTPRequestHandler):
                    def do_GET(self):
                        self.send_response(200 if self.path in ('/health','/v1/models') else 404)
                        self.end_headers()
                        if self.path == '/v1/models':
                            self.wfile.write(b'{"data":[{"id":"fake-sage"}]}')
                        else: self.wfile.write(b'{}')
                    def log_message(self, *args): pass
                HTTPServer(('127.0.0.1', int(sys.argv[1])), Handler).serve_forever()
            '''))
            (t / 'lifecycle.py').write_text(textwrap.dedent('''
                import os, signal, subprocess, sys, time
                from pathlib import Path
                root=Path(sys.argv[2]); pidfile=root/'server.pid'
                if sys.argv[1]=='start':
                    p=subprocess.Popen([sys.executable, str(root/'server.py'), sys.argv[3]],
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, start_new_session=True)
                    pidfile.write_text(str(p.pid))
                else:
                    os.kill(int(pidfile.read_text()), signal.SIGTERM)
            '''))
            (t / 'train.py').write_text(textwrap.dedent('''
                import os, sys, time, urllib.request
                try:
                    urllib.request.urlopen(os.environ['TEST_HEALTH'], timeout=.1)
                except OSError:
                    print('training: server offline')
                else:
                    sys.exit('training: server unexpectedly online')
                time.sleep(.25)
                print('training complete')
            '''))
            (t / 'fake-opencode').write_text(textwrap.dedent('''
                #!/usr/bin/env python3
                import json, os, subprocess, sys
                from pathlib import Path
                prompt=sys.stdin.read()
                path=Path(os.environ['TEST_CALLS']); old=json.loads(path.read_text()) if path.exists() else []
                sid=sys.argv[sys.argv.index('--session')+1]
                old.append({'sid':sid, 'prompt':prompt})
                path.write_text(json.dumps(old))
                if len(old)==1:
                    result=subprocess.run([sys.executable, os.environ['TEST_SCRIPT'], 'train', '--',
                                           sys.executable, str(Path.cwd()/'train.py')],
                                           env=os.environ.copy(), capture_output=True)
                    assert result.returncode==0, result.stderr
                print(json.dumps({'type':'step_start','sessionID':sid}))
            '''))
            (t / 'fake-opencode').write_text((t / 'fake-opencode').read_text().lstrip())
            (t / 'fake-opencode').chmod(0o755)
            s=socket.socket(); s.bind(('127.0.0.1',0)); port=s.getsockname()[1]; s.close()
            c=json.dumps({'exclusive':True,'model_id':'fake-sage','stop':[sys.executable,str(t/'lifecycle.py'),'stop',str(t)],
                          'start':[sys.executable,str(t/'lifecycle.py'),'start',str(t),str(port)],
                          'health':f'http://127.0.0.1:{port}/health'})
            (t / 'lifecycle.json').write_text(c)
            subprocess.run([sys.executable,str(t/'lifecycle.py'),'start',str(t),str(port)],check=True)
            try:
                env=os.environ.copy()
                env.update(OC_RUN_STATE_DIR=str(t/'logs'), OC_NATIVE_BIN=str(t/'fake-opencode'),
                           TEST_CALLS=str(t/'calls.json'), TEST_SCRIPT=str(SCRIPT),
                           TEST_HEALTH=f'http://127.0.0.1:{port}/health')
                import time
                time.sleep(.1)
                result=subprocess.run([sys.executable,str(SCRIPT),'--gpu-lifecycle',str(t/'lifecycle.json'),
                                       '0.2s','Original prompt'], cwd=t, env=env, capture_output=True, text=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
                calls=json.loads((t/'calls.json').read_text())
                self.assertEqual(len(calls),1)  # training outlasted budget; no second turn
                self.assertIn('Original prompt',calls[0]['prompt'])
                log=next((t/'logs').iterdir())
                self.assertIn('training complete',(log/'training.log').read_text())
                self.assertTrue((log/'training-result.json').is_file())
                self.assertTrue(module().health(f'http://127.0.0.1:{port}/health'))
            finally:
                pidfile=t/'server.pid'
                if pidfile.exists():
                    try: os.kill(int(pidfile.read_text()), 15)
                    except ProcessLookupError: pass

    def test_continues_exact_session_without_gpu_handoff(self):
        with tempfile.TemporaryDirectory() as td:
            t = Path(td)
            executable = t / 'fake'
            executable.write_text('#!/usr/bin/env python3\nimport json,os,sys,time\n'
                                  'from pathlib import Path\n'
                                  'p=Path(os.environ["TEST_CALLS"])\n'
                                  'calls=json.loads(p.read_text()) if p.exists() else []\n'
                                  'calls.append([sys.argv[sys.argv.index("--session")+1], sys.stdin.read()])\n'
                                  'p.write_text(json.dumps(calls))\n'
                                  'time.sleep(.15)\n'
                                  'print(json.dumps({"type":"step_start"}))\n')
            executable.chmod(0o755)
            env = os.environ.copy()
            env.update(OC_RUN_STATE_DIR=str(t/'state'), OC_NATIVE_BIN=str(executable),
                       TEST_CALLS=str(t/'calls.json'))
            p = subprocess.run([sys.executable,str(SCRIPT),'1.0s','This is my initial prompt'],
                               cwd=t,env=env,text=True,capture_output=True,timeout=8)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            calls=json.loads((t/'calls.json').read_text())
            self.assertGreaterEqual(len(calls),2)
            self.assertEqual(len({c[0] for c in calls}),1)
            self.assertIn('This is my initial prompt',calls[0][1])
            self.assertIn('Review the original task',calls[1][1])

    def test_registration_is_one_shot(self):
        with tempfile.TemporaryDirectory() as td:
            env=os.environ.copy(); env.update(OC_RUN_HANDOFF_FILE=td+'/request.json',OC_RUN_WORKSPACE=td)
            cmd=[sys.executable,str(SCRIPT),'train','--',sys.executable,'train.py']
            self.assertEqual(subprocess.run(cmd, env=env, capture_output=True).returncode,0)
            self.assertNotEqual(subprocess.run(cmd, env=env,capture_output=True).returncode,0)
            self.assertEqual(json.loads(Path(td+'/request.json').read_text())['argv'][1],'train.py')


if __name__=='__main__': unittest.main()
