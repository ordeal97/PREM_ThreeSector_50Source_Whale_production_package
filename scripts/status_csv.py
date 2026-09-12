#!/usr/bin/env python3
"""Atomic status storage; one controller process owns transition decisions."""
from __future__ import annotations
import argparse,csv,os,tempfile
from pathlib import Path

ACTIVE={'CONTROL_PEND','CONTROL_RUN','MESHER','SOLVER','QC'}
REQUIRED=('run_id','state','output_qc','reason','attempt','control_job_id','mesher_job_id','solver_job_id','submit_time','finish_time','scratch_cleaned')
def read(p):
 with p.open(newline='') as f:
  r=csv.DictReader(f);return list(r),r.fieldnames
def write(p, rows, fields):
 p.parent.mkdir(parents=True,exist_ok=True);fd,tmp=tempfile.mkstemp(dir=p.parent,prefix=p.name+'.',text=True)
 with os.fdopen(fd,'w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
 os.replace(tmp,p)
def main():
 q=argparse.ArgumentParser();q.add_argument('--status',type=Path,required=True);s=q.add_subparsers(dest='cmd',required=True)
 i=s.add_parser('init');i.add_argument('--template',type=Path,required=True)
 u=s.add_parser('update');u.add_argument('--run-id',required=True);u.add_argument('values',nargs='+')
 g=s.add_parser('get');g.add_argument('--run-id',required=True);g.add_argument('--field',required=True)
 s.add_parser('active');s.add_parser('active-count');s.add_parser('dump');a=q.parse_args()
 if a.cmd=='init':
  if not a.status.exists():
   initial,fields=read(a.template)
   fields=list(fields or [])
   for field in REQUIRED:
    if field not in fields: fields.append(field)
   for row in initial:
    for field in fields: row.setdefault(field,'')
   write(a.status,initial,fields)
  return
 rows,fields=read(a.status)
 if a.cmd=='active': print(*[x['run_id'] for x in rows if x['state'] in ACTIVE],sep='\n');return
 if a.cmd=='active-count':print(sum(x['state'] in ACTIVE for x in rows));return
 if a.cmd=='dump':print(a.status.read_text(),end='');return
 row=next((x for x in rows if x['run_id']==a.run_id),None)
 if not row:raise SystemExit('unknown run id')
 if a.cmd=='get':print(row.get(a.field,''));return
 values=dict(x.split('=',1) for x in a.values)
 if not set(values)<=set(fields):raise SystemExit('unknown status field')
 row.update(values);write(a.status,rows,fields)
if __name__=='__main__':main()
