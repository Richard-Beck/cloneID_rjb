"""Bounded fake-writer tests; never executes a PhysiCell engine or model."""
from pathlib import Path
import hashlib
import json
import os
import signal
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from scipy.io import savemat
import native_stream as stream
from core import transfer

FAKE=r'''import json,os,struct,sys,time
from pathlib import Path
CAP={'protocol':'cloneid-native-frame','version':1,'fields':5,'max_cells':200000,'max_frame_bytes':8000064,'acknowledged':True}
if len(sys.argv)>1 and sys.argv[1]=='--cloneid-frame-protocol':
 print(json.dumps(CAP));sys.exit(0)
root=Path.cwd();mode=sys.argv[1] if len(sys.argv)>1 else 'normal'
(root/'stream.protocol').write_text('CLONEID_NATIVE_FRAME_PROTOCOL 1 200000 5 8000064\n')
state=(root/'state_trajectory.csv').open('w');state.write('time_minutes,n_low,n_high,n_dead_low,n_dead_high,wgd_events\n');state.flush()
times=[float(line) for line in (root/'sample_times.txt').read_text().splitlines()] if (root/'sample_times.txt').exists() else [0.,30.,60.]
for i,t in enumerate(times):
 cells=[[20.,20.,1000.,0.,0.],[40.,30.,1200.,0.,1.],[60.,50.,900.,1.,0.]]
 raw=struct.pack('<8sIIQdQQQQ',b'CLIDFRM1',1,5,i,t,len(cells),len(cells)*40,0,0)+b''.join(struct.pack('<5d',*row) for row in cells)
 if mode=='oversized' and i==0:raw=struct.pack('<8sIIQdQQQQ',b'CLIDFRM1',1,5,i,t,200001,200001*40,0,0)
 with (root/'stream.frame.part').open('wb') as f:
  f.write(raw[:32]);f.flush();time.sleep(.02);f.write(raw[32:])
 state.write(f'{t},1,1,1,0,0\n');state.flush()
 (root/'stream.frame.part').replace(root/'stream.frame.ready')
 print('SAMPLE',i,flush=True)
 deadline=time.monotonic()+10
 while not (root/'stream.ack').exists():
  if time.monotonic()>deadline:sys.exit(9)
  time.sleep(.002)
 if int((root/'stream.ack').read_text())!=i:sys.exit(10)
 (root/'stream.ack').unlink()
 if (root/'stream.frame.ready').exists():sys.exit(11)
 if mode=='failure' and i==1:sys.exit(7)
 if mode=='timeout' and i==0:time.sleep(10)
 if mode=='log':print('L'*100000,flush=True)
state.close()
'''


