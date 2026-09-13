import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import deployment_check
from production_common import ROOT,environment_setup,load_config,rows
from materialize_worktrees import lsf

class EnvironmentProfileTests(unittest.TestCase):
 def command(self,path):
  path.write_text('#!/usr/bin/env bash\nexit 0\n');path.chmod(0o755)
 def shell(self,environment,path):
  values=dict(os.environ,PATH=path)
  values.update({key:value for key,value in environment.items() if isinstance(value,str)})
  return subprocess.run(['/bin/bash','--noprofile','--norc','-c','module() { :; }\nset -euo pipefail\n'+environment_setup(environment)],env=values,text=True,capture_output=True)
 def test_aplus_profile_renders_idempotent_setup_into_all_lsf(self):
  cfg=load_config(ROOT/'config/production.toml')
  with tempfile.TemporaryDirectory() as tmp:
   lsf(cfg,rows(ROOT/'production_run_manifest.csv')[0],Path(tmp),())
   for name in ('submit_lsf.bash','mesher_lsf.bash','solver_lsf.bash'):
    text=(Path(tmp)/name).read_text()
    self.assertIn('module purge\nif ! command -v ifort',text)
    self.assertIn('source /share/apps/intel/oneapi_2023.1.0/setvars.sh --force',text)
    self.assertIn('module load hdf5/1.14.3_oneapi2023',text)
    self.assertIn('required command missing: ifort',text)
    self.assertIn('required command missing: mpiifort',text)
    if name == 'submit_lsf.bash':
     self.assertIn('PACKAGE_ROOT="$(cd "$WORKPATH/../.." && pwd)"',text)
     self.assertIn('"$SMOKE_TOOL" --source-dir "$WORKPATH"',text)
     self.assertIn('"$LINKAGE_TOOL" --binary "$WORKPATH/bin/xspecfem3D" --require-asdf',text)
    if name != 'submit_lsf.bash':self.assertIn('mpirun -np',text)
 def test_initialized_environment_skips_setvars(self):
  root=Path(tempfile.mkdtemp());ready=root/'ready';ready.mkdir();marker=root/'marker';setup=root/'setvars.sh'
  for name in ('ifort','mpiifort','mpirun'):self.command(ready/name)
  setup.write_text('echo sourced >> "'+str(marker)+'"\nreturn 3\n')
  result=self.shell({'oneapi_setup':str(setup),'modules':['hdf5'],'mpi_launcher':'mpirun'},str(ready)+':/usr/bin:/bin')
  self.assertEqual(result.returncode,0,result.stderr);self.assertFalse(marker.exists())
 def test_missing_commands_force_setvars_even_with_marker(self):
  root=Path(tempfile.mkdtemp());initial=root/'initial';ready=root/'ready';initial.mkdir();ready.mkdir();marker=root/'marker';setup=root/'setvars.sh'
  for name in ('mpiifort','mpirun'):self.command(initial/name)
  self.command(ready/'ifort')
  setup.write_text('[[ "$1" == --force ]] || return 3\necho "$1" >> "'+str(marker)+'"\nexport PATH="'+str(ready)+':$PATH"\n')
  environment={'oneapi_setup':str(setup),'modules':['hdf5'],'mpi_launcher':'mpirun','ONEAPI_ROOT':'already_initialized'}
  result=self.shell(environment,str(initial)+':/usr/bin:/bin')
  self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(marker.read_text().strip(),'--force')
 def test_deployment_check_uses_idempotent_setup(self):
  root=Path(tempfile.mkdtemp());cfg={'environment':{'oneapi_setup':'/setvars.sh','modules':['hdf5'],'mpi_launcher':'mpirun'},'runtime':{'python_bin':'python3'}};calls=[]
  def fake_run(*args,**kwargs):
   calls.append(args[0]);return type('Result',(),{'returncode':0,'stdout':'ok','stderr':''})()
  with patch('deployment_check.load_config',return_value=cfg),patch('deployment_check.subprocess.run',side_effect=fake_run),patch.object(sys,'argv',['deployment_check.py','--config',str(root/'config.toml')]):
   with self.assertRaises(SystemExit) as exit_code:deployment_check.main()
  self.assertEqual(exit_code.exception.code,False);self.assertIn('if ! command -v ifort',calls[0][2]);self.assertIn('source /setvars.sh --force',calls[0][2])

if __name__=='__main__':unittest.main()
