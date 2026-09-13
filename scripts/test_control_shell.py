import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from materialize_worktrees import lsf


class ControlShellTests(unittest.TestCase):
 def test_rendered_control_uses_atomic_metadata_and_lsf_history_fallback(self):
  root=Path(tempfile.mkdtemp());bindir=root/'bin';bindir.mkdir();marker=root/'setvars-called';setup=root/'setvars.sh';setup.write_text('echo sourced >> "'+str(marker)+'"\nreturn 3\n')
  scripts=root/'scripts';scripts.mkdir()
  for name in ('asdf_smoke.py','linkage_audit.py'):
   path=scripts/name;path.write_text('#!/usr/bin/env python3\n');path.chmod(0o755)
  for name,body in {'module':'exit 0','ifort':'exit 0','mpiifort':'exit 0','mpirun':'exit 0','make':'exit 0','bjobs':'exit 0','bhist':'echo "Completed <done>"','bsub':'echo "Job <201> is submitted"'}.items():
   path=bindir/name;path.write_text('#!/usr/bin/env bash\n'+body+'\n');path.chmod(0o755)
  scratch=root/'scratch'/'A'/'DATABASES_MPI';scratch.mkdir(parents=True)
  cfg={'lsf':{'mpi_ranks':384,'ptile':64,'mpi_queue':'mpi','control_queue':'serial','control_ranks':1,'control_hosts':1,'per_run_wait_seconds':0},'build':{'make_jobs':1,'mesher_target':'meshfem3D','solver_target':'specfem3D'},'environment':{'oneapi_setup':str(setup),'modules':['fake'],'mpi_launcher':'mpirun'},'runtime':{'python_bin':'python3'},'_root':root}
  run=root/'worktrees'/'A';run.mkdir(parents=True)
  row={'run_id':'A','scratch_database_path':str(scratch)};lsf(cfg,row,run)
  text=(run/'submit_lsf.bash').read_text()
  self.assertIn('#BSUB -q serial',text);self.assertIn('#BSUB -L /bin/bash',text);self.assertIn('mv "$tmp" run_job_ids.env',text);self.assertIn('bhist -l',text)
  bash_env=root/'bash_env';bash_env.write_text('module() { :; }\n')
  env=dict(os.environ,PATH=str(bindir)+':'+os.environ['PATH'],LSB_JOBID='101',BASH_ENV=str(bash_env))
  subprocess.run(['bash',str(run/'submit_lsf.bash')],cwd=run,env=env,check=True)
  (run/'bin').mkdir(exist_ok=True)
  for name in ('xmeshfem3D','xspecfem3D'):
   path=run/'bin'/name;path.write_text('#!/usr/bin/env bash\nexit 0\n');path.chmod(0o755)
  subprocess.run(['bash',str(run/'mesher_lsf.bash')],cwd=run,env=env,check=True)
  subprocess.run(['bash',str(run/'solver_lsf.bash')],cwd=run,env=env,check=True)
  self.assertFalse(marker.exists())
  metadata=(run/'run_job_ids.env').read_text()
  self.assertIn('control_job_id=101',metadata);self.assertIn('mesher_job_id=201',metadata);self.assertIn('solver_job_id=201',metadata)
  self.assertIn('mesher_submission_state=CONFIRMED',metadata);self.assertIn('solver_submission_state=CONFIRMED',metadata)


if __name__=='__main__':unittest.main()
