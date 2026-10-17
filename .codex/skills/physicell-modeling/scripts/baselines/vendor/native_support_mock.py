"""Synthetic native-failure checks; no private inputs, fit, or engine execution.

Run with the campaign Python: python vendor/native_support_mock.py
"""
from pathlib import Path
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import subprocess
import numpy as np
import pandas as pd

import native_support as support
from core import fitting
import lineage_model as lineage
import wgd_transfer as transfer
import native_diagnostics as diagnostics
import native_refinement as refinement


def dump(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))


def fake_data():
    rows=pd.DataFrame(dict(group=['2N','4N'],episode_id=['e0','e1'],passage_id=['p0','p1'],time_days=[0.,1.]))
    episodes=[dict(episode_id=f'e{i}',parent_episode_id=None,founding_group=group,arm='C',parent_transfer_time_days=0.) for i,group in enumerate(['2N','4N'])]
    return SimpleNamespace(n=2,obs=np.zeros((2,30)),scales=np.ones((2,30)),weights=np.full((2,6),.5),groups=np.array(['2N','4N']),rows=rows,episodes=episodes,byid={q['episode_id']:q for q in episodes})


def trajectory(path,both=True,last=30.):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    pd.DataFrame(dict(time_minutes=[0.,last],n_low=[10,11],n_high=[10 if both else 0,12 if both else 0],n_dead_low=[0,0],n_dead_high=[0,0],wgd_events=[0,0])).to_csv(path,index=False)


class SupportChecks(unittest.TestCase):
    def setUp(self):
        self.data=fake_data();self.coef=np.array([.5,.1,.1,.1,.1,.1])
    def score(self,p,**kwargs):
        d=self.data
        return support.score_support(p,d.obs,d.scales,d.weights,self.coef,1.,fitting.composite_score,**kwargs)
    def test_full_objective_identical(self):
        p=np.arange(60,dtype=float).reshape(2,30)/100
        expected=fitting.composite_score(p,self.data.obs,self.data.scales,self.data.weights,self.coef,offset=1.)
        value=self.score(p)
        self.assertEqual(value['full_loss'],expected[0]);self.assertEqual(value['weighted_components'],expected[2].tolist());self.assertEqual(value['ranking_basis'],'native_full')
    def test_partial_weights_and_exact_matched_support(self):
        p=np.full((2,30),2.);p[1]=np.nan
        value=self.score(p)
        self.assertIsNone(value['full_loss']);self.assertAlmostEqual(value['partial_loss'],4.);self.assertAlmostEqual(value['weight_fraction'],.5)
        matched=self.score(np.ones((2,30)),mask_override=np.asarray(value['mask']))
        self.assertAlmostEqual(matched['ranking_loss'],1.);self.assertAlmostEqual(matched['weight_fraction'],.5)
    def test_missing_component_is_explicit(self):
        p=np.ones((2,30));p[:,0]=np.nan
        value=self.score(p)
        self.assertIsNone(value['full_loss']);self.assertEqual(value['missing_components'],[0]);self.assertAlmostEqual(value['partial_loss'],.5)
    def test_no_support_and_duplicate_rows(self):
        self.assertIsNone(self.score(np.full((2,30),np.nan))['ranking_loss'])
        value=self.score(np.ones((2,30)),seen=np.array([2,0]));self.assertIsNone(value['ranking_loss'])
    def test_support_first_ranking_does_not_favor_low_partial_loss(self):
        def value(mask,loss):
            score=self.score(mask)
            return dict(candidate=dict(id=str(loss)),status='partial',ranking_score=loss,ranking_basis='native_partial_normalized',native_support=dict(replicates=[score]))
        broad=np.ones((2,30));broad[1]=np.nan;narrow=broad.copy();narrow[:,0]=np.nan
        broader=value(broad,100.);narrower=value(narrow,.01)
        self.assertLess(support.ranking_key(broader),support.ranking_key(narrower))
        complete=dict(status='complete',ranking_score=1e25,ranking_basis='native_full',candidate=dict(id='full'))
        self.assertLess(support.ranking_key(complete),support.ranking_key(broader))
        self.assertEqual(support.ranking_evidence(broader)['component_fraction'],1.)
    def test_exact_saved_snapshots_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for i,t in enumerate([0.,30.]):(root/f'output{i:08}.xml').write_text(f'<root><current_time>{t}</current_time></root>')
            p,available,records,_=support.measure_requested(root,[0.,30.,60.],lambda path:(np.ones(30),{}))
            self.assertEqual(available.tolist(),[True,True,False]);self.assertTrue(np.isnan(p[-1]).all());self.assertEqual(records[-1]['status'],'missing')


