"""Frozen-vector transfer and full-disk observation operators used by the current baseline."""
import json
import numpy as np,pandas as pd
from pathlib import Path
import xml.etree.ElementTree as ET
from scipy.io import loadmat
from skimage.draw import disk
from .colony import init_volume,BASE
from .spatial import measure,aggregate

def initial(p,seed,domain_size,post_g1_minutes=780.):
 W,H=domain_size
 phase_lengths=np.array([480.,240.,60.])*post_g1_minutes/780.
 xeq,speed,K,r0,rho0,m0,vinit,fG=p;rng=np.random.default_rng(seed);N=max(1,round(rho0*W*H));C=min(N,max(1,round(N/m0)))
 cycling=rng.random(N)>fG;age=rng.uniform(0,post_g1_minutes,N);age[~cycling]=0
 phase=np.zeros(N,dtype=int);elapsed=np.zeros(N);vol=np.zeros((N,3));V0=4*np.pi*r0**3/3
 for i in range(N):
  vol[i]=init_volume(age[i]/1440,vinit)*V0 if cycling[i] else BASE*vinit*V0
  if cycling[i]:
   phase[i]=1+int(age[i]>=phase_lengths[0])+int(age[i]>=phase_lengths[:2].sum());elapsed[i]=age[i]-[0,0,phase_lengths[0],phase_lengths[:2].sum()][phase[i]]
 rbar=np.mean((vol.sum(axis=1)*3/(4*np.pi))**(1/3));spacing=2*rbar*xeq
 sizes=np.full(C,N//C);sizes[:N%C]+=1;rng.shuffle(sizes);positions=[]
 for size in sizes:
  bound=int(np.ceil(np.sqrt(size)))+1;q,z=np.mgrid[-bound:bound+1,-bound:bound+1]
  xx=(q+z/2).ravel();yy=(z*np.sqrt(3)/2).ravel();pick=np.argsort(xx**2+yy**2,kind='stable')[:size]
  xx=xx[pick]*spacing;yy=yy[pick]*spacing;ang=rng.uniform(0,2*np.pi);cx=rng.uniform(-W/2,W/2);cy=rng.uniform(-H/2,H/2)
  positions.append(np.column_stack([(cx+xx*np.cos(ang)-yy*np.sin(ang)+W/2)%W-W/2,(cy+xx*np.sin(ang)+yy*np.cos(ang)+H/2)%H-H/2]))
 pos=np.vstack(positions);rng.shuffle(pos)
 return pd.DataFrame(dict(x=pos[:,0],y=pos[:,1],phase=phase,elapsed=elapsed,nuclear_solid=vol[:,0],cytoplasmic_solid=vol[:,1],fluid=vol[:,2])),dict(cells=N,centers=C,mean_radius=rbar,mean_cluster=N/C)

def snapshot(path,domain_size,field_shape,crop_origin):
 path=Path(path);W,H=domain_size;FH,FW=field_shape;CROP_X,CROP_Y=crop_origin
 root=ET.parse(path).getroot();labels={l.text:(int(l.attrib['index']),int(l.attrib['size'])) for l in root.findall('.//simplified_data/labels/label')}
 if not labels:labels={l.text:(int(l.attrib['index']),int(l.attrib['size'])) for l in root.findall('.//labels/label')}
 data=loadmat(path.with_name(path.stem+'_cells.mat'))['cells'];pos=labels['position'][0];vi=labels['total_volume'][0]
 live=np.ones(data.shape[1],dtype=bool)
 if 'dead' in labels:live=data[labels['dead'][0]]==0
 else:live=data[labels['current_phase'][0]]<100
 x,y=data[pos,live],data[pos+1,live];rad=(data[vi,live]*3/(4*np.pi))**(1/3)
 fields=[];dens=[]
 for x0,y0 in [(CROP_X,CROP_Y)]:
  near=(x+rad>=x0)&(x-rad<x0+FW)&(y+rad>=y0)&(y-rad<y0+FH)
  canvas=np.zeros((FH,FW),dtype=bool)
  for xx,yy,rr in zip(x[near]-x0,y[near]-y0,rad[near]):
   row,col=disk((yy,xx),rr,shape=canvas.shape);canvas[row,col]=True
  sel=(x>=x0)&(x<x0+FW)&(y>=y0)&(y<y0+FH)
  centers=np.column_stack([x[sel]-x0,y[sel]-y0]);fields.append(measure(canvas,centers,np.pi*rad[sel]**2));dens.append(sel.sum()/(FW*FH))
 val,se=aggregate(fields)
 return np.r_[np.log(np.mean(dens)),val],dict(live_cells=int(live.sum()),global_density=float(live.sum()/(W*H)),field_density=float(np.mean(dens)))

def export_case(directory, p, rate, seed, times, domain_size, post_g1_minutes=780., death_per_day=.076560048, mechanics_minutes=.5, phenotype_minutes=3.):
    W,H=domain_size
    p=np.asarray(p,float)
    times=np.unique(np.ceil(np.asarray(times,float)/mechanics_minutes)*mechanics_minutes)
    if len(times)==0 or times.min()<0 or rate<=0:raise ValueError("Invalid rate/sample times")
    d=Path(directory);d.mkdir(parents=True,exist_ok=False);(d/'output').mkdir()
    ic,meta=initial(p,seed,domain_size,post_g1_minutes);ic.to_csv(d/'initial_cells.csv',index=False)
    np.savetxt(d/'sample_times.txt',times,fmt='%.8f')
    tree=ET.parse(Path(__file__).resolve().parents[2]/'assets/physicell/PhysiCell_settings.xml');root=tree.getroot()
    def put(k,v):root.find(k).text=str(v)
    for k,v in [('domain/x_min',-W/2),('domain/x_max',W/2),('domain/y_min',-H/2),('domain/y_max',H/2),
                ('overall/dt_diffusion',mechanics_minutes),('overall/dt_mechanics',mechanics_minutes),('overall/dt_phenotype',phenotype_minutes),
                ('overall/max_time',max(times)+mechanics_minutes),('parallel/omp_num_threads',1),('options/random_seed',seed),
                ('options/virtual_wall_at_domain_edge','true')]:put(k,v)
    ph='cell_definitions/cell_definition/phenotype/';v0=4*np.pi*p[3]**3/3
    put(ph+'cycle/phase_durations/duration[@index="0"]',1440/rate)
    for i,minutes in enumerate((480.,240.,60.),1):put(ph+f'cycle/phase_durations/duration[@index="{i}"]',minutes*post_g1_minutes/780.)
    put(ph+'death/model[@code="100"]/death_rate',death_per_day/1440)
    put(ph+'volume/total',v0);put(ph+'volume/nuclear',v0*540/2494)
    put(ph+'mechanics/cell_cell_repulsion_strength',p[1]/1440)
    put(ph+'mechanics/cell_cell_adhesion_strength',p[1]/1440*((1-p[0])/(1-p[0]/1.25))**2)
    put('user_parameters/mechanics_voxel_size',max(40,2.5*p[3]*(2*max(1,p[6]))**(1/3)+5))
    tree.write(d/'PhysiCell_settings.xml',encoding='utf-8',xml_declaration=True)
    (d/'cell_rules.csv').write_text(f'default,pressure,decreases,cycle entry,0,{p[2]:.17g},2,0\n')
    return meta
