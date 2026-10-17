"""Run-local two-state exporter and bounded standalone PhysiCell execution."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
from scipy.io import loadmat

from core.colony import BASE, init_volume
from core.transfer import snapshot
import native_support as support

ASSET_ROOT=Path(__file__).resolve().parents[1]/"assets/perspective"
ENGINE=None


def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(value,indent=2,allow_nan=False)+"\n");temp.replace(path)


def mixed_equilibrium(low,high,fraction):
    speed=np.array([low[1],high[1]],float)
    spacing=np.array([low[0],high[0]],float)
    weight=np.array([1-fraction,fraction])*np.sqrt(speed)
    c=(1-spacing)/(1-spacing/1.25)
    theta=float(np.sum(weight*c)/np.sum(weight))
    return (1-theta)/(1-theta/1.25)


def initial_spacing_native(f_low,r_low,r_high,low,high):
    c_low=(1-low[0])/(1-low[0]/1.25);c_high=(1-high[0])/(1-high[0]/1.25)
    lo=0.;hi=2.5*max(r_low,r_high)
    for iteration in range(50):
        distance=(lo+hi)/2;force=0.
        for radius,strength,adhesion,weight in [(2*r_low,low[1],c_low*c_low,f_low*f_low),
                    (r_low+r_high,np.sqrt(low[1]*high[1]),c_low*c_high,2*f_low*(1-f_low)),
                    (2*r_high,high[1],c_high*c_high,(1-f_low)**2)]:
            overlap=max(0.,1-distance/max(radius,1e-30));attraction=max(0.,1-distance/max(1.25*radius,1e-30))
            force+=weight*strength*(overlap*overlap-adhesion*attraction*attraction)
        if force>0:lo=distance
        else:hi=distance
    return (lo+hi)/2


def initial_state(p_low,p_high,density,f_high,cluster_size,seed,domain_size,post_g1_minutes=780,
                  initial_dead_low_fraction=0.,initial_dead_high_fraction=0.):
    low,high=np.asarray(p_low,float),np.asarray(p_high,float)
    if low.shape!=(8,) or high.shape!=(8,) or not 0<=f_high<=1 or density<=0 or cluster_size<1:
        raise ValueError("Invalid two-state initialization")
    width,height=domain_size;rng=np.random.default_rng(seed)
    fd=np.array([initial_dead_low_fraction,initial_dead_high_fraction],float)
    if min(fd)<0 or max(fd)>=1:raise ValueError('Invalid state-specific initial dead fraction')
    total_high=f_high*(1-fd[0])/((1-f_high)*(1-fd[1])+f_high*(1-fd[0]))
    number=max(1,round(density*width*height))
    # Independent state draws; never round an expected state count.
    # Together with state-dependent dead draws, living labels conditional on
    # the living count follow Binomial(N_live, f_high).
    state=(rng.random(number)<total_high).astype(int)
    n_high=int(state.sum())
    parameters=np.vstack([low,high]);fg=parameters[state,7]
    cycling=rng.random(number)>fg;age=rng.uniform(0,post_g1_minutes,number);age[~cycling]=0
    lengths=np.array([480.,240.,60.])*post_g1_minutes/780.
    phase=np.zeros(number,int);elapsed=np.zeros(number);volumes=np.zeros((number,3))
    for index in range(number):
        radius=parameters[state[index],3];multiplier=parameters[state[index],6];v0=4*np.pi*radius**3/3
        volumes[index]=init_volume(age[index]/1440,multiplier)*v0 if cycling[index] else BASE*multiplier*v0
        if cycling[index]:
            phase[index]=1+int(age[index]>=lengths[0])+int(age[index]>=lengths[:2].sum())
            elapsed[index]=age[index]-[0,0,lengths[0],lengths[:2].sum()][phase[index]]
    dead=rng.random(number)<fd[state]
    radii=(volumes.sum(axis=1)*3/(4*np.pi))**(1/3)
    mean_radius=float(np.mean(radii))
    equilibrium=mixed_equilibrium(low,high,n_high/number)
    r_low=float(np.mean(radii[state==0])) if (state==0).any() else low[3]*low[6]**(1/3)
    r_high=float(np.mean(radii[state==1])) if (state==1).any() else high[3]*high[6]**(1/3)
    spacing=initial_spacing_native(1-n_high/number,r_low,r_high,low,high)
    centers=min(number,max(1,round(number/cluster_size)));sizes=np.full(centers,number//centers);sizes[:number%centers]+=1;rng.shuffle(sizes)
    positions=[]
    for size in sizes:
        bound=int(np.ceil(np.sqrt(size)))+1;q,z=np.mgrid[-bound:bound+1,-bound:bound+1]
        xx=(q+z/2).ravel();yy=(z*np.sqrt(3)/2).ravel();pick=np.argsort(xx**2+yy**2,kind="stable")[:size]
        xx=xx[pick]*spacing;yy=yy[pick]*spacing;angle=rng.uniform(0,2*np.pi);cx=rng.uniform(-width/2,width/2);cy=rng.uniform(-height/2,height/2)
        positions.append(np.column_stack([(cx+xx*np.cos(angle)-yy*np.sin(angle)+width/2)%width-width/2,
                                           (cy+xx*np.sin(angle)+yy*np.cos(angle)+height/2)%height-height/2]))
    positions=np.vstack(positions);rng.shuffle(positions)
    cells=pd.DataFrame(dict(x=positions[:,0],y=positions[:,1],state=state,phase=phase,elapsed=elapsed,
                            nuclear_solid=volumes[:,0],cytoplasmic_solid=volumes[:,1],fluid=volumes[:,2],
                            dead=dead.astype(int),dead_age_minutes=np.zeros(number)))
    live_low=int(np.sum((state==0)&~dead));live_high=int(np.sum((state==1)&~dead))
    return cells,dict(cells=number,n_low=live_low,n_high=live_high,n_dead_low=int(np.sum((state==0)&dead)),
                      n_dead_high=int(np.sum((state==1)&dead)),inherited_live_high_fraction=float(f_high),
                      initial_total_high_fraction=float(total_high),realized_total_high_fraction=n_high/number,
                      initial_high_fraction=live_high/max(live_low+live_high,1),initial_dead_age_minutes=0.,
                      state_assignment="independent_Bernoulli_total_state_then_state_specific_dead",centers=centers,mean_radius=mean_radius,mixed_equilibrium=equilibrium,initial_spacing_pixels=spacing)


def export_case(directory,spec,initial_override=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False);(directory/"output").mkdir()
    width,height=spec["domain_size"]
    low=np.asarray(spec["p_low"],float);high=np.asarray(spec["p_high"],float)
    mechanics=spec.get("mechanics_minutes",.5);phenotype=spec.get("phenotype_minutes",3.)
    times=np.unique(np.ceil(np.asarray(spec["times_days"],float)*1440/mechanics)*mechanics)
    if not len(times) or times.min()<0:raise ValueError("Invalid sampling times")
    cells,metadata=initial_state(low,high,spec["initial_density"],spec["initial_high_fraction"],spec["cluster_size"],
                                 spec["seed"],spec["domain_size"],spec.get("post_g1_minutes",780),
                                 spec.get('initial_dead_low_fraction',0.),spec.get('initial_dead_high_fraction',0.))
    if initial_override is not None:
        cells=initial_override.copy()
        if 'dead' not in cells:cells['dead']=0
        if 'dead_age_minutes' not in cells:cells['dead_age_minutes']=0.
        cells=cells[['x','y','state','phase','elapsed','nuclear_solid','cytoplasmic_solid','fluid','dead','dead_age_minutes']]
        metadata.update(cells=len(cells),n_low=int(((cells.state==0)&(cells.dead==0)).sum()),n_high=int(((cells.state==1)&(cells.dead==0)).sum()),
                        n_dead_low=int(((cells.state==0)&(cells.dead!=0)).sum()),n_dead_high=int(((cells.state==1)&(cells.dead!=0)).sum()))
    cells.to_csv(directory/"initial_cells.csv",index=False);np.savetxt(directory/"sample_times.txt",times,fmt="%.8f")
    tree=ET.parse(ASSET_ROOT/"physicell/PhysiCell_settings.xml");root=tree.getroot()
    def put(path,value):root.find(path).text=str(value)
    for path,value in [("domain/x_min",-width/2),("domain/x_max",width/2),("domain/y_min",-height/2),("domain/y_max",height/2),
                       ("overall/max_time",float(times.max()+mechanics)),("overall/dt_diffusion",mechanics),
                       ("overall/dt_mechanics",mechanics),("overall/dt_phenotype",phenotype),("parallel/omp_num_threads",1),
                       ("options/random_seed",spec["seed"]),("options/virtual_wall_at_domain_edge","true")]:put(path,value)
    definitions=root.find("cell_definitions");default=definitions[0];other=copy.deepcopy(default)
    other.set("name","wgd_high");other.set("ID","1");definitions.append(other)
    for index,(definition,p,rate) in enumerate(zip([default,other],[low,high],[spec["rate_low"],spec["rate_high"]])):
        phenotype_node=definition.find("phenotype")
        def state_put(path,value):phenotype_node.find(path).text=str(value)
        if rate<=0:raise ValueError("G1 rate must be positive")
        state_put('cycle/phase_durations/duration[@index="0"]',1440/rate)
        for phase,minutes in enumerate([480.,240.,60.],1):state_put(f'cycle/phase_durations/duration[@index="{phase}"]',minutes*spec.get("post_g1_minutes",780)/780)
        suffix='high' if index else 'low'
        state_put('death/model[@code="100"]/death_rate',spec.get(f'background_death_{suffix}_per_day',spec.get("background_death_per_day",.076560048))/1440)
        state_put('death/model[@code="100"]/phase_durations/duration[@index="0"]',60*spec.get(f'dead_duration_{suffix}_hours',8.6))
        v0=4*np.pi*p[3]**3/3;state_put("volume/total",v0);state_put("volume/nuclear",v0*540/2494)
        state_put("mechanics/cell_cell_repulsion_strength",p[1]/1440)
        state_put("mechanics/cell_cell_adhesion_strength",p[1]/1440*((1-p[0])/(1-p[0]/1.25))**2)
        affinities=phenotype_node.find("mechanics/cell_adhesion_affinities");affinities.clear()
        for name in ["default","wgd_high"]:ET.SubElement(affinities,"cell_adhesion_affinity",name=name).text="1"
    user=root.find("user_parameters")
    for name,kind,value in [("wgd_interception_enabled","bool",str(spec.get("interception_enabled",True)).lower()),
                            ("wgd_probability","double",spec["wgd_probability"]),("mitotic_death_low","double",spec["mitotic_death_low"]),
                            ("mitotic_death_high","double",spec["mitotic_death_high"])]:ET.SubElement(user,name,type=kind).text=str(value)
    for state in ['low','high']:
        ET.SubElement(user,f'dead_duration_{state}_minutes',type='double').text=str(60*spec.get(f'dead_duration_{state}_hours',8.6))
    put("user_parameters/mechanics_voxel_size",max(40,max(2.5*p[3]*(2*max(1,p[6]))**(1/3)+5 for p in [low,high])))
    tree.write(directory/"PhysiCell_settings.xml",encoding="utf-8",xml_declaration=True)
    (directory/"cell_rules.csv").write_text(f"default,pressure,decreases,cycle entry,0,{low[2]:.17g},2,0\nwgd_high,pressure,decreases,cycle entry,0,{high[2]:.17g},2,0\n")
    atomic_json(directory/"case_spec.json",spec)
    return metadata,times


def read_cells(xml):
    xml=Path(xml);root=ET.parse(xml).getroot();nodes=root.findall(".//simplified_data/labels/label") or root.findall(".//labels/label")
    labels={node.text:int(node.attrib["index"]) for node in nodes}
    return loadmat(xml.with_name(xml.stem+"_cells.mat"))["cells"],labels


def read_trajectory(path):
    """Retain complete numeric rows when the engine leaves a truncated CSV tail."""
    frame=pd.read_csv(path)
    required=['time_minutes','n_low','n_high','n_dead_low','n_dead_high','wgd_events']
    if any(key not in frame for key in required):raise ValueError('Invalid native trajectory schema')
    values=frame[required].apply(pd.to_numeric,errors='coerce').to_numpy(float)
    keep=np.isfinite(values).all(axis=1)&(values>=0).all(axis=1)
    frame=frame.loc[keep].copy()
    if frame.empty:raise ValueError('No complete native trajectory rows')
    frame[required]=values[keep]
    if np.any(np.diff(frame.time_minutes.to_numpy())<0):raise ValueError('Native trajectory times are not ordered')
    denominator=frame.n_low+frame.n_high
    frame['f_high']=np.divide(frame.n_high,denominator,out=np.full(len(frame),np.nan),where=denominator>0)
    return frame


def execute(directory,spec,timeout_seconds=600,initial_override=None,pair_check=False,measure=True):
    directory=Path(directory);start=time.monotonic();outcome=dict(status='failure',engine_status='not_started',requested_times_days=spec['times_days'])
    try:
        metadata,times=export_case(directory,spec,initial_override)
        command=[str(ENGINE),'PhysiCell_settings.xml']
        if pair_check:command.append('--pair-check')
        outcome.update(initial=metadata,sample_times_minutes=times.tolist(),engine_status='failed')
        try:
            with open(directory/'engine.log','w') as log:
                result=subprocess.run(command,cwd=directory,stdout=log,stderr=subprocess.STDOUT,timeout=timeout_seconds,
                                      env={**os.environ,'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
            outcome['engine_returncode']=result.returncode
            if result.returncode:outcome['error']=f'Engine exit {result.returncode}'
            else:outcome['engine_status']='complete'
        except subprocess.TimeoutExpired as error:outcome.update(engine_status='timed_out',error=f'{type(error).__name__}: {error}')
        except OSError as error:outcome['error']=f'{type(error).__name__}: {error}'
        if pair_check:
            outcome['status']='success' if outcome['engine_status']=='complete' else 'failure'
        else:
            trajectory=None
            try:
                trajectory=read_trajectory(directory/'state_trajectory.csv')
                trajectory.to_csv(directory/'state_trajectory.csv',index=False)
                outcome.update(trajectory_rows=len(trajectory),trajectory_first_time_minutes=float(trajectory.time_minutes.iloc[0]),trajectory_last_time_minutes=float(trajectory.time_minutes.iloc[-1]),terminal_low=int(trajectory.n_low.iloc[-1]),terminal_high=int(trajectory.n_high.iloc[-1]),terminal_dead_low=int(trajectory.n_dead_low.iloc[-1]),terminal_dead_high=int(trajectory.n_dead_high.iloc[-1]))
            except (OSError,ValueError,pd.errors.ParserError) as error:outcome['trajectory_error']=repr(error)
            all_measured=not measure;any_measured=False
            if measure:
                values,available,records,parse_errors=support.measure_requested(directory/'output',times,lambda path:snapshot(path,spec['domain_size'],spec['field_shape'],spec['crop_origin']))
                np.savez_compressed(directory/'observables.npz',times_minutes=times,predicted=values,requested_time_support=available,f_high=trajectory.f_high.to_numpy() if trajectory is not None else np.array([]))
                outcome.update(snapshots=records,snapshot_parse_errors=parse_errors,requested_snapshots=len(times),measured_snapshots=int(available.sum()))
                all_measured=bool(available.all()) and bool(np.isfinite(values).all());any_measured=bool(available.any())
            endpoint_available=trajectory is not None and abs(float(trajectory.time_minutes.iloc[-1])-float(times[-1]))<=.500001
            outcome['requested_terminal_time_available']=bool(endpoint_available)
            complete=outcome['engine_status']=='complete' and endpoint_available and all_measured
            outcome['status']='success' if complete else 'partial' if any_measured or trajectory is not None else 'failure'
    except Exception as error:outcome['error']=f'{type(error).__name__}: {error}'
    outcome['wall_seconds']=time.monotonic()-start;outcome['peak_rss_kib']=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    atomic_json(directory/'outcome.json',outcome)
    return outcome
