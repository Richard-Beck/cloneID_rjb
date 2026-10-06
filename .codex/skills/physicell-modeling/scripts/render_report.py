"""Package an offline report from the generic data contract and pre-rendered local image assets."""
import argparse,csv,json,math,shutil
from pathlib import Path
from plotly.offline import get_plotlyjs

def local_path(value):
    p=Path(value)
    if p.is_absolute() or '..' in p.parts or ':' in value or not value:raise ValueError('Report asset must be a relative path: '+value)
    return p

def validate(d,assets):
    required=['title','groups','models','model_definitions','candidates','best','growth','fields','component_names','component_groups','count_axis_label','descriptions','protocol','compute_usage']
    for key in required:
        if key not in d:raise ValueError('Missing report field: '+key)
    groups=[g['id'] for g in d['groups']]
    if not groups or len(set(groups))!=len(groups):raise ValueError('Unique nonempty groups required')
    if not d['models'] or len(set(d['models']))!=len(d['models']):raise ValueError('Unique nonempty stages required')
    for m in d['models']:
        if any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_-' for c in m):raise ValueError('Unsafe stage identifier')
        if m not in d['model_definitions']:raise ValueError('Missing model definition')
    keys=set()
    for c in d['candidates']:
        key=(c['group'],c['stage'],c['id'])
        if key in keys:raise ValueError('Duplicate candidate key')
        keys.add(key)
        if c['group'] not in groups or c['stage'] not in d['models']:raise ValueError('Unknown candidate group/stage')
        if not math.isfinite(c['loss']) or c['loss']<0:raise ValueError('Invalid candidate loss')
        if any(n not in c['components'] for n in d['component_names']):raise ValueError('Missing loss component')
        if not math.isclose(sum(c['components'].values()),c['loss'],rel_tol=1e-9,abs_tol=1e-10):raise ValueError('Component losses do not sum to total')
        if any(not math.isfinite(v) or v<0 for v in c['components'].values()):raise ValueError('Invalid component loss')
        for p in c['params'].values():
            if not math.isfinite(p['log']) or not math.isfinite(p['value']):raise ValueError('Nonfinite parameter')
    for g in groups:
        for m in d['models']:
            pool=[c for c in d['candidates'] if c['group']==g and c['stage']==m]
            expected=min(pool,key=lambda c:(c['loss'],c['id']))['id'] if pool else None
            if d['best'].get(g+'_'+m)!=expected:raise ValueError('Incorrect stage winner')
    for f in d['fields']:
        for name in ('raw_image','mask_image'):
            if not (assets/local_path(f[name])).is_file():raise FileNotFoundError(f[name])
        for s in f['simulations']:
            if not (assets/local_path(s['image'])).is_file():raise FileNotFoundError(s['image'])
            if (f['group'],s['stage'],s['candidate']) not in keys:raise ValueError('Field references unknown candidate')
    for g in d['growth']:
        n=len(g['times'])
        if len(g['observed'])!=n or len(g['passage_ids'])!=n:raise ValueError('Growth lengths differ')
        if any(len(v)!=n for v in g['simulations'].values()):raise ValueError('Growth prediction lengths differ')
        metrics=g.get('metrics',{})
        for values in [metrics.get('observed',{}),*metrics.get('simulations',{}).values()]:
            for name,series in values.items():
                if name not in ('coverage','gap','clark_evans','area_quantiles'):raise ValueError('Unknown passage metric: '+name)
                if len(series)!=n:raise ValueError('Passage metric lengths differ')
                for value in series:
                    if value is None:continue
                    if name=='area_quantiles':
                        if not isinstance(value,list) or len(value)!=5:raise ValueError('Expected five area quantiles')
                        if all(x is None for x in value):continue
                        if any(x is None or not math.isfinite(x) for x in value) or value!=sorted(value):raise ValueError('Invalid area quantiles')
                    elif not math.isfinite(value):raise ValueError('Nonfinite passage metric')
    for item in d.get('links',[]):local_path(item['href'])
    for names in d['component_groups'].values():
        if any(n not in d['component_names'] for n in names):raise ValueError('Unknown grouped loss component')
    for key in ('imageGeometry','imageSelection','lossDefinition','parameterTransforms'):
        if key not in d['descriptions']:raise ValueError('Missing description: '+key)

def render(data_path,output):
    data_path=Path(data_path).resolve();output=Path(output).resolve();d=json.loads(data_path.read_text())
    validate(d,data_path.parent);payload=json.dumps(d,allow_nan=False).replace('</','<\\/')
    assets=Path(__file__).resolve().parents[1]/'assets/report'
    output.mkdir(parents=True,exist_ok=True);(output/'assets').mkdir(exist_ok=True)
    files={f[k] for f in d['fields'] for k in ('raw_image','mask_image')}
    files.update(s['image'] for f in d['fields'] for s in f['simulations'])
    files.update(i['href'] for i in d.get('links',[]))
    for value in sorted(files):
        rel=local_path(value);src=data_path.parent/rel;dest=output/rel
        if not src.is_file():raise FileNotFoundError(src)
        dest.parent.mkdir(parents=True,exist_ok=True)
        if src.resolve()!=dest.resolve():shutil.copy2(src,dest)
    for name in ('report.js','report.css'):shutil.copy2(assets/name,output/'assets'/name)
    (output/'assets/plotly.min.js').write_text(get_plotlyjs())
    (output/'REPORT.html').write_text((assets/'template.html').read_text().replace('@@REPORT_DATA@@',payload))
    (output/'data.json').write_text(json.dumps(d,indent=2,allow_nan=False)+'\n')
    with (output/'loss_components.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['group','stage','id','loss']+d['component_names']);writer.writeheader()
        for c in d['candidates']:writer.writerow({**{k:c[k] for k in ('group','stage','id','loss')},**c['components']})
    (output/'REPORT.md').write_text('# PhysiCell modeling report\n\n[Open the interactive report](REPORT.html). Keep this folder and its assets together when sharing.\n')
    return output/'REPORT.html'

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('data');ap.add_argument('output');args=ap.parse_args();print(render(args.data,args.output))
