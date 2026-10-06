"""Portable checks using synthetic inputs only; no engine, project data or scheduler submission."""
import json,math,tempfile,unittest
from pathlib import Path
import numpy as np
from core.fitting import embed_branch_parameters,embed_rates,sigmoid_rate,medium_multiplier,composite_score,bounded_search
from core.spatial import measure,aggregate
from core.fields import colour_labels
from core.transfer import export_case
from submit_campaign import plan
from render_report import render
from test_campaign import CampaignTests


def report_fixture(root):
    from PIL import Image
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    for name,color in [('raw','gray'),('mask','blue'),('sim','green')]:Image.new('RGB',(80,60),color).save(root/(name+'.png'))
    models=['stationary','constant','adaptation']; candidates=[]
    for m in models:
        for i in range(2):
            loss=1+i*.03
            candidates.append(dict(id=m+str(i),group='lineage-alpha',stage=m,loss=loss,predicted=loss*.98,inherited=False,source_stage=m,
                components={'Count':loss/2,'Shape':loss/2},params={'Reference rate':dict(value=2+i,log=math.log10(2+i),unit='per day',section='kinetics'),
                'Radius':dict(value=10+i,log=math.log10(10+i),unit='px',section='shared')}))
    field=dict(id='field-a',group='lineage-alpha',arm='feed-A',passage=1,episode='episode-a',passage_id='acq-a',time=1.,tile='tile-a',
        raw_image='raw.png',mask_image='mask.png',raw_path='synthetic raw',mask_path='synthetic mask',raw_sha256='fixture',mask_sha256='fixture',observed={'visible_cells':1},
        simulations=[dict(stage=m,rank=1,candidate=m+'0',loss=1.,time=1.,image='sim.png',visible_cells=1,snapshot='synthetic snapshot',cells_sha256='fixture') for m in models])
    data=dict(title='Synthetic portability check',groups=[dict(id='lineage-alpha',label='Lineage alpha'),dict(id='lineage-beta',label='Lineage beta: no completed fits')],
        models=models,model_definitions={m:'Synthetic fixture model' for m in models},candidates=candidates,
        best={'lineage-alpha_'+m:m+'0' for m in models},component_names=['Count','Shape'],component_groups={'Morphology':['Shape']},
        growth=[dict(group='lineage-alpha',arm='feed-A',episode='episode-a',passage=1,condition_label='Declared condition',times=[0.,1.],observed=[10.,20.],passage_ids=['a','b'],simulations={m:[11.,19.] for m in models})],fields=[field],
        count_axis_label='Cells',default_cutoff_percent=5,descriptions={k:'Synthetic test convention.' for k in ['imageGeometry','imageSelection','lossDefinition','parameterTransforms']},
        protocol=['Synthetic test; no biological fit performed.'],compute_usage={'CPU-hours':'Not applicable: renderer test'})
    path=root/'fixture.json';path.write_text(json.dumps(data));return path

