"""Process-boundary fault tests and reversible integration; no live account."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_backend import NOW, populate, Store, Engine, FakeApi, Synchronizer, stamp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from integrate import integrate, ID, START

CRASH = r'''
import os,sys,json
from pathlib import Path
from test_backend import Store, Engine, FakeApi, Synchronizer, NOW
path, point = Path(sys.argv[1]), sys.argv[2]
s = Store(path)
e = Engine(s, clock=lambda:NOW)
operation, boundary = point.rsplit(':',1)
if operation in ('draft','answer','correct') and boundary=='before':
    original=s.save_session
    def save(value):
        original(value)
        os._exit(77)
    s.save_session=save
if operation=='advance' and boundary=='before':
    original=s.execute
    def execute(sql,args=()):
        value=original(sql,args)
        if sql.startswith('INSERT OR IGNORE INTO outbox'):
            os._exit(77)
        return value
    s.execute=execute
if operation in ('draft','answer','correct','advance'):
    args={'text':'partial'} if operation=='draft' else {'text':'wrong'} if operation=='answer' else {}
    e.command('crash-command',operation,args)
    os._exit(77)
api=FakeApi(s)
sync=Synchronizer(e,api,path.parent/'media')
if operation=='send':
    if boundary=='before':
        original=api.request
        def request(path,method='GET',data=None,etag=None):
            if method!='GET':os._exit(77)
            return original(path,method,data,etag)
        api.request=request
    else:
        sync.apply_result=lambda *args: os._exit(77)
else:
    original=sync.state
    def state(oid,value,message):
        original(oid,value,message)
        if value=='confirmed':os._exit(77)
    if boundary=='before':sync.state=state
sync.flush()
os._exit(77)
'''


class ProcessRecoveryTests(unittest.TestCase):
    def test_crash_at_each_durable_boundary(self):
        for operation in ('draft','answer','correct','advance','send','confirm'):
            for boundary in ('before','after'):
                with self.subTest(operation=operation,boundary=boundary), tempfile.TemporaryDirectory() as temporary:
                    path=Path(temporary)/'db.sqlite3'
                    store=Store(path);populate(store,NOW)
                    # Exactly one radical: a completed meaning is a complete subject.
                    for a in store.all('assignment'):
                        if a['data']['subject_id']!=1:
                            a['data']['available_at']=stamp(NOW+86400);store.put(a)
                    engine=Engine(store,clock=lambda:NOW)
                    engine.start('reviews',1)
                    if operation=='correct':engine.answer('wrong')
                    if operation in ('advance','send','confirm'):
                        engine.answer(engine.session_view()['subject']['meanings'][0])
                    if operation in ('send','confirm'):engine.advance()
                    store.close()
                    env={**os.environ,'PYTHONPATH':str(ROOT/'backend')+os.pathsep+str(ROOT/'tests')}
                    result=subprocess.run([sys.executable,'-B','-c',CRASH,str(path),operation+':'+boundary],env=env,capture_output=True,timeout=8)
                    self.assertEqual(77,result.returncode,result.stderr.decode())
                    store=Store(path);engine=Engine(store,clock=lambda:NOW)
                    view=engine.session_view();rows=store.rows('SELECT state FROM outbox')
                    if operation=='draft':self.assertEqual('partial' if boundary=='after' else '',view['draft'])
                    elif operation=='answer':self.assertEqual('feedback' if boundary=='after' else 'question',view['phase'])
                    elif operation=='correct':self.assertEqual(0 if boundary=='after' else 1,view['errors'])
                    elif operation=='advance':
                        self.assertEqual('complete' if boundary=='after' else 'feedback',view['phase'])
                        self.assertEqual(1 if boundary=='after' else 0,len(rows))
                    else:
                        self.assertEqual('confirmed' if operation=='confirm' and boundary=='after' else 'uncertain',rows[0][0])
                        api=FakeApi(store);sync=Synchronizer(engine,api,Path(temporary)/'media')
                        sync.flush()
                        self.assertEqual([],api.mutations,'Restart must never replay an uncertain submission')
                    store.close()

    def test_protocol_rejects_malformed_input_and_continues(self):
        with tempfile.TemporaryDirectory() as temporary:
            Path(temporary,'mode.json').write_text('{"mode":"demo"}')
            requests=['[]','null','{"v":3,"id":"bad"}','not-json',json.dumps({'v':1,'id':'last','method':'snapshot'})]
            result=subprocess.run([sys.executable,'-B',str(ROOT/'backend/worker.py'),'--state-dir',temporary],input='\n'.join(requests)+'\n',text=True,capture_output=True,timeout=8)
            self.assertEqual(0,result.returncode,result.stderr)
            messages=[json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(4,sum(m.get('ok') is False for m in messages))
            last=next(m for m in messages if m.get('id')=='last')
            self.assertTrue(last['ok']);self.assertTrue(last['data']['demo'])


class IntegrationTests(unittest.TestCase):
    def test_install_remove_preserves_original_exactly(self):
        with tempfile.TemporaryDirectory() as temporary:
            home=Path(temporary);bindings=home/'.config/hypr/bindings.lua'
            bindings.parent.mkdir(parents=True)
            original='-- Personal settings\no.bind("SUPER + B", "Browser", "firefox")\n'
            bindings.write_text(original)
            integrate(home,ROOT,runtime=False)
            integrate(home,ROOT,runtime=False)
            self.assertEqual(1,bindings.read_text().count(START))
            integrate(home,ROOT,remove=True,runtime=False)
            self.assertEqual(original,bindings.read_text())
            self.assertEqual([],list((home/'.local/share/applications').glob('*.desktop')))

    def test_conflicts_and_user_edits_survive(self):
        with tempfile.TemporaryDirectory() as temporary:
            home=Path(temporary);bindings=home/'.config/hypr/bindings.lua'
            bindings.parent.mkdir(parents=True)
            original='o.bind("SUPER + ALT + W", "My editor", "editor")\n'
            bindings.write_text(original)
            integrate(home,ROOT,runtime=False)
            self.assertNotIn('wanikani resume',bindings.read_text())
            edited='o.bind("SUPER + K", "Personal", "personal")\n'
            bindings.write_text(bindings.read_text()+edited)
            launcher=home/'.local/share/applications'/f'{ID}.lookup.desktop'
            launcher.write_text('user-edited')
            integrate(home,ROOT,remove=True,runtime=False)
            self.assertIn(original,bindings.read_text());self.assertIn(edited,bindings.read_text())
            self.assertEqual('user-edited',launcher.read_text())