class StreamChecks(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.case=self.root/'transient/case0';self.compact=self.root/'result';self.case.mkdir(parents=True)
  self.fake=self.root/'fake_engine';self.fake.write_text('#!'+sys.executable+'\n'+FAKE);self.fake.chmod(0o755)
  self.calls=[]
 def tearDown(self):self.temp.cleanup()
 def observer(self,frame):
  self.calls.append(frame['index'])
  self.assertFalse((self.case/'stream.frame.part').exists());self.assertTrue((self.case/'stream.frame.ready').exists());self.assertFalse((self.case/'stream.ack').exists())
  return np.full(30,frame['actual_minutes']),dict(count=frame['cells'])
 def run_case(self,mode='normal',timeout=3.,**kwargs):
  return stream.execute([str(self.fake),mode],self.case,[0.,30.,60.],self.observer,timeout,compact_directory=self.compact,**kwargs)
 def test_exact_ack_stream_and_cleanup(self):
  result=self.run_case();self.assertEqual(result['status'],'success');self.assertEqual(self.calls,[0,1,2]);self.assertFalse(self.case.exists());self.assertTrue(result['case_cleanup_complete']);self.assertEqual(result['requested_time_support'].tolist(),[True]*3)
  with np.load(self.compact/'stream_observables.npz') as progress:
   self.assertEqual(str(progress['stream_identity_sha256']),hashlib.sha256((self.compact/'stream_identity.json').read_bytes()).hexdigest());np.testing.assert_array_equal(progress['actual_times_minutes'],[0.,30.,60.]);self.assertEqual(progress['frame_sha256'].shape,(3,))
  self.assertLessEqual(result['peak_case_bytes'],stream.MAX_FRAME_BYTES);self.assertTrue((self.compact/'state_trajectory.csv').exists());self.assertFalse(list(self.root.rglob('*.mat')));self.assertFalse(list(self.root.rglob('*.xml')))
 def test_late_failure_retains_earlier_actual_support(self):
  result=self.run_case('failure');self.assertEqual(result['status'],'partial');self.assertEqual(result['engine_returncode'],7);self.assertEqual(result['requested_time_support'].tolist(),[True,True,False]);self.assertTrue(np.isnan(result['predicted'][2]).all());self.assertFalse(self.case.exists())
 def test_timeout_and_cancel_cleanup(self):
  result=self.run_case('timeout',timeout=.2);self.assertEqual(result['engine_status'],'timed_out');self.assertEqual(result['requested_time_support'].tolist(),[True,False,False]);self.assertFalse(self.case.exists())
 def test_cancellation_from_callback_preserves_measured_frame(self):
  def cancel(frame):
   value=self.observer(frame);os.kill(os.getpid(),signal.SIGTERM);return value
  result=stream.execute([str(self.fake),'normal'],self.case,[0.,30.,60.],cancel,3.,compact_directory=self.compact)
  self.assertEqual(result['engine_status'],'cancelled');self.assertTrue(result['requested_time_support'][0]);self.assertFalse(self.case.exists())
 def test_oversized_header_rejected_without_measurement(self):
  result=self.run_case('oversized');self.assertEqual(result['status'],'failure');self.assertEqual(self.calls,[]);self.assertIn('header/payload',result['error']);self.assertFalse(self.case.exists())
 def test_old_engine_fails_before_case_execution(self):
  old=self.root/'old_engine';old.write_text('#!'+sys.executable+'\nimport sys\nfrom pathlib import Path\nif "--cloneid-frame-protocol" in sys.argv:sys.exit(1)\nPath("MUST_NOT_RUN").write_text("bad")\n');old.chmod(0o755)
  result=stream.execute([str(old),'normal'],self.case,[0.],self.observer,1.,compact_directory=self.compact)
  self.assertEqual(result['status'],'failure');self.assertIn('lacks required',result['error']);self.assertFalse((self.case/'MUST_NOT_RUN').exists());self.assertFalse(self.case.exists())
 def test_bounded_logs_are_drained(self):
  result=self.run_case('log',limits=dict(log_bytes=1024));self.assertEqual(result['status'],'success');self.assertTrue(result['log_truncated']);self.assertLessEqual((self.compact/'engine.log').stat().st_size,1024)
 def test_exact_full_precision_asset_deduplicated_and_reserved(self):
  reservations=[];commits=[]
  def reserve(size,path,metadata):reservations.append(size);return 'slot0'
  def commit(token,record):commits.append((token,record))
  context=dict(run_root=str(self.root),run_id='synthetic',input_manifest_sha256='input',reserve_asset=reserve,commit_asset=commit)
  provenance=dict(candidate_id='candidate',source_checkpoint_sha256='source',stage='shared',replicate=0,seed=7,case_index=0,case_spec=dict(seed=7))
  with patch.object(stream,'STORAGE_CONTEXT',context):result=self.run_case(provenance=provenance,figure_requests={0:[175,57,57],1:[1]},figure_geometry=([120,100],[100,120],[0,0]))
  manifest=json.loads((self.compact/'field_assets.json').read_text());self.assertEqual(len(manifest['assets']),1);asset=manifest['assets'][0];path=self.root/asset['path'];self.assertEqual(asset['geometry']['field_shape'],[100,120]);self.assertEqual(asset['geometry']['units']['position'],'pixels');self.assertEqual(asset['seed'],7);self.assertEqual(asset['case_index'],0);self.assertEqual(len(asset['case_spec_sha256']),64);self.assertEqual(asset['kind'],'native_cell_frame_v1');self.assertEqual(asset['observation_rows'],[57,175]);self.assertEqual(reservations,[184]);self.assertEqual(len(commits),1);self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),asset['sha256']);self.assertEqual(stream.read_frame(path)['cells'],3);self.assertEqual(result['status'],'success')
 def test_asset_reservation_rejection_does_not_drop_science(self):
  context=dict(run_root=str(self.root),run_id='synthetic',input_manifest_sha256='input',reserve_asset=lambda *args:False)
  with patch.object(stream,'STORAGE_CONTEXT',context):result=self.run_case(provenance=dict(candidate_id='c',source_checkpoint_sha256='x',replicate=0,seed=7,case_index=0,case_spec=dict(seed=7)),figure_requests={0:[57]},figure_geometry=([120,100],[100,120],[0,0]))
  self.assertEqual(result['status'],'success');self.assertEqual(result['snapshots'][0]['asset_retention'],'global_asset_budget_exhausted');self.assertFalse(list(self.compact.glob('*.bin')))
 def test_initial_csv_cap_checked_before_write(self):
  import pandas as pd
  target=self.case/'initial_cells.csv'
  with patch.object(stream,'STORAGE_CONTEXT',dict(input_bytes=262150)):
   with self.assertRaisesRegex(ValueError,'exceeds declared'):stream.write_initial_csv(pd.DataFrame(dict(value=['a'*100])),target)
  self.assertFalse(target.exists())


