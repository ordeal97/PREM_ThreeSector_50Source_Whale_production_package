#!/usr/bin/env python3
"""Safely remove only a QC-PASS run's declared scratch directory."""
from __future__ import annotations
import argparse,shutil
from pathlib import Path
from production_common import load_config,run_row,runtime,rows
def main():
 p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--run-id',required=True);p.add_argument('--execute',action='store_true');a=p.parse_args();cfg=load_config(a.config);row=run_row(cfg,a.run_id)
 if not row:raise SystemExit('unknown run_id')
 status=next((x for x in rows(runtime(cfg)['status']) if x['run_id']==a.run_id),None)
 if not status or status['state']!='DONE' or status['output_qc']!='PASS':raise SystemExit('cleanup requires DONE + output_qc PASS')
 root=cfg['paths']['scratch_root'].resolve(strict=False);target=(root/a.run_id).resolve(strict=False);declared=Path(row['scratch_database_path']).resolve(strict=False)
 if target.parent!=root or declared!=target/'DATABASES_MPI':raise SystemExit('unsafe scratch target')
 print(('REMOVE ' if a.execute else 'DRY-RUN remove ')+str(target))
 if a.execute and target.exists():shutil.rmtree(target)
if __name__=='__main__':main()