class PackageTests(unittest.TestCase):
    def test_nested_rates_for_arbitrary_branch_count(self):
        constant=embed_rates([2.],'stationary','constant',5)
        adaptive=embed_rates(constant,'constant','adaptation',5,midpoint=3,width=4)
        for e,l,m,w in adaptive:np.testing.assert_allclose(sigmoid_rate(np.arange(9),e,l,m,w),2.)
        self.assertAlmostEqual(float(medium_multiplier(7,7,3,2,1)),1.)
        self.assertAlmostEqual(float(sigmoid_rate(1,2,10,3,4)),2.8)
    def test_complete_branch_biology_embedding(self):
        stationary={'pressure_K':2.,'speed':40.,'death':.03}
        constant=embed_branch_parameters(stationary,'stationary','constant',5)
        for name,value in stationary.items():np.testing.assert_array_equal(constant[name],np.repeat(value,5))
        constant['pressure_K'][2]=7.
        adaptive=embed_branch_parameters(constant,'constant','adaptation',5)
        for name in constant:np.testing.assert_array_equal(adaptive[name],constant[name])
        adaptive['pressure_K'][2]=9.
        self.assertEqual(constant['pressure_K'][2],7.)
        with self.assertRaises(ValueError):embed_branch_parameters({'speed':[1.,2.]},'constant','adaptation',5)
        with self.assertRaises(ValueError):embed_branch_parameters({'speed':float('nan')},'stationary','constant',5)
    def test_scoring_floor_and_required_values(self):
        p=np.zeros((2,29));o=p.copy();p[:,2]=np.log(.2);o[:,2]=np.log(.5)
        w=np.zeros((2,5));w[:,3]=.5
        loss,offset,parts=composite_score(p,o,np.ones_like(p),w,[1/3,1/6,1/6,1/6,1/6],offset=0)
        self.assertEqual(loss,0);self.assertEqual(parts.sum(),loss)
        p[0,2]=np.nan
        with self.assertRaises(ValueError):composite_score(p,o,np.ones_like(p),w,[1/3,1/6,1/6,1/6,1/6],offset=0)
    def test_saturated_and_sparse_fields(self):
        binary=np.ones((140,140),bool);centers=np.array([[40,40],[90,90]])
        result=measure(binary,centers,np.array([20,20]));self.assertEqual(result['gap'],0);self.assertEqual(aggregate([result])[0][1],0)
        binary[65:75,65:75]=False;self.assertTrue(np.isfinite(measure(binary,centers,np.array([20,20]))['gap']))
        labels=np.ones((60,60),int);labels[:,30:]=2
        rgb,meta=colour_labels(labels,2);self.assertEqual(meta['coloring_conflicts'],0);self.assertFalse(np.array_equal(rgb[20,20],rgb[20,40]))
    def test_checkpoint_and_export_are_portable(self):
        import xml.etree.ElementTree as ET
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);result=bounded_search(lambda x:{'loss':float((x[0]-.3)**2)},[.8],[(0,1)],2,root/'best.json')
            self.assertLess(result['loss'],1e-8)
            p=[.85,100,1,8,1e-4,2,1,.5]
            export_case(root/'case',p,2.,123,[0,.7],(200,160),post_g1_minutes=1440.,death_per_day=0)
            xml=ET.parse(root/'case/PhysiCell_settings.xml');base='cell_definitions/cell_definition/phenotype/'
            self.assertEqual(float(xml.find(base+'death/model[@code="100"]/death_rate').text),0)
            self.assertAlmostEqual(float(xml.find(base+'cycle/phase_durations/duration[@index="1"]').text),480*1440/780)
            self.assertEqual(np.loadtxt(root/'case/sample_times.txt')[-1],1.)
    def test_scheduler_cpu_cap_and_dependencies(self):
        spec={'max_cpus':7,'nodes':[dict(name='fit',cwd='.',command=['python','adapter.py','fit'],minutes=5,tasks=31),dict(name='sim',cwd='.',command=['python','adapter.py','sim'],minutes=10,tasks=70,depends_on='fit',condition='afterany')]}
        nodes=plan(spec,Path('/tmp/unused-plan'))
        self.assertIn('--array=0-30%7',nodes[0]['command']);self.assertEqual(nodes[1]['condition'],'afterany')
        spec['nodes'][1]['depends_on']=None
        with self.assertRaises(ValueError):plan(spec,Path('/tmp/unused-plan'))
    def test_report_packaging_and_invalid_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=report_fixture(root/'inputs');html=render(data,root/'report')
            self.assertTrue(html.exists());self.assertTrue((html.parent/'assets/plotly.min.js').is_file());self.assertTrue((html.parent/'raw.png').is_file())
            d=json.loads(data.read_text());d['candidates'][0]['loss']=20;data.write_text(json.dumps(d))
            with self.assertRaises(ValueError):render(data,root/'bad')

if __name__=='__main__':unittest.main()
