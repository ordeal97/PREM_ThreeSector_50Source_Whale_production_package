#!/usr/bin/env python3
"""Render the 100 portable LSF bundles without materializing source worktrees."""
from __future__ import annotations
import argparse,shutil
from pathlib import Path
from materialize_worktrees import default_modules,lsf
from production_common import load_config,rows
def main():
 p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);a=p.parse_args();cfg=load_config(a.config);root=cfg['_root']/'rendered_lsf'
 for row in rows(cfg['paths']['manifest']):
  target=root/row['run_id'];target.mkdir(parents=True,exist_ok=True);lsf(cfg,row,target,default_modules(cfg))
 print('rendered',len(rows(cfg['paths']['manifest'])),'runs to',root)
if __name__=='__main__':main()
