import tempfile
import unittest
from pathlib import Path
from production_common import ROOT,load_config,rows
from materialize_worktrees import lsf

class EnvironmentProfileTests(unittest.TestCase):
 def test_aplus_profile_renders_into_lsf(self):
  cfg=load_config(ROOT/'config/production.toml')
  self.assertEqual(cfg['runtime']['python_bin'],'/share/home/yiy/.conda/envs/ulvz-specfem/bin/python3')
  self.assertEqual(cfg['environment']['modules'],['hdf5/1.14.3_oneapi2023'])
  with tempfile.TemporaryDirectory() as tmp:
   lsf(cfg,rows(ROOT/'production_run_manifest.csv')[0],Path(tmp),())
   text=(Path(tmp)/'mesher_lsf.bash').read_text()
   self.assertIn('source "/share/apps/intel/oneapi_2023.1.0/setvars.sh"',text)
   self.assertIn('module load hdf5/1.14.3_oneapi2023',text)
   self.assertIn('mpirun -np',text)

if __name__=='__main__':unittest.main()
