import unittest
from token_master.core import *
class TestGuard(unittest.TestCase):
 def test_missing_is_noop(self): self.assertEqual(evaluate(task_id='t',run_id='r',provider='p',observed_tokens=None,estimate=None,elapsed_seconds=None),[])
 def test_runaway_and_dedup(self):
  e=Estimate('t','r','p','m',100,1,200,.5)
  a=evaluate(task_id='t',run_id='r',provider='p',observed_tokens=100000,estimate=e,elapsed_seconds=1)
  self.assertEqual({x.rule for x in a},{'absolute-threshold','estimate-multiple','burn-rate'})
  self.assertEqual(evaluate(task_id='t',run_id='r',provider='p',observed_tokens=100000,estimate=e,elapsed_seconds=1,alerted={x.dedupe_key for x in a}),[])
 def test_mismatch_and_reset(self):
  e=Estimate('t','r','other','m',1,1,2,.9)
  a=evaluate(task_id='t',run_id='r',provider='p',observed_tokens=2,estimate=e,elapsed_seconds=100,previous=Snapshot('p',100,100),current=Snapshot('p',200,50))
  self.assertIn('provider-mismatch',{x.rule for x in a}); self.assertIn('counter-reset',{x.rule for x in a})
 def test_concurrent_runs_dedupe_keys_differ(self):
  a=evaluate(task_id='t',run_id='r1',provider='p',observed_tokens=100000,estimate=None,elapsed_seconds=None)
  b=evaluate(task_id='t',run_id='r2',provider='p',observed_tokens=100000,estimate=None,elapsed_seconds=None)
  self.assertNotEqual(a[0].dedupe_key,b[0].dedupe_key)
if __name__=='__main__': unittest.main()