class LineageChecks(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name);self.data=fake_data();self.c=dict(id='shared_0',stage='shared',alpha=0.);self.folder=self.root/'candidates/shared_0'
        self.final=dict(x=[0.]*15,loss=1.,data_loss=1.,assumption_penalty=0.,ridge_penalty=0.,parameter_difference=0.)
        dump(self.folder/'final.json',self.final);dump(self.root/'shared_candidates.json',[self.c]);dump(self.folder/'slots.json',[dict(replicate=i,indices=[0,1]) for i in range(2)])
        self.context=patch.multiple(lineage,ROOT=self.root,Data=lambda:self.data,REPLICATES=2);self.context.start()
    def tearDown(self):self.context.stop();self.temporary.cleanup()
    def add(self,rep,indices,status='complete'):
        folder=self.folder/'simulations'/f'{rep:03}';dump(folder/'outcome.json',dict(status=status));np.savez_compressed(folder/'observables.npz',indices=indices,predicted=np.ones((len(indices),30)))
    def test_parallel_score_partial_and_read_only_reduce(self):
        self.add(0,[0,1]);self.add(1,[0],status='partial');result=lineage.score_candidate_worker('shared',0)
        self.assertEqual(result['status'],'partial');self.assertNotIn('simulator_data_loss',result);self.assertAlmostEqual(result['partial_simulator_data_loss'],1.)
        with patch.object(lineage,'Data',side_effect=AssertionError('Reducer must not load data or recompute scores')):lineage.score('shared')
        self.assertEqual(json.loads((self.root/'shared_best.json').read_text())['candidate'],self.c)
        dump(self.folder/'final.json',dict(self.final,loss=2.))
        with self.assertRaisesRegex(ValueError,'evidence mismatch'):lineage.score('shared')
    def test_one_supported_seed_does_not_invent_seed_dispersion(self):
        self.add(0,[0,1]);value=lineage.score_candidate_worker('shared',0)
        self.assertEqual(value['status'],'partial');self.assertIsNone(value['partial_simulator_data_loss_seed_sd'])
    def test_fit_filters_only_explicit_invalidity(self):
        self.c.update(initial=[0.]*15,seed=7);dump(self.root/'shared_candidates.json',[self.c])
        initial=dict(loss=1e25,invalid=True);valid=dict(loss=1e26,invalid=False)
        def search(objective,*args):
            self.assertIsNone(objective(np.zeros(15)));self.assertEqual(objective(np.zeros(15))['loss'],1e26)
        with patch.object(lineage,'evaluate',side_effect=[valid,initial,valid]),patch.object(lineage.fitting,'bounded_search',side_effect=search):lineage.fit('shared',0)
    def test_finalize_salvages_valid_checkpoint_without_optimizer_status(self):
        dump(self.folder/'checkpoint.json',dict(x=[0.]*15,loss=1.,evaluations=7))
        self.data.common_plans=[]
        with patch.object(lineage,'evaluate',return_value=self.final):lineage.finalize('shared',0)
        value=json.loads((self.folder/'final.json').read_text())
        self.assertEqual(value['fit_evaluations'],7);self.assertEqual(value['fit_evaluations_basis'],'checkpoint_lower_bound');self.assertTrue(value['optimizer_status_unavailable'])
    def test_complete_and_all_failed(self):
        self.add(0,[0,1]);self.add(1,[0,1]);value=lineage.score_candidate_worker('shared',0)
        self.assertEqual(value['status'],'complete');self.assertAlmostEqual(value['simulator_data_loss'],1.);self.assertEqual(value['simulator_data_loss_seed_sd'],0.)
        (self.folder/'simulations/000/observables.npz').unlink();(self.folder/'simulations/001/observables.npz').unlink()
        value=lineage.score_candidate_worker('shared',0);self.assertEqual(value['status'],'unavailable');lineage.score('shared')
        self.assertEqual(json.loads((self.root/'shared_best.json').read_text())['status'],'unavailable')
    def test_missing_score_record_reduces_to_unavailable(self):
        lineage.score('shared');self.assertEqual(json.loads((self.root/'shared_scores.json').read_text())[0]['reason'],'missing_score_worker_record')


