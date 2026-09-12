#!/usr/bin/env python3
"""Pure in-memory controller exercise: no LSF commands, builds, or simulations."""
from __future__ import annotations
import json
from production_common import ROOT,load_config,rows
from production_controller import stage2_ready
def main():
 cfg=load_config(ROOT/'config/production.toml');manifest=rows(cfg['paths']['manifest']);state={x['run_id']:{'state':'NOT_SUBMITTED','output_qc':''} for x in manifest};active=[];peak=0;submitted=[];blocked=False
 while len(submitted)<len(manifest):
  for rid in active:state[rid]={'state':'DONE','output_qc':'PASS'}
  active=[];unlocked=stage2_ready(manifest,state,cfg)
  for row in manifest:
   if len(active)>=cfg['lsf']['max_active_runs']:break
   if state[row['run_id']]['state']!='NOT_SUBMITTED':continue
   if row['stage']==cfg['staging']['stage2'] and not unlocked:blocked=True;continue
   state[row['run_id']]={'state':'CONTROL_PEND','output_qc':''};active.append(row['run_id']);submitted.append(row['run_id'])
  peak=max(peak,len(active))
 for rid in active:state[rid]={'state':'DONE','output_qc':'PASS'}
 terminal=all(x['state']=='DONE' and x['output_qc']=='PASS' for x in state.values())
 report={'status':'PASS' if len(submitted)==100 and peak==2 and terminal else 'FAIL','scheduler':'in-memory state model; no bsub','submitted_runs':len(submitted),'max_active_observed':peak,'stage2_locked_observed':blocked,'stage2_unlocked_after_all_baselines':stage2_ready(manifest,state,cfg),'all_terminal_pass':terminal,'bsub_called':False,'mesher_called':False,'solver_called':False}
 (ROOT/'preflight/mock_submission.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));raise SystemExit(report['status']!='PASS')
if __name__=='__main__':main()
