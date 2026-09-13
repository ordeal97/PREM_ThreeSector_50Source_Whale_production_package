import tempfile,sys
import unittest
from pathlib import Path
from unittest.mock import patch
from materialize_worktrees import ensure_runtime_dirs,main as materialize_main,may_replace_inactive
from production_common import worktree_errors
from production_cli import control_lsf,materialized_gate
from production_controller import all_terminal, counts_as_active, fail, process_failure, process_success_cleanup, remove_scratch, retry_ready, scheduler, stage2_ready, submission_blocked, submit
class ControllerLogic(unittest.TestCase):
 def setUp(self):
  self.cfg={'staging':{'stage1':'B0','stage2':'M3'}};self.manifest=[{'run_id':'A','stage':'B0'},{'run_id':'B','stage':'B0'},{'run_id':'C','stage':'M3'}]
 def test_stage2_is_locked_until_all_baselines_pass(self):
  state={'A':{'state':'DONE','output_qc':'PASS'},'B':{'state':'DONE','output_qc':'FAIL'}}
  self.assertFalse(stage2_ready(self.manifest,state,self.cfg))
 def test_stage2_unlocks_only_on_done_and_pass(self):
  state={'A':{'state':'DONE','output_qc':'PASS'},'B':{'state':'DONE','output_qc':'PASS'}}
  self.assertTrue(stage2_ready(self.manifest,state,self.cfg))
 def test_worktree_runtime_directories_are_created_idempotently(self):
  target=Path(tempfile.mkdtemp())/'run'
  ensure_runtime_dirs(target);ensure_runtime_dirs(target)
  self.assertTrue(all((target/name).is_dir() for name in ('obj','bin','OUTPUT_FILES','logs')))
 def test_rebuild_inactive_refuses_active_or_unclean_failed_runs(self):
  self.assertTrue(may_replace_inactive({'state':'NOT_SUBMITTED'}))
  self.assertTrue(may_replace_inactive({'state':'EXIT','scratch_cleaned':'true'}))
  self.assertFalse(may_replace_inactive({'state':'EXIT','scratch_cleaned':'false'}))
  self.assertFalse(may_replace_inactive({'state':'SOLVER','scratch_cleaned':'true'}))
 def test_control_lsf_creates_runtime_logs(self):
  root=Path(tempfile.mkdtemp())
  cfg={'lsf':{'control_job_prefix':'p','control_queue':'serial','control_ranks':1,'control_hosts':1},'runtime':{'python_bin':'python3'},'_root':root,'_path':root/'config.toml','paths':{'runtime_root':root/'runtime'}}
  control_lsf(cfg,'run')
  self.assertTrue((root/'runtime/logs').is_dir())
  self.assertIn('#BSUB -L /bin/bash',(root/'runtime/rendered_lsf/production_run.lsf').read_text())
 def test_job_terminal_guard_and_retry_guard(self):
  self.assertTrue(all_terminal({'control_job_id':'EXIT','mesher_job_id':'DONE','solver_job_id':'EXIT'}))
  for state in ('RUN','PEND','UNKNOWN'):
   self.assertFalse(all_terminal({'control_job_id':'EXIT','solver_job_id':state}))
  scratch=Path(tempfile.mkdtemp())/'missing'
  self.assertTrue(retry_ready({'state':'EXIT','scratch_cleaned':'true'},{'control_job_id':'EXIT'},scratch))
  self.assertFalse(retry_ready({'state':'EXIT','scratch_cleaned':'true'},{'control_job_id':'RUN'},scratch))
  self.assertFalse(retry_ready({'state':'QC_FAIL','scratch_cleaned':'false'},{'solver_job_id':'EXIT'},scratch))
 def test_cleanup_failure_blocks_submissions(self):
  self.assertTrue(submission_blocked({'A':{'scratch_cleaned':'false'}}))
  self.assertFalse(submission_blocked({'A':{'scratch_cleaned':'true'},'B':{'scratch_cleaned':''}}))
  self.assertTrue(counts_as_active({'state':'EXIT'},{'control_job_id':'EXIT','mesher_job_id':'RUN'}))
  self.assertFalse(counts_as_active({'state':'EXIT'},{'control_job_id':'EXIT','mesher_job_id':'EXIT'}))
 def test_failure_cleanup_waits_for_live_child_and_records_cleanup_failure(self):
  root=Path(tempfile.mkdtemp());run=root/'work'/'A';run.mkdir(parents=True)
  cfg={'paths':{'run_root':root/'work','scratch_root':root/'scratch','runtime_root':root/'runtime'},'_root':root}
  row={'run_id':'A','stage':'B0','scratch_database_path':str(root/'scratch'/'A'/'DATABASES_MPI')}
  status={'state':'EXIT','attempt':'0','failure_stage':'CONTROL','reason':'control_exit'}
  with patch('production_controller.state',return_value={'A':status}),patch('production_controller.job_states',return_value={'control_job_id':'EXIT','mesher_job_id':'RUN'}),patch('production_controller.write_failed') as record,patch('production_controller.preserve_diagnostics') as preserve,patch('production_controller.remove_scratch') as clean:
   self.assertFalse(process_failure(cfg,row));record.assert_called();preserve.assert_not_called();clean.assert_not_called()
  updates=[]
  with patch('production_controller.state',return_value={'A':status}),patch('production_controller.job_states',return_value={'control_job_id':'EXIT','mesher_job_id':'EXIT'}),patch('production_controller.write_failed'),patch('production_controller.preserve_diagnostics'),patch('production_controller.remove_scratch',side_effect=OSError('no space')),patch('production_controller.update',side_effect=lambda *x:updates.append(x)):
   self.assertFalse(process_failure(cfg,row))
  self.assertTrue(any('scratch_cleaned=false' in x for call in updates for x in call))
 def test_success_cleanup_removes_declared_scratch_after_terminal_jobs(self):
  root=Path(tempfile.mkdtemp());target=root/'scratch'/'A';(target/'DATABASES_MPI').mkdir(parents=True);(target/'DATABASES_MPI'/'x').write_text('x')
  cfg={'paths':{'run_root':root/'work','scratch_root':root/'scratch','runtime_root':root/'runtime'}};row={'run_id':'A','scratch_database_path':str(target/'DATABASES_MPI')}
  remove_scratch(cfg,row);self.assertFalse(target.exists())
  updates=[];status={'attempt':'0'}
  with patch('production_controller.state',return_value={'A':status}),patch('production_controller.job_states',return_value={'solver_job_id':'DONE'}),patch('production_controller.remove_scratch'),patch('production_controller.update',side_effect=lambda *x:updates.append(x)):
   self.assertTrue(process_success_cleanup(cfg,row))
  self.assertTrue(any('state=DONE' in ' '.join(str(x) for x in call) and 'scratch_cleaned=true' in ' '.join(str(x) for x in call) for call in updates))
 def test_mesher_solver_control_and_qc_failures_keep_their_stage(self):
  root=Path(tempfile.mkdtemp());cfg={'paths':{'run_root':root/'work','scratch_root':root/'scratch','runtime_root':root/'runtime'}};row={'run_id':'A','stage':'B0','scratch_database_path':str(root/'scratch'/'A'/'DATABASES_MPI')}
  for stage,want in (('MESHER','state=EXIT'),('SOLVER','state=EXIT'),('CONTROL','state=EXIT'),('QC','state=QC_FAIL')):
   status={'state':'SOLVER','attempt':'0','output_qc':''};updates=[]
   with patch('production_controller.state',return_value={'A':status}),patch('production_controller.process_failure'),patch('production_controller.update',side_effect=lambda *x:updates.append(x)):
    fail(cfg,row,stage,'test')
   self.assertTrue(any(want in ' '.join(str(x) for x in call) and 'failure_stage='+stage in ' '.join(str(x) for x in call) for call in updates))
 def test_submit_creates_manifest_database_path_before_mocked_bsub(self):
  root=Path(tempfile.mkdtemp());run=root/'work'/'A';run.mkdir(parents=True);(run/'submit_lsf.bash').write_text('#!/usr/bin/env bash\n')
  database=root/'scratch'/'A'/'DATABASES_MPI';cfg={'paths':{'run_root':root/'work','scratch_root':root/'scratch','runtime_root':root/'runtime'}};row={'run_id':'A','stage':'B0','scratch_database_path':str(database)};updates=[]
  def fake_bsub(*args,**kwargs):
   self.assertTrue(database.is_dir());self.assertTrue((root/'scratch'/'A').is_dir())
   return type('Result',(),{'returncode':0,'stdout':'Job <123> is submitted'})()
  with patch('production_controller.worktree_errors',return_value=[]),patch('production_controller.subprocess.run',side_effect=fake_bsub),patch('production_controller.update',side_effect=lambda *x:updates.append(x)):
   submit(cfg,row);submit(cfg,row)
  self.assertTrue(any('control_job_id=123' in str(x) for x in updates))
 def test_worktree_gate_rejects_stale_rendered_lsf(self):
  root=Path(tempfile.mkdtemp());rid='A';inputs=root/'inputs'/rid/'DATA';rendered=root/'rendered_lsf'/rid;run=root/'work'/rid
  inputs.mkdir(parents=True);rendered.mkdir(parents=True);(run/'DATA').mkdir(parents=True)
  for name in ('Par_file','CMTSOLUTION','STATIONS','ulvz_s40rts.par'):(inputs/name).write_text(name);(run/'DATA'/name).write_text(name)
  for name in ('submit_lsf.bash','mesher_lsf.bash','solver_lsf.bash'):(rendered/name).write_text(name);(run/name).write_text(name)
  row={'run_id':rid,'par_file_sha256':'p','cmtsolution_sha256':'c','stations_sha256':'s','ulvz_file_sha256':'u'}
  import json
  (run/'run_identity.json').write_text(json.dumps({'run_id':rid,'source_commit':'commit','input_hashes':{'par_file_sha256':'p','cmtsolution_sha256':'c','stations_sha256':'s','ulvz_file_sha256':'u'}}))
  cfg={'paths':{'run_root':root/'work','inputs_dir':root/'inputs'},'_root':root,'source':{'commit':'commit'}}
  self.assertEqual(worktree_errors(cfg,row),[])
  (run/'solver_lsf.bash').write_text('stale')
  self.assertTrue(worktree_errors(cfg,row))
 def test_materialized_gate_rejects_missing_or_stale_tree(self):
  cfg={'paths':{'manifest':Path('manifest')}}
  with patch('production_cli.rows',return_value=[{'run_id':'A'}]),patch('production_cli.worktree_errors',return_value=['worktree missing']):
   with self.assertRaises(RuntimeError):materialized_gate(cfg)
 def test_scheduler_accepts_historical_done_successfully_text(self):
  empty=type('Result',(),{'stdout':''})()
  history=type('Result',(),{'stdout':'Done successfully'})()
  with patch('production_controller.subprocess.run',side_effect=[empty,history]):self.assertEqual(scheduler('123'),'DONE')
 def test_refresh_lsf_does_not_require_build_template_evidence(self):
  root=Path(tempfile.mkdtemp());run=root/'work'/'A';(run/'DATA').mkdir(parents=True);(run/'DATA'/'Par_file').write_text('x')
  manifest=root/'manifest.csv';row={'run_id':'A','scratch_database_path':str(root/'scratch'/'A'/'DATABASES_MPI')}
  cfg={'paths':{'manifest':manifest,'run_root':root/'work','runtime_root':root/'runtime'},'environment':{'oneapi_setup':'/setup','modules':['hdf5'],'mpi_launcher':'mpirun'},'lsf':{'mpi_ranks':1,'ptile':1,'mpi_queue':'mpi','control_queue':'serial','control_ranks':1,'control_hosts':1,'per_run_wait_seconds':1},'build':{'make_jobs':1,'mesher_target':'meshfem3D','solver_target':'specfem3D'}}
  with patch('materialize_worktrees.load_config',return_value=cfg),patch('materialize_worktrees.rows',side_effect=lambda path:[row] if path==manifest else []),patch('materialize_worktrees.latest_build') as build,patch.object(sys,'argv',['materialize_worktrees.py','--config','x','--refresh-lsf','--run-id','A']):
   materialize_main();build.assert_not_called()
  self.assertTrue((run/'submit_lsf.bash').is_file())
 def test_submit_rejects_escape_or_unwritable_database_before_bsub(self):
  root=Path(tempfile.mkdtemp());run=root/'work'/'A';run.mkdir(parents=True);(run/'submit_lsf.bash').touch()
  cfg={'paths':{'run_root':root/'work','scratch_root':root/'scratch','runtime_root':root/'runtime'}}
  with patch('production_controller.worktree_errors',return_value=[]),patch('production_controller.subprocess.run') as bsub:
   with self.assertRaises(RuntimeError):submit(cfg,{'run_id':'A','stage':'B0','scratch_database_path':str(root/'outside'/'DATABASES_MPI')})
   bsub.assert_not_called()
  database=root/'scratch'/'A'/'DATABASES_MPI';row={'run_id':'A','stage':'B0','scratch_database_path':str(database)}
  with patch('production_controller.worktree_errors',return_value=[]),patch('production_controller.os.access',return_value=False),patch('production_controller.subprocess.run') as bsub:
   with self.assertRaises(RuntimeError):submit(cfg,row)
   bsub.assert_not_called()
 def test_failure_cleanup_does_not_overwrite_completed_attempt(self):
  root=Path(tempfile.mkdtemp());cfg={'paths':{'run_root':root/'work','scratch_root':root/'scratch','runtime_root':root/'runtime'}};row={'run_id':'A','stage':'B0','scratch_database_path':str(root/'scratch'/'A'/'DATABASES_MPI')}
  status={'state':'EXIT','attempt':'0','scratch_cleaned':'true'}
  with patch('production_controller.state',return_value={'A':status}),patch('production_controller.write_failed') as record,patch('production_controller.remove_scratch') as clean:
   self.assertTrue(process_failure(cfg,row));record.assert_not_called();clean.assert_not_called()
 def test_pending_child_submission_prevents_failure_cleanup(self):
  root=Path(tempfile.mkdtemp());run=root/'work'/'A';run.mkdir(parents=True);(run/'run_job_ids.env').write_text('mesher_submission_state=PENDING\n')
  cfg={'paths':{'run_root':root/'work','scratch_root':root/'scratch','runtime_root':root/'runtime'}};row={'run_id':'A','stage':'B0','scratch_database_path':str(root/'scratch'/'A'/'DATABASES_MPI')};status={'state':'EXIT','attempt':'0'}
  with patch('production_controller.state',return_value={'A':status}),patch('production_controller.write_failed') as record,patch('production_controller.remove_scratch') as clean:
   self.assertFalse(process_failure(cfg,row));record.assert_called();clean.assert_not_called()
if __name__=='__main__':unittest.main()