class TransferChecks(unittest.TestCase):
    def test_timeout_preserves_earlier_exact_observations(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)/'case'
            def export(folder,spec,override):
                folder.mkdir();(folder/'output').mkdir();(folder/'output/output00000000.xml').write_text('<root><current_time>0</current_time></root>');trajectory(folder/'state_trajectory.csv',last=0.)
                return {},np.array([0.,30.])
            spec=dict(times_days=[0.,30/1440],domain_size=[1,1],field_shape=[1,1],crop_origin=[0,0])
            with patch.object(transfer,'export_case',side_effect=export),patch.object(transfer.subprocess,'run',side_effect=subprocess.TimeoutExpired('fake',1)),patch.object(transfer,'snapshot',return_value=(np.ones(30),{})):
                outcome=transfer.execute(directory,spec,timeout_seconds=1)
            self.assertEqual(outcome['status'],'partial');self.assertEqual(outcome['engine_status'],'timed_out');self.assertFalse(outcome['requested_terminal_time_available'])
            with np.load(directory/'observables.npz') as values:self.assertEqual(values['requested_time_support'].tolist(),[True,False]);self.assertTrue(np.isnan(values['predicted'][1]).all())


class DiagnosticChecks(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name);self.data=fake_data();self.stage=self.root/'screen';self.cid='case0';self.final=dict(x=[0.]*33,assays=[dict(id='saved',predicted_high=.2)])
        dump(self.stage/'frozen'/self.cid/'final.json',self.final);self.digest=support.file_sha(self.stage/'frozen'/self.cid/'final.json')
        dump(self.stage/'parameter_manifest.json',{self.cid:self.digest});dump(self.stage/'candidates.json',[dict(id=self.cid,alpha=0.)]);dump(self.stage/'contract.json',dict(replicates=2))
        self.slots=[dict(candidate_id=self.cid,case_index=i,kind='main',episode_id=f'e{i}',replicate=i,observation_rows=[0,1],oxygen=20.5,initial_high_fraction=.5) for i in range(2)]
        dump(self.stage/'slots.json',self.slots)
        def evaluate(data,x,alpha,family,folder,*args,**kwargs):
            folder.mkdir(parents=True,exist_ok=True);np.savez_compressed(folder/'approximation.npz',predicted=np.zeros((2,30)));return dict(valid=True)
        self.context=patch.multiple(diagnostics,ROOT=self.root);self.context.start()
        self.data_patch=patch.object(diagnostics.a,'Data',return_value=self.data);self.data_patch.start()
        self.decode_patch=patch.object(diagnostics.a,'decode',return_value={});self.decode_patch.start()
        self.evaluate_patch=patch.object(diagnostics.a,'evaluate',side_effect=evaluate);self.evaluate_patch.start()
    def tearDown(self):
        self.evaluate_patch.stop();self.decode_patch.stop();self.data_patch.stop();self.context.stop();self.temporary.cleanup()
    def add(self,both=False):
        folder=self.stage/'cases'/self.cid/'00000';dump(folder/'outcome.json',dict(status='partial',error='timeout',checkpoint_sha256=self.digest));trajectory(folder/'case/state_trajectory.csv',both=both)
        np.savez_compressed(folder/'observables.npz',indices=[0],predicted=np.ones((1,30)))
    def test_partial_microscopy_survives_missing_correction(self):
        self.add();diagnostics.analyze('screen',0);dest=self.stage/'analysis'/self.cid
        summary=json.loads((dest/'summary.json').read_text());micro=json.loads((dest/'microscopy_scores.json').read_text())
        self.assertEqual(summary['status'],'partial');self.assertEqual(summary['correction_status'],'unavailable');self.assertIsNone(micro['total']);self.assertAlmostEqual(micro['ranking_total'],1.);self.assertAlmostEqual(micro['ranking_native_minus_approximation_bias'],1.);self.assertTrue((dest/'native_counts.csv').exists())
    def test_projection_failure_preserves_evidence(self):
        self.add(both=True)
        with patch.object(diagnostics,'_project_analysis',side_effect=RuntimeError('synthetic projection numerical failure')):diagnostics.analyze('screen',0)
        dest=self.stage/'analysis'/self.cid;self.assertTrue((dest/'projection_outcome.json').exists());self.assertEqual(json.loads((dest/'summary.json').read_text())['correction_status'],'unavailable')
    def test_all_failed_produces_unavailable(self):
        diagnostics.analyze('screen',0);summary=json.loads((self.stage/'analysis'/self.cid/'summary.json').read_text());self.assertEqual(summary['status'],'unavailable');self.assertIsNone(summary['ranking_native_microscopy_loss'])
    def test_hash_integrity_remains_strict(self):
        dump(self.stage/'frozen'/self.cid/'final.json',dict(self.final,changed=True))
        with self.assertRaisesRegex(ValueError,'hash mismatch'):diagnostics.analyze('screen',0)


