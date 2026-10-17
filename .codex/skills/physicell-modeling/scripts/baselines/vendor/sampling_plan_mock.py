"""Synthetic schedule collisions and frozen compact recovery; no model/engine calls.

The subprocess is a tiny frame/ACK writer, not a PhysiCell executable. Legacy
reference mapping below is the original nearest-time argmin with first tie.
"""
from pathlib import Path
import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
import native_stream as stream
from native_stream_mock import FAKE


class SamplingPlanChecks(unittest.TestCase):
 def test_export_bytes_and_legacy_observation_map_unchanged(self):
  for raw in [[0.,.4,.41,.9],[0.,.133333333,.583333333,1.33333333],
              [0.,.25,.5],[2679.9000000000046,2679.9999999999986,2681.1],
              [2887.833333333326,2887.8999999999983,2891.6],
              [0.,np.nextafter(.5,0),np.nextafter(.5,1),.5,.5]]:
   raw=np.asarray(raw);old_frames=np.unique(np.ceil(raw/.5)*.5)
   old_map=np.argmin(abs(old_frames[:,None]-raw[None,:]),axis=0)
   old_bytes=io.StringIO();np.savetxt(old_bytes,old_frames,fmt='%.8f')
   plan=stream.sampling_plan(raw)
   np.testing.assert_array_equal(plan['frame_times_minutes'],old_frames)
   np.testing.assert_array_equal(plan['raw_to_frame_index'],old_map)
   np.testing.assert_array_equal(np.asarray(plan['frame_times_minutes'])[plan['raw_to_export_index']],np.ceil(raw/.5)*.5)
   self.assertEqual(plan['sample_times_sha256'],hashlib.sha256(old_bytes.getvalue().encode()).hexdigest())
 def test_nearest_frame_differs_from_ceil_bin_and_keeps_earlier_tie(self):
  plan=stream.sampling_plan([0.,.25,.5,.583333333])
  self.assertEqual(plan['raw_to_export_index'],[0,1,1,2])
  self.assertEqual(plan['raw_to_frame_index'],[0,0,1,1])
 def test_duplicate_requests_do_not_create_extra_frames(self):
  plan=stream.sampling_plan([0.,.4,.4,.41,.9,.9])
  self.assertEqual(plan['frame_times_minutes'],[0.,.5,1.])
  self.assertEqual(plan['raw_to_frame_index'],[0,1,1,1,2,2])
 def test_schedule_and_alias_tampering_rejected(self):
  plan=stream.sampling_plan([0.,.4,.41,.9])
  with tempfile.TemporaryDirectory() as temporary:
   root=Path(temporary);np.savetxt(root/'sample_times.txt',plan['frame_times_minutes'],fmt='%.8f')
   stream.validate_sampling_plan(root,plan,plan['frame_times_minutes'])
   wrong=copy.deepcopy(plan);wrong['raw_to_frame_index'][1]=0
   with self.assertRaisesRegex(ValueError,'mapping'):stream.validate_sampling_plan(root,wrong,wrong['frame_times_minutes'])
   (root/'sample_times.txt').write_text('0\n0.5\n1\n')
   with self.assertRaisesRegex(ValueError,'file differs'):stream.validate_sampling_plan(root,plan,plan['frame_times_minutes'])
 def test_no_time_tolerance_widening(self):
  with self.assertRaisesRegex(ValueError,'no legacy-matched'):stream.observation_frame_map([1.000002],[0.,.5])


