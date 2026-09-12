import unittest
from production_controller import stage2_ready
class ControllerLogic(unittest.TestCase):
 def setUp(self):
  self.cfg={'staging':{'stage1':'B0','stage2':'M3'}};self.manifest=[{'run_id':'A','stage':'B0'},{'run_id':'B','stage':'B0'},{'run_id':'C','stage':'M3'}]
 def test_stage2_is_locked_until_all_baselines_pass(self):
  state={'A':{'state':'DONE','output_qc':'PASS'},'B':{'state':'DONE','output_qc':'FAIL'}}
  self.assertFalse(stage2_ready(self.manifest,state,self.cfg))
 def test_stage2_unlocks_only_on_done_and_pass(self):
  state={'A':{'state':'DONE','output_qc':'PASS'},'B':{'state':'DONE','output_qc':'PASS'}}
  self.assertTrue(stage2_ready(self.manifest,state,self.cfg))
if __name__=='__main__':unittest.main()