class RefinementChecks(unittest.TestCase):
    def test_finite_high_loss_and_expired_profile_preserve_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);cid='screen0';candidate=dict(id=cid,alpha=0.,seed=7)
            x=np.mean(refinement.a.BOUNDS,axis=1);x[:2]=.5;x[2]=np.log(1e-12)
            source=dict(x=x.tolist(),loss=1e25,valid=True)
            dump(root/'screen_candidates.json',[candidate]);dump(root/'candidates'/cid/'final.json',source);dump(root/'screen/frozen'/cid/'final.json',source)
            digest=support.file_sha(root/'screen/frozen'/cid/'final.json')
            correction=dict(status='available',native_records=1,source_x=x.tolist(),source_sha256=digest)
            dump(root/'screen/analysis'/cid/'summary.json',dict(correction_status='available',failures=[dict(reason='one missing field')]))
            dump(root/'screen/analysis'/cid/'correction.json',correction)
            dump(root/'screen/analysis'/cid/'microscopy_scores.json',dict(ranking_native_minus_approximation_bias=.5,ranking_basis='native_partial_normalized'))
            result=dict(valid=True,loss=1e25,data_loss=1e25,assay_deviance=1.,ridge_penalty=0.,assays=[])
            with patch.object(refinement,'r',root),patch.object(refinement.a,'Data',return_value=fake_data()),patch.object(refinement.a,'evaluate',return_value=result) as evaluate,patch.object(refinement.signal,'signal'):
                refinement.run(0,seconds=0.)
            self.assertEqual(evaluate.call_count,1)
            value=json.loads((root/'refinement'/cid/'replicate_000/final.json').read_text())
            self.assertEqual(value['loss'],1e25);self.assertEqual(value['native_support_basis'],'native_partial_normalized');self.assertEqual(value['evaluations'],1)
            checkpoint=json.loads((root/'refinement'/cid/'replicate_000/checkpoint.json').read_text())
            self.assertEqual(checkpoint['candidate']['id'],'refined_screen0_r000');self.assertEqual(checkpoint['source_final_sha256'],digest);self.assertEqual(checkpoint['source_candidate_id'],cid);self.assertFalse(checkpoint['optimization_complete']);self.assertTrue(checkpoint['checkpoint_recovery_available']);self.assertIn('native_corrected_comparison_loss',checkpoint);self.assertIn('trust_region',checkpoint)
    def test_independent_starts_share_source_bounds_and_keep_distinct_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);cid='screen0';x=np.mean(refinement.a.BOUNDS,axis=1);x[:2]=.5;x[2]=np.log(1e-12)
            source=dict(x=x.tolist(),loss=1.,valid=True);dump(root/'screen_candidates.json',[dict(id=cid,alpha=0.,seed=7)])
            dump(root/'candidates'/cid/'final.json',source);dump(root/'screen/frozen'/cid/'final.json',source)
            digest=support.file_sha(root/'screen/frozen'/cid/'final.json');correction=dict(status='available',native_records=1,source_x=x.tolist(),source_sha256=digest)
            dump(root/'screen/analysis'/cid/'summary.json',dict(correction_status='available'));dump(root/'screen/analysis'/cid/'correction.json',correction);dump(root/'screen/analysis'/cid/'microscopy_scores.json',dict(ranking_native_minus_approximation_bias=.5))
            value=dict(valid=True,loss=1.,data_loss=1.,assay_deviance=1.,ridge_penalty=0.,assays=[])
            with patch.object(refinement,'r',root),patch.object(refinement.a,'Data',return_value=fake_data()),patch.object(refinement.a,'evaluate',return_value=value),patch.object(refinement.signal,'signal'):
                refinement.run(0,seconds=0.,replicate=0);refinement.run(0,seconds=0.,replicate=1)
                with self.assertRaisesRegex(RuntimeError,'attempt exists'):refinement.run(0,seconds=0.,replicate=1)
            records=[json.loads((root/'refinement'/cid/f'replicate_{rep:03}/final.json').read_text()) for rep in [0,1]]
            identities=[json.loads((root/'refinement'/cid/f'replicate_{rep:03}/attempt_identity.json').read_text()) for rep in [0,1]]
            self.assertNotEqual(records[0]['candidate']['id'],records[1]['candidate']['id']);self.assertEqual(records[0]['source_candidate_id'],records[1]['source_candidate_id'])
            self.assertEqual(identities[0]['lower_z'],identities[1]['lower_z']);self.assertEqual(identities[0]['upper_z'],identities[1]['upper_z'])
            self.assertEqual(identities[0]['initial_z'],identities[0]['source_z']);self.assertNotEqual(identities[0]['initial_z'],identities[1]['initial_z'])
            for record in records:
                lower=np.asarray(record['trust_region']['lower_z']);upper=np.asarray(record['trust_region']['upper_z']);actual=refinement.e.encode(np.asarray(record['x']))
                self.assertTrue(np.all(actual>=lower-1e-12));self.assertTrue(np.all(actual<=upper+1e-12));self.assertEqual(record['source_final_sha256'],digest)
    def test_missing_correction_skips_without_evaluation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);cid='screen0'
            dump(root/'screen_candidates.json',[dict(id=cid,alpha=0.,seed=7)]);dump(root/'candidates'/cid/'final.json',dict(x=[0.]*33,loss=1.,valid=True))
            with patch.object(refinement,'r',root),patch.object(refinement.a,'evaluate',side_effect=AssertionError('No unsupported evaluation')):
                refinement.run(0)
            self.assertEqual(json.loads((root/'refinement'/cid/'replicate_000/outcome.json').read_text())['status'],'skipped_unavailable_native_correction')


if __name__=='__main__':unittest.main()