class CollisionStreamChecks(unittest.TestCase):
 def setUp(self):
  self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
  self.case=self.root/'transient/case';self.case.mkdir(parents=True);self.compact=self.root/'compact'
  self.fake=self.root/'fake_writer';self.fake.write_text('#!'+sys.executable+'\n'+FAKE);self.fake.chmod(0o755)
  self.raw=np.array([0.,.4,.41,.9]);self.plan=stream.sampling_plan(self.raw);self.times=np.array(self.plan['frame_times_minutes'])
  self.lookup=np.array(self.plan['raw_to_frame_index']);self.rows=np.array([7,9,11,12]);self.calls=[]
  self.expected=dict(run_id='synthetic',input_manifest_sha256='input',candidate_id='c',source_checkpoint_sha256='source',stage='shared',replicate=0,sampling_plan=self.plan)
  np.savetxt(self.case/'sample_times.txt',self.times,fmt='%.8f')
 def tearDown(self):self.temporary.cleanup()
 def measure(self,frame):self.calls.append(frame['index']);return np.full(30,frame['actual_minutes']),{}
 def execute(self,mode='normal',canonical=True):
  return stream.execute([str(self.fake),mode],self.case,self.times if canonical else self.raw,self.measure,3.,compact_directory=self.compact,provenance=self.expected if canonical else {})
 def test_live_canonical_stream_maps_collisions_once(self):
  result=self.execute();self.assertEqual(result['status'],'success');self.assertEqual(self.calls,[0,1,2]);self.assertFalse(self.case.exists())
  self.assertEqual(stream.map_observables(self.compact,self.rows,self.lookup,raw_observation_times=self.raw),4)
  with np.load(self.compact/'observables.npz') as saved:
   np.testing.assert_array_equal(saved['indices'],self.rows)
   np.testing.assert_array_equal(saved['predicted'][:,0],[0.,.5,.5,1.])
   np.testing.assert_array_equal(saved['observation_requested_times_minutes'],self.raw)
   np.testing.assert_array_equal(saved['observation_frame_indices'],self.lookup)
   np.testing.assert_array_equal(saved['observation_frame_times_minutes'],[0.,.5,.5,1.])
   np.testing.assert_array_equal(saved['observation_actual_times_minutes'],[0.,.5,.5,1.])
  identity=json.loads((self.compact/'stream_identity.json').read_text())
  self.assertEqual(identity['provenance']['sampling_plan'],self.plan)
  self.assertEqual(identity['input_artifact_sha256']['sample_times.txt'],self.plan['sample_times_sha256'])
 def test_old_raw_index_consumption_reproduces_strict_failure(self):
  result=self.execute(canonical=False)
  self.assertEqual(result['status'],'partial');self.assertEqual(self.calls,[0,1])
  self.assertIn('identity/order/time',result['error'])
  self.assertEqual(result['rejected_frame'],dict(frame_index=2,actual_minutes=1.,expected_next_index=2,expected_minutes=.41,canonical_frame_count=4))
 def test_interrupted_compact_recovery_maps_shared_frame_without_missing_rows(self):
  result=self.execute('failure');self.assertEqual(result['requested_time_support'].tolist(),[True,True,False])
  with patch.object(stream,'execute',side_effect=AssertionError('Recovery must never execute')):
   recovered=stream.recover_mapped_case(self.compact,self.expected,self.times,self.rows,self.lookup,{},raw_observation_times=self.raw)
  self.assertEqual(recovered['status'],'partial');self.assertEqual(recovered['measured_observations'],3);self.assertEqual(recovered['requested_snapshots'],3)
  with np.load(self.compact/'observables.npz') as saved:
   np.testing.assert_array_equal(saved['indices'],self.rows[:3]);np.testing.assert_array_equal(saved['predicted'][:,0],[0.,.5,.5])
   np.testing.assert_array_equal(saved['requested_time_support'],[True,True,False]);np.testing.assert_array_equal(saved['observation_frame_indices'],[0,1,1,2])
   self.assertTrue(np.isnan(saved['observation_actual_times_minutes'][-1]))
  before=(self.compact/'outcome.json').read_bytes()
  stream.recover_mapped_case(self.compact,self.expected,self.times,self.rows,self.lookup,{},raw_observation_times=self.raw)
  self.assertEqual((self.compact/'outcome.json').read_bytes(),before)
 def test_recovery_rejects_changed_raw_mapping_or_sample_file_hash(self):
  self.execute('failure');wrong=copy.deepcopy(self.expected);wrong['sampling_plan']['raw_requested_minutes'][1]=.39
  with self.assertRaisesRegex(ValueError,'schedule/raw mapping'):stream.load_compact_evidence(self.compact,wrong,self.times)
  path=self.compact/'stream_identity.json';identity=json.loads(path.read_text());identity['input_artifact_sha256']['sample_times.txt']='b'*64;path.write_text(json.dumps(identity))
  with self.assertRaisesRegex(ValueError,'schedule/raw mapping'):stream.load_compact_evidence(self.compact,self.expected,self.times)
 def test_lineage_wrapper_recovers_collisions_from_frozen_metadata(self):
  import lineage_model as lineage
  model=self.root/'lineage';folder=model/'candidates/c';self.compact=folder/'simulations/000'
  candidate=dict(id='c',stage='shared',alpha=0.)
  def dump(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
  dump(self.root/'run_identity.json',dict(run_id='synthetic'));dump(self.root/'input_manifest.json',{})
  dump(model/'shared_candidates.json',[candidate]);dump(folder/'final.json',dict(x=[0.]*15))
  raw_days=self.raw/1440;self.raw=raw_days*1440;self.plan=stream.sampling_plan(self.raw);self.lookup=np.asarray(self.plan['raw_to_frame_index'])
  dump(folder/'slots.json',[dict(replicate=0,times_days=raw_days.tolist(),indices=self.rows.tolist(),lookup=list(range(4)))])
  self.expected=stream.run_expectation(self.root,'c',hashlib.sha256((folder/'final.json').read_bytes()).hexdigest(),'shared',0);self.expected['sampling_plan']=self.plan
  self.execute('failure')
  with patch.object(lineage,'ROOT',model),patch.object(lineage,'evaluate',side_effect=AssertionError('No model calls')),patch.object(lineage,'Data',side_effect=AssertionError('No model construction')):
   recovered=lineage.recover_lineage_case('shared',0,0)
  self.assertEqual(recovered['measured_observations'],3)
  with np.load(self.compact/'observables.npz') as saved:np.testing.assert_array_equal(saved['observation_frame_indices'],[0,1,1,2])
 def test_lineage_live_wrapper_composes_rows_and_deduplicates_figure_frame(self):
  import lineage_model as lineage
  model=self.root/'lineage';folder=model/'candidates/c';compact=folder/'simulations/000'
  candidate=dict(id='c',stage='shared',alpha=0.);folder.mkdir(parents=True)
  (model/'shared_candidates.json').write_text(json.dumps([candidate]));(folder/'final.json').write_text(json.dumps(dict(x=[0.]*15)))
  slot=dict(group_index=0,oxygen=0.,seed=7,replicate=0,times_days=(self.raw/1440).tolist(),indices=[175,57,11,12],lookup=[2,1,3,0])
  (folder/'slots.json').write_text(json.dumps([slot]));assets=[]
  def export(directory,*args,**kwargs):
   directory.mkdir();plan=stream.sampling_plan(args[3]);np.savetxt(directory/'sample_times.txt',plan['frame_times_minutes'],fmt='%.8f');return dict(sampling_plan=plan)
  context=dict(run_root=str(self.root),run_id='synthetic',input_manifest_sha256='input',reserve_asset=lambda *args:'slot',commit_asset=lambda token,asset:assets.append(asset))
  with patch.object(lineage,'ROOT',model),patch.object(lineage,'ENGINE',self.fake,create=True),patch.object(lineage,'TIMEOUT',3.),patch.object(lineage,'vectors',return_value=np.zeros((2,15))),patch.object(lineage,'rate',return_value=1.),patch.object(lineage.transfer,'export_case',side_effect=export),patch.object(lineage.transfer,'snapshot_arrays',side_effect=lambda x,y,v,d,*args:(np.full(30,float(v[0])),{})),patch.object(stream,'STORAGE_CONTEXT',context),patch.object(lineage,'evaluate',side_effect=AssertionError('No model calls')):
   lineage.simulate('shared',0,0)
  outcome=json.loads((compact/'outcome.json').read_text());self.assertEqual(outcome['status'],'complete');self.assertEqual(outcome['requested_snapshots'],3);self.assertEqual(outcome['raw_requested_times'],4)
  with np.load(compact/'observables.npz') as saved:np.testing.assert_array_equal(saved['observation_frame_indices'],[1,1,2,0])
  self.assertEqual(len(assets),1);self.assertEqual(assets[0]['sample_index'],1);self.assertEqual(assets[0]['observation_rows'],[57,175]);self.assertEqual(assets[0]['actual_minutes'],.5)
 def test_perspective_wrapper_recovers_collisions_from_frozen_metadata(self):
  import native_diagnostics as diagnostics
  model=self.root/'perspective';out=model/'screen';self.compact=out/'cases/c/00000';frozen=out/'frozen/c/final.json'
  def dump(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
  dump(frozen,dict(x=[0.]*33));digest=hashlib.sha256(frozen.read_bytes()).hexdigest()
  raw_days=self.raw/1440;self.raw=raw_days*1440;self.plan=stream.sampling_plan(self.raw)
  dump(out/'parameter_manifest.json',dict(c=digest));dump(out/'slots.json',[dict(candidate_id='c',case_index=0,replicate=0,times_days=raw_days.tolist(),observation_rows=[0,1,2,3],kind='main')])
  dump(self.root/'run_identity.json',dict(run_id='synthetic'));dump(self.root/'input_manifest.json',{})
  self.expected=stream.run_expectation(self.root,'c',digest,'screen',0);self.expected['sampling_plan']=self.plan
  self.execute('failure')
  with patch.object(diagnostics,'ROOT',model),patch.object(diagnostics.a,'evaluate',side_effect=AssertionError('No model calls')),patch.object(diagnostics.a,'Data',side_effect=AssertionError('No model construction')):
   recovered=diagnostics.recover_perspective_case('screen',0,pd.DataFrame(dict(time_days=raw_days)))
  self.assertEqual(recovered['measured_observations'],3)
  with np.load(self.compact/'observables.npz') as saved:np.testing.assert_array_equal(saved['observation_frame_indices'],[0,1,1,2])
 def test_perspective_live_wrapper_uses_canonical_figure_index(self):
  import native_diagnostics as diagnostics
  import types
  model=self.root/'perspective';out=model/'screen';frozen=out/'frozen/c/final.json';frozen.parent.mkdir(parents=True);frozen.write_text(json.dumps(dict(x=[0.]*33)))
  slot=dict(candidate_id='c',case_index=0,replicate=0,seed=7,kind='main',times_days=(self.raw/1440).tolist(),observation_rows=[0,57,175,1])
  (out/'slots.json').write_text(json.dumps([slot]));(out/'parameter_manifest.json').write_text(json.dumps(dict(c=hashlib.sha256(frozen.read_bytes()).hexdigest())))
  times=np.zeros(176);times[[0,57,175,1]]=self.raw/1440;data=types.SimpleNamespace(rows=pd.DataFrame(dict(time_days=times)))
  spec=dict(seed=7,times_days=slot['times_days'],domain_size=[120,100],field_shape=[100,120],crop_origin=[0,0]);assets=[]
  def export(directory,sp,override):
   directory.mkdir();plan=stream.sampling_plan(np.asarray(sp['times_days'])*1440);np.savetxt(directory/'sample_times.txt',plan['frame_times_minutes'],fmt='%.8f');return dict(sampling_plan=plan),np.asarray(plan['frame_times_minutes'])
  context=dict(run_root=str(self.root),run_id='synthetic',input_manifest_sha256='input',reserve_asset=lambda *args:'slot',commit_asset=lambda token,asset:assets.append(asset))
  with patch.object(diagnostics,'ROOT',model),patch.object(diagnostics,'spec',return_value=spec),patch.object(diagnostics,'stage_remaining_seconds',return_value=10.),patch.object(diagnostics.a,'Data',return_value=data),patch.object(diagnostics.native,'ENGINE',self.fake),patch.object(diagnostics.native,'export_case',side_effect=export),patch.object(diagnostics.native,'support_snapshot',side_effect=lambda frame,sp:self.measure(frame)),patch.object(stream,'STORAGE_CONTEXT',context),patch.object(diagnostics.a,'evaluate',side_effect=AssertionError('No model calls')):
   diagnostics.run('screen',0)
  compact=out/'cases/c/00000';outcome=json.loads((compact/'outcome.json').read_text());self.assertEqual(outcome['status'],'complete')
  with np.load(compact/'observables.npz') as saved:np.testing.assert_array_equal(saved['observation_frame_indices'],[0,1,1,2])
  self.assertEqual(self.calls,[0,1,2]);self.assertEqual(len(assets),1);self.assertEqual(assets[0]['sample_index'],1);self.assertEqual(assets[0]['observation_rows'],[57,175])


if __name__=='__main__':unittest.main()
