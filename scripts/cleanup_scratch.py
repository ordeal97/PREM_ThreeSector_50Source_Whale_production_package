#!/usr/bin/env python3
"""Safely remove only a terminal run's declared scratch directory."""
from __future__ import annotations
import argparse,fcntl
from pathlib import Path
from production_common import load_config,run_row,runtime
from production_controller import all_terminal,job_states,process_failure,process_success_cleanup,state
def main():
 p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--run-id',required=True);p.add_argument('--execute',action='store_true');a=p.parse_args();cfg=load_config(a.config);row=run_row(cfg,a.run_id)
 if not row:raise SystemExit('unknown run_id')
 status=state(cfg).get(a.run_id)
 if not status:raise SystemExit('status missing')
 if status['state'] not in {'DONE','EXIT','QC_FAIL'} or (status['state']=='DONE' and status['output_qc']!='PASS'):raise SystemExit('cleanup requires DONE + output_qc PASS, EXIT, or QC_FAIL')
 root=cfg['paths']['scratch_root'].resolve(strict=False);target=(root/a.run_id).resolve(strict=False);declared=Path(row['scratch_database_path']).resolve(strict=False)
 if target.parent!=root or declared!=target/'DATABASES_MPI':raise SystemExit('unsafe scratch target')
 states=job_states(cfg['paths']['run_root']/a.run_id,status)
 if not all_terminal(states):raise SystemExit('cleanup requires all known control/mesher/solver jobs terminal')
 print(('REMOVE ' if a.execute else 'DRY-RUN remove ')+str(target))
 if not a.execute:return
 lock=runtime(cfg)['lock'];lock.parent.mkdir(parents=True,exist_ok=True)
 with lock.open('a+') as f:
  try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise SystemExit('another controller holds lock')
  if status['state'] in {'EXIT','QC_FAIL'}:
   if not process_failure(cfg,row):raise SystemExit('cleanup failed or awaits terminal submission identity')
  elif not process_success_cleanup(cfg,row):raise SystemExit('cleanup failed')
if __name__=='__main__':main()
