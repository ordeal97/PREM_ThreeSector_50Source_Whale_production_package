#!/usr/bin/env python3
"""Verify the frozen Whale runtime environment without invoking SPECFEM or LSF."""
from __future__ import annotations
import json,shlex,subprocess,sys
from pathlib import Path
from production_common import load_config

def main():
 p=__import__('argparse').ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args();cfg=load_config(a.config);env=cfg['environment']
 setup='\n'.join(['set -e','module purge',f'if [[ -z "${{I_MPI_ROOT:-}}" ]] || ! command -v mpiifort >/dev/null 2>&1; then source {shlex.quote(env["oneapi_setup"])}; fi',*[f'module load {shlex.quote(x)}' for x in env['modules']],f'command -v {shlex.quote(env["mpi_launcher"])}','command -v mpiifort','command -v mpiicc'])
 shell=subprocess.run(['bash','-lc',setup],text=True,capture_output=True)
 try:
  python=subprocess.run([cfg['runtime']['python_bin'],'-c','import sys,h5py,numpy; assert sys.version_info >= (3,11); print(sys.version.split()[0]); print(h5py.__version__); print(numpy.__version__)'],text=True,capture_output=True)
  python_exit=python.returncode;python_stdout=python.stdout;python_stderr=python.stderr
 except OSError as exc:
  python_exit=127;python_stdout='';python_stderr=str(exc)
 report={'status':'PASS' if shell.returncode==0 and python_exit==0 else 'FAIL','python_bin':cfg['runtime']['python_bin'],'environment':env,'shell_exit':shell.returncode,'python_exit':python_exit,'shell_stdout':shell.stdout,'shell_stderr':shell.stderr,'python_stdout':python_stdout,'python_stderr':python_stderr,'bsub_called':False,'mesher_called':False,'solver_called':False}
 print(json.dumps(report,indent=2));raise SystemExit(report['status']!='PASS')
if __name__=='__main__':main()