class ObserverChecks(unittest.TestCase):
 def test_legacy_xml_mat_and_compact_frame_observers_identical(self):
  with tempfile.TemporaryDirectory() as temporary:
   root=Path(temporary);x=np.array([20.,40.,60.,85.]);y=np.array([20.,30.,50.,70.]);volume=np.array([1000.,1200.,900.,800.]);dead=np.array([0.,0.,1.,0.]);state=np.array([0.,1.,0.,1.])
   data=np.vstack([x,y,np.zeros(4),volume,dead]);savemat(root/'output00000000_cells.mat',dict(cells=data))
   (root/'output00000000.xml').write_text('<root><labels><label index="0" size="3">position</label><label index="3" size="1">total_volume</label><label index="4" size="1">dead</label></labels></root>')
   raw=stream.HEADER.pack(b'CLIDFRM1',1,5,0,0.,4,160,0,0)+np.column_stack([x,y,volume,dead,state]).astype('<f8').tobytes();(root/'frame.bin').write_bytes(raw);frame=stream.read_frame(root/'frame.bin')
   geometry=([120,100],[100,120],[0,0]);old,oldmeta=transfer.snapshot(root/'output00000000.xml',*geometry);new,newmeta=transfer.snapshot_arrays(frame['x'],frame['y'],frame['total_volume'],frame['dead'],*geometry)
   np.testing.assert_array_equal(old,new);self.assertEqual(oldmeta,newmeta);self.assertEqual(newmeta['field_count'],4);self.assertEqual(newmeta['field_dead_count'],1)


