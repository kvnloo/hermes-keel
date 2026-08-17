import json, sqlite3, tempfile, time, unittest
from pathlib import Path
from unittest import mock
from privileged_broker import core

NOW=2_000_000_000
class Backend:
 def __init__(self, fail=False, rollback_fail=False): self.calls=[]; self.fail=fail; self.rollback_fail=rollback_fail
 def check_pre(self,r): self.calls.append('pre')
 def mutate(self,r): self.calls.append('mutate')
 def health(self,r): self.calls.append('health'); return {'ok':not self.fail}
 def rollback(self,r): self.calls.append('rollback');

class BrokerTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(); self.root=Path(self.t.name); self.db=self.root/'kanban.db'; self.key=b'k'*32
  self.req=core.make_request('t_9966a8c5',66,'N'*32,NOW)
  db=sqlite3.connect(self.db); db.executescript('create table tasks(id text,status text,completed_at int,body text); create table task_runs(id int,task_id text,status text,ended_at int); create table task_comments(task_id text,body text);')
  db.execute('insert into tasks values(?,?,?,?)',('t_9966a8c5','running',None,core.digest(self.req))); db.execute('insert into task_runs values(?,?,?,?)',(66,'t_9966a8c5','running',None)); db.commit(); db.close()
  self.ap=self.root/'approvals'; self.log=self.root/'ledger'; self.lock=self.root/'lock'
 def tearDown(self): self.t.cleanup()
 def approval(self): return core.approve(self.req,db=self.db,key=self.key,approvals=self.ap,captain_uid=1000,now=NOW)
 def execute(self,backend=None): return core.execute(self.req,db=self.db,key=self.key,approvals=self.ap,ledger=self.log,lock=self.lock,now=NOW,backend=backend or Backend())
 def test_happy_path_consumes_before_mutation(self):
  self.approval(); b=Backend(); out=self.execute(b); self.assertTrue(out['ok']); self.assertEqual(b.calls,['pre','mutate','health']); self.assertEqual(json.loads(self.log.read_text().splitlines()[1])['phase'],'consumed')
 def test_missing_forged_and_modified_approval_fail(self):
  with self.assertRaisesRegex(core.Rejected,'missing-or-ambiguous'): self.execute()
  self.approval(); rows=[json.loads(x) for x in self.ap.read_text().splitlines()]; rows[0]['captain_uid']=0; self.ap.write_text(json.dumps(rows[0])+'\n')
  with self.assertRaisesRegex(core.Rejected,'missing-or-ambiguous'): self.execute()
 def test_packet_change_after_approval_fails(self):
  self.approval(); self.req['expires_at']-=1
  with self.assertRaises(core.Rejected): self.execute()
 def test_replay_fails_and_mutates_once(self):
  self.approval(); self.execute(); b=Backend()
  with self.assertRaisesRegex(core.Rejected,'replay'): self.execute(b)
  self.assertEqual(b.calls,[])
 def test_expiry_wrong_host_action_args_env_rejected(self):
  for field,value in [('target_host','evil'),('action','shell')]:
   r=dict(self.req); r[field]=value
   with self.assertRaises(core.Rejected): core.validate_request(r,now=NOW)
  for extra in ('args','env','command','service'):
   r=dict(self.req); r[extra]='evil'
   with self.assertRaisesRegex(core.Rejected,'bad-schema'): core.validate_request(r,now=NOW)
  with self.assertRaisesRegex(core.Rejected,'expired'): core.validate_request(self.req,now=self.req['expires_at'])
 def test_terminal_task_or_run_fails(self):
  self.approval(); db=sqlite3.connect(self.db); db.execute("update task_runs set status='done',ended_at=?",(NOW,)); db.commit(); db.close()
  with self.assertRaisesRegex(core.Rejected,'inactive'): self.execute()
 def test_health_failure_rolls_back_and_records(self):
  self.approval(); b=Backend(fail=True); out=self.execute(b); self.assertFalse(out['ok']); self.assertTrue(out['rollback_ok']); self.assertEqual(b.calls[-1],'rollback')
 def test_crash_after_consume_blocks_replay(self):
  self.approval(); real=core.append_chain
  def crash(path,key,record):
   real(path,key,record)
   if record.get('phase')=='consumed': raise RuntimeError('crash')
  with mock.patch.object(core,'append_chain',side_effect=crash):
   with self.assertRaises(RuntimeError): self.execute()
  with self.assertRaisesRegex(core.Rejected,'replay'): self.execute()
 def test_symlink_ledgers_fail_closed(self):
  target=self.root/'target'; target.write_text(''); self.ap.symlink_to(target)
  with self.assertRaises(core.Rejected): self.execute()
 def test_malicious_health_output_not_logged(self):
  self.approval()
  class Evil(Backend):
   def health(self,r): return {'ok':False,'output':'SECRET\n$(id)'}
  out=self.execute(Evil()); self.assertNotIn('SECRET',self.log.read_text()); self.assertNotIn('output',out)
 def test_exact_fixed_paths_and_local_listener(self):
  op=core.fixed_operation(); self.assertEqual(op['listen'],'127.0.0.1:11434'); self.assertEqual(op['service'],'ollama.service'); self.assertNotIn('shell',json.dumps(op)); self.assertEqual(op['argv'],[core.NEW_BINARY,'serve'])
if __name__=='__main__': unittest.main()