class CompactRecoveryChecks(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.case=self.root/'case';self.case.mkdir()
  self.expected=dict(run_id='new',input_manifest_sha256='input',candidate_id='c',source_checkpoint_sha256='source',stage='shared',replicate=0)
  self.identity=dict(protocol=stream.PROTOCOL,protocol_version=1,times_minutes=[0.,30.],provenance=self.expected)
  self.create()
 def tearDown(self):self.temp.cleanup()
 def create(self):
  (self.case/'stream_identity.json').write_text(json.dumps(self.identity));digest=hashlib.sha256((self.case/'stream_identity.json').read_bytes()).hexdigest()
  np.savez_compressed(self.case/'stream_observables.npz',protocol_version=np.array(1),stream_identity_sha256=np.array(digest),times_minutes=np.array([0.,30.]),actual_times_minutes=np.array([0.,np.nan]),requested_time_support=np.array([True,False]),frame_sha256=np.array([b'a'*64,b''],dtype='S64'),predicted=np.vstack([np.arange(30.),np.full(30,np.nan)]))
 def recover(self):return stream.recover_mapped_case(self.case,self.expected,[0.,30.],[3,9],[0,1],dict(candidate_id='c'))
 def test_hardkill_recovers_exact_rows_without_fabricating_missing(self):
  result=self.recover();self.assertEqual(result['status'],'partial');self.assertEqual(result['recovery_model_calls'],0);self.assertEqual(result['engine_status'],'interrupted_recovered');self.assertEqual(result['measured_observations'],1)
  with np.load(self.case/'observables.npz') as values:self.assertEqual(values['indices'].tolist(),[3]);np.testing.assert_array_equal(values['predicted'][0],np.arange(30.));self.assertTrue(np.isnan(values['trajectory_predicted'][1]).all())
  self.assertFalse((self.case/'stream_observables.npz').exists());self.assertLessEqual(stream.compact_usage(self.case),2000000)
 def test_completed_or_partial_outcome_is_never_overwritten(self):
  for status in ['complete','partial']:
   value=dict(status=status,sentinel='immutable');(self.case/'outcome.json').write_text(json.dumps(value));before=(self.case/'outcome.json').read_bytes();self.assertEqual(self.recover(),value);self.assertEqual((self.case/'outcome.json').read_bytes(),before)
 def test_foreign_candidate_and_source_are_rejected(self):
  for key in ['candidate_id','source_checkpoint_sha256','run_id','input_manifest_sha256','stage','replicate']:
   wrong=dict(self.expected);wrong[key]='foreign'
   with self.assertRaisesRegex(ValueError,'identity mismatch'):stream.load_compact_evidence(self.case,wrong,[0.,30.])
 def test_changed_identity_hash_or_frozen_times_rejected(self):
  self.identity['extra']='changed';(self.case/'stream_identity.json').write_text(json.dumps(self.identity))
  with self.assertRaisesRegex(ValueError,'hash/protocol'):self.recover()
  self.create()
  with self.assertRaisesRegex(ValueError,'times mismatch'):stream.load_compact_evidence(self.case,self.expected,[0.,31.])
 def test_actual_time_or_frame_hash_mismatch_rejected(self):
  path=self.case/'stream_observables.npz'
  with np.load(path) as values:data={key:values[key] for key in values}
  data['actual_times_minutes']=np.array([10.,np.nan]);np.savez_compressed(path,**data)
  with self.assertRaisesRegex(ValueError,'actual frame times'):self.recover()
  self.create()
  with np.load(path) as values:data={key:values[key] for key in values}
  data['frame_sha256']=np.array([b'bad',b''],dtype='S64');np.savez_compressed(path,**data)
  with self.assertRaisesRegex(ValueError,'hash/support'):self.recover()
 def test_lineage_recovery_uses_only_frozen_metadata(self):
  import lineage_model as lineage
  def dump(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
  model=self.root/'lineage';candidate=dict(id='c',stage='shared',alpha=0.);folder=model/'candidates/c';self.case=folder/'simulations/000';self.case.mkdir(parents=True)
  dump(self.root/'run_identity.json',dict(run_id='new'));dump(self.root/'input_manifest.json',dict(files={}));dump(model/'shared_candidates.json',[candidate]);dump(folder/'final.json',dict(x=[0.]*15,loss=1.));dump(folder/'slots.json',[dict(replicate=0,times_days=[0.,30/1440],indices=[3,9],lookup=[0,1])])
  self.expected=stream.run_expectation(self.root,'c',hashlib.sha256((folder/'final.json').read_bytes()).hexdigest(),'shared',0);self.expected['sampling_plan']=stream.sampling_plan([0.,30.]);self.identity['provenance']=self.expected;self.identity['input_artifact_sha256']={'sample_times.txt':self.expected['sampling_plan']['sample_times_sha256']};self.create()
  with patch.object(lineage,'ROOT',model),patch.object(lineage,'evaluate',side_effect=AssertionError('No science evaluation')),patch.object(lineage,'Data',side_effect=AssertionError('No dataset model construction')):result=lineage.recover_lineage_case('shared',0,0)
  self.assertEqual(result['measured_observations'],1);self.assertEqual(result['source_stream_npz_name'],'stream_observables.npz')
 def test_perspective_recovery_uses_frozen_parameters_and_rows(self):
  import native_diagnostics as diagnostics
  import pandas as pd
  def dump(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
  model=self.root/'perspective';out=model/'screen';self.case=out/'cases/c/00000';self.case.mkdir(parents=True);frozen=out/'frozen/c/final.json';dump(frozen,dict(x=[0.]*33))
  digest=hashlib.sha256(frozen.read_bytes()).hexdigest();dump(out/'parameter_manifest.json',dict(c=digest));dump(out/'slots.json',[dict(candidate_id='c',case_index=0,replicate=0,times_days=[0.,30/1440],observation_rows=[0,1],kind='main')]);dump(self.root/'run_identity.json',dict(run_id='new'));dump(self.root/'input_manifest.json',dict(files={}))
  self.expected=stream.run_expectation(self.root,'c',digest,'screen',0);self.expected['sampling_plan']=stream.sampling_plan([0.,30.]);self.identity['provenance']=self.expected;self.identity['input_artifact_sha256']={'sample_times.txt':self.expected['sampling_plan']['sample_times_sha256']};self.create();rows=pd.DataFrame(dict(time_days=[0.,30/1440]))
  with patch.object(diagnostics,'ROOT',model),patch.object(diagnostics.a,'evaluate',side_effect=AssertionError('No approximation evaluation')),patch.object(diagnostics.a,'Data',side_effect=AssertionError('No model construction')):result=diagnostics.recover_perspective_case('screen',0,rows)
  self.assertEqual(result['checkpoint_sha256'],digest);self.assertEqual(result['measured_observations'],1);self.assertEqual(result['status'],'partial')
 def test_aggregate_and_per_file_admission_happen_before_write(self):
  directory=self.root/'full';directory.mkdir()
  names=['observables.npz','outcome.json','stream_identity.json','state_trajectory.csv','field_assets.json','stream_observables.npz','stream_provenance.json']
  for name in names:(directory/name).write_bytes(b'x'*262144)
  (directory/'engine.log').write_bytes(b'x'*65536)
  self.assertEqual(stream.compact_usage(directory),1900544)
  with self.assertRaisesRegex(ValueError,'Aggregate'):stream.write_npz(directory/'observables.npz',random=np.random.default_rng(1).random(30000))
  self.assertEqual((directory/'observables.npz').stat().st_size,262144)
  with self.assertRaisesRegex(ValueError,'declared byte cap'):stream.write_json(directory/'outcome.json',dict(too_large='x'*262144))
  self.assertEqual(stream.compact_contract()['final_closed_list_max_bytes'],1376256)


if __name__=='__main__':unittest.main()
