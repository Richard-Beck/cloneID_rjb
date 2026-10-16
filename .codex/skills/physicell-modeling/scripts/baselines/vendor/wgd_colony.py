"""Expected-outcome two-state colony, days/pixels; native symmetric mechanics.

Two distinct high-state G1 arrival cohorts are retained at each time step:
ordinary daughters and full-volume WGD mothers. The shared envelope and founder
count do not acquire a new founder on conversion. Background death is separate.
"""
import numpy as np
from numba import njit
from core.colony import BASE, DEAD_RATES, update_volume, init_volume

TRACE_NAMES = ['time_days','n_live_low','n_live_high','fraction_high_live','radius_envelope',
               'radius_low_pooled','radius_high_pooled','spacing','pressure_low','pressure_high',
               'mitotic_death_low','mitotic_death_high','wgd_events',
               'low_divisions','high_divisions','g1_rate_low','g1_rate_high',
               'n_dead_low','n_dead_high','background_death_low','background_death_high',
               'n_total_retained','radius_pooled']

@njit(cache=True)
def outcome_counts(ml,mh,dl,dh,w):
    ld=(1-dl)*(1-w)*ml; wg=(1-dl)*w*ml; hd=(1-dh)*mh
    return 2*ld,2*hd,wg,dl*ml,dh*mh

@njit(cache=True)
def state_moments(g,gv,q,qv,ng,r0):
    n=0.; rad=0.
    for j in range(ng):
        n+=g[j];rad+=g[j]*r0*max(1e-15,gv[j].sum())**(1/3)
    for j in range(len(q)):
        n+=q[j];rad+=q[j]*r0*max(1e-15,qv[j].sum())**(1/3)
    return n,rad/max(n,1e-30)

@njit(cache=True)
def mixed_geometry(R,nl,nh,rl,rh,c0,xl,xh,sl,sh):
    n=nl+nh;fl=nl/max(n,1e-30);fh=1-fl
    eta=c0*np.pi*R*R;u=max(-np.expm1(-eta),1e-15)
    L=u*np.exp(min(eta,80))/(c0*np.pi*R)
    rho=n/u;d=np.sqrt(2/(np.sqrt(3)*rho));ne=max(1.,rho*np.pi*L*L)
    z=max(0.,min(ne-1,6-2*np.sqrt(12*ne-3)/ne))
    radii=np.array([2*rl,rl+rh,2*rh]);strength=np.array([sl,np.sqrt(sl*sh),sh])
    cl=(1-xl)/(1-xl/1.25);ch=(1-xh)/(1-xh/1.25)
    adhesion=np.array([cl*cl,cl*ch,ch*ch]);force=np.zeros(3);ov2=np.zeros(3)
    for j in range(3):
        ov=max(0.,1-d/max(radii[j],1e-30));a=max(0.,1-d/max(1.25*radii[j],1e-30))
        ov2[j]=ov*ov;force[j]=strength[j]*(ov*ov-adhesion[j]*a*a)
    pl=z*(fl*ov2[0]+fh*ov2[1])/.027288820670331
    ph=z*(fl*ov2[1]+fh*ov2[2])/.027288820670331
    rhs=z*d*(fl*fl*force[0]+2*fl*fh*force[1]+fh*fh*force[2])/L
    return u,d,pl,ph,rhs

@njit(cache=True)
def initial_spacing(fl,rl,rh,xl,xh,sl,sh):
    lo=0.;hi=2.5*max(rl,rh)
    cl=(1-xl)/(1-xl/1.25);ch=(1-xh)/(1-xh/1.25)
    for _ in range(50):
        d=(lo+hi)/2;f=0.
        for r,s,a,pair in ((2*rl,sl,cl*cl,fl*fl),(rl+rh,np.sqrt(sl*sh),cl*ch,2*fl*(1-fl)),(2*rh,sh,ch*ch,(1-fl)**2)):
            ov=max(0.,1-d/max(r,1e-30));av=max(0.,1-d/max(1.25*r,1e-30))
            f+=pair*s*(ov*ov-a*av*av)
        if f>0:lo=d
        else:hi=d
    return (lo+hi)/2

@njit(cache=True)
def initial_total_high_fraction(live_high, dead_low, dead_high):
    """Retain inherited living fraction at fixed TOTAL seeded density."""
    return live_high*(1-dead_low)/((1-live_high)*(1-dead_high)+live_high*(1-dead_low))

@njit(cache=True)
def retained_moments(g,gv,q,qv,ng,dead,dv,nd,r0):
    live,rad=state_moments(g,gv,q,qv,ng,r0);n_dead=0.;radius_sum=live*rad
    for j in range(nd):
        if dead[j]>0:
            n_dead+=dead[j];radius_sum+=dead[j]*r0*max(dv[j].sum(),1e-300)**(1/3)
    return live,n_dead,radius_sum/max(live+n_dead,1e-300)

@njit(cache=True)
def mixture_area(g,gv,q,qv,ng,r0,h,hv,qh,qhv,nh,rh,dl,dlv,dh,dhv,nd):
    a=np.empty(ng+len(q)+nh+len(qh)+2*nd);weights=np.empty(len(a));k=0
    for pop,vol,size,rad in ((g,gv,ng,r0),(q,qv,len(q),r0),(h,hv,nh,rh),(qh,qhv,len(qh),rh),(dl,dlv,nd,r0),(dh,dhv,nd,rh)):
        for j in range(size):
            if pop[j]>0:
                a[k]=rad*rad*max(vol[j].sum(),1e-300)**(2/3);weights[k]=pop[j];k+=1
    if k==0:return np.full(25,np.nan)
    a=a[:k];weights=weights[:k];order=np.argsort(a);a=a[order];weights=weights[order]
    av=np.empty(k);wv=np.empty(k);n=0
    for j in range(k):
        if n>0 and abs(a[j]-av[n-1])<=1e-12*max(a[j],1.):wv[n-1]+=weights[j]
        else:av[n]=a[j];wv[n]=weights[j];n+=1
    av=av[:n];wv=wv[:n];mean=np.sum(av*wv)/np.sum(wv);cdf=np.cumsum(wv)/np.sum(wv)
    return np.log(np.interp(np.arange(.02,1.,.04),cdf,av)/mean)

@njit(cache=True)
def simulate_two_state(pl,ph,lam_l,lam_h,rho0,m0,fhigh,w,dl,dh,times,dt=1/240,T=13/24,observation_area=1540000.):
    """State9=xeq,speed,K,r0,vinit,fG,mu,tau_hours,fD; fhigh is LIVING.

    Death is absorbing; M-death precedes WGD and retains full mother volume.
    Dead age is zero at initialization. All retained cells enter pooled targets.
    """
    xl,sl,kl,rl,vl,gl,mul,taul,fdl=pl;xh,sh,kh,rh,vh,gh,muh,tauh,fdh=ph
    bins=max(1,int(np.rint(T/dt)));steps=int(np.max(np.rint(times/dt)))
    result=np.full((len(times),30),np.nan);trace=np.full((steps+1,23),np.nan)
    if (dt<=0 or min(mul,muh)<0 or max(mul,muh)*dt>1 or min(taul,tauh)<=0 or not 0<=fhigh<=1 or min(fdl,fdh)<0 or max(fdl,fdh)>=1 or min(w,dl,dh)<0 or max(w,dl,dh)>1 or observation_area<=0):return result,trace
    total_high=initial_total_high_fraction(fhigh,fdl,fdh)
    low_total=rho0*(1-total_high);high_total=rho0*total_high
    g=np.zeros(steps+2);gv=np.zeros((steps+2,3));g[0]=low_total*(1-fdl)*gl;gv[0]=BASE*vl
    h=np.zeros(3*steps+4);hv=np.zeros((3*steps+4,3));h[0]=high_total*(1-fdh)*gh;hv[0]=BASE*vh
    hf=np.zeros(3*steps+4);hf[0]=h[0]
    q=np.full(bins,low_total*(1-fdl)*(1-gl)/bins);qv=np.zeros((bins,3))
    qh=np.zeros(2*bins);qh[:bins]=high_total*(1-fdh)*(1-gh)/bins;qhv=np.zeros((2*bins,3))
    fql=q.copy();fqh=qh.copy();fgl=g[0]
    deadl=np.zeros(steps+bins+2);deadh=np.zeros(steps+bins+2)
    dvl=np.zeros((steps+bins+2,3));dvh=np.zeros((steps+bins+2,3))
    dfl=np.zeros(steps+bins+2);dfh=np.zeros(steps+bins+2);born=np.zeros(steps+bins+2)
    deadl[0]=low_total*fdl*gl;deadh[0]=high_total*fdh*gh;dvl[0]=BASE*vl;dvh[0]=BASE*vh
    for j in range(bins):
        qv[j]=init_volume((bins-j-.5)*dt,vl);qhv[j]=init_volume((bins-j-.5)*dt,vh);qhv[bins+j]=BASE
        deadl[j+1]=low_total*fdl*(1-gl)/bins;dvl[j+1]=qv[j]
        deadh[j+1]=high_total*fdh*(1-gh)/bins;dvh[j+1]=qhv[j]
    dfl[:bins+1]=deadl[:bins+1];dfh[:bins+1]=deadh[:bins+1];nd=bins+1
    nl,nld,rbl=retained_moments(g,gv,q,qv,1,deadl,dvl,nd,rl);nh,nhd,rbh=retained_moments(h,hv,qh,qhv,1,deadh,dvh,nd,rh)
    if nl+nld<=1e-25:rbl=rl*vl**(1/3)
    if nh+nhd<=1e-25:rbh=rh*vh**(1/3)
    c0=rho0/m0;d0=initial_spacing(1-total_high,rbl,rbh,xl,xh,sl,sh);R=np.sqrt(m0*np.sqrt(3)/2*d0*d0/np.pi)
    cursor=0;slot=0;flux=np.zeros(7);decay=np.exp(-DEAD_RATES*dt)
    for step in range(steps+1):
        ng=step+1;ngh=3*step+1
        nl,nld,rbl=retained_moments(g,gv,q,qv,ng,deadl,dvl,nd,rl);nh,nhd,rbh=retained_moments(h,hv,qh,qhv,ngh,deadh,dvh,nd,rh)
        if nl+nld<=1e-25:rbl=rl*vl**(1/3)
        if nh+nhd<=1e-25:rbh=rh*vh**(1/3)
        ntl=nl+nld;nth=nh+nhd;n=ntl+nth;live=nl+nh
        if not np.isfinite(n+R+rbl+rbh) or n<=0 or n>10 or live<=0:return result,trace
        u,d,pressure_l,pressure_h,rhs=mixed_geometry(R,ntl,nth,rbl,rbh,c0,xl,xh,sl,sh);rbar=(ntl*rbl+nth*rbh)/n
        trace[step,:10]=np.array([step*dt,nl,nh,nh/live,R,rbl,rbh,d,pressure_l,pressure_h]);trace[step,10:15]=flux[:5]
        trace[step,15]=lam_l/(1+(pressure_l/kl)**2);trace[step,16]=lam_h/(1+(pressure_h/kh)**2)
        trace[step,17]=nld;trace[step,18]=nhd;trace[step,19]=flux[5];trace[step,20]=flux[6];trace[step,21]=n;trace[step,22]=rbar
        if cursor<len(times) and int(np.rint(times[cursor]/dt))==step:
            aa=np.log(2)/(np.pi*c0);gap=aa/(np.sqrt(R*R+aa)+R)
            founders=fgl+hf[:ngh].sum()+fql.sum()+fqh.sum()+dfl[:nd].sum()+dfh[:nd].sum();wf=min(1.,founders/(n*m0));ce=wf+(1-wf)*2*np.sqrt(n)*d
            aq=mixture_area(g,gv,q,qv,ng,rl,h,hv,qh,qhv,ngh,rh,deadl,dvl,deadh,dvh,nd)
            while cursor<len(times) and int(np.rint(times[cursor]/dt))==step:
                result[cursor,0]=np.log1p(n*observation_area);result[cursor,1]=np.log1p((nld+nhd)*observation_area)
                result[cursor,2]=u;result[cursor,3]=np.log(max(gap,1.));result[cursor,4]=ce;result[cursor,5:]=aq;cursor+=1
        if step==steps:break
        el=trace[step,15]*dt;eh=trace[step,16]*dt;survl=1-mul*dt;survh=1-muh*dt
        if max(el,eh)>1 or min(survl,survh)<0:return np.full_like(result,np.nan),trace
        next_t=(step+1)*dt
        for j in range(nd):
            if deadl[j]>0:
                dvl[j]*=decay
                if next_t-born[j]>=taul/24-1e-12:deadl[j]=0.;dfl[j]=0.
            if deadh[j]>0:
                dvh[j]*=decay
                if next_t-born[j]>=tauh/24-1e-12:deadh[j]=0.;dfh[j]=0.
        entered_l=0.;entered_h=0.;entered_w=0.;mix_l=np.zeros(3);mix_h=np.zeros(3);mix_w=np.zeros(3)
        loss_l=0.;loss_h=0.;death_mix_l=np.zeros(3);death_mix_h=np.zeros(3)
        old_loss_l=fgl*mul*dt;old_loss_h=0.;feh=0.;fehw=0.
        for j in range(ng):
            update_volume(gv,j,1.,dt);loss=g[j]*mul*dt;loss_l+=loss;death_mix_l+=loss*gv[j]
            g[j]*=survl;e=g[j]*el;entered_l+=e;mix_l+=e*gv[j];g[j]-=e
        fgl*=survl;fel=fgl*el;fgl-=fel
        for j in range(ngh):
            update_volume(hv,j,1.,dt);loss=h[j]*muh*dt;loss_h+=loss;death_mix_h+=loss*hv[j];old_loss_h+=hf[j]*muh*dt;hf[j]*=survh
            h[j]*=survh;e=h[j]*eh;h[j]-=e;founder_entry=hf[j]*eh;hf[j]-=founder_entry
            if j>0 and j%3==0:entered_w+=e;mix_w+=e*hv[j];fehw+=founder_entry
            else:entered_h+=e;mix_h+=e*hv[j];feh+=founder_entry
        for j in range(bins):
            update_volume(qv,j,2.,dt);loss=q[j]*mul*dt;loss_l+=loss;death_mix_l+=loss*qv[j];old_loss_l+=fql[j]*mul*dt;q[j]*=survl;fql[j]*=survl
        for j in range(2*bins):
            update_volume(qhv,j,2.,dt);loss=qh[j]*muh*dt;loss_h+=loss;death_mix_h+=loss*qhv[j];old_loss_h+=fqh[j]*muh*dt;qh[j]*=survh;fqh[j]*=survh
        background_l=loss_l;background_h=loss_h
        newl,newh,wgd,mitdeadl,mitdeadh=outcome_counts(q[slot],qh[slot],dl,dh,w)
        newhw=2*(1-dh)*qh[bins+slot];mitdeadhw=dh*qh[bins+slot];mitdeadh+=mitdeadhw
        loss_l+=mitdeadl;death_mix_l+=mitdeadl*qv[slot];old_loss_l+=dl*fql[slot]
        loss_h+=mitdeadh;death_mix_h+=dh*qh[slot]*qhv[slot]+mitdeadhw*qhv[bins+slot];old_loss_h+=dh*(fqh[slot]+fqh[bins+slot])
        deadl[nd]=loss_l;deadh[nd]=loss_h;born[nd]=next_t;dfl[nd]=old_loss_l;dfh[nd]=old_loss_h
        if loss_l>0:dvl[nd]=death_mix_l/loss_l
        if loss_h>0:dvh[nd]=death_mix_h/loss_h
        nd+=1;flux=np.array([mitdeadl/dt,mitdeadh/dt,wgd/dt,newl/(2*dt),(newh+newhw)/(2*dt),background_l/dt,background_h/dt])
        g[ng]=newl;gv[ng]=qv[slot]/2;h[ngh]=newh;hv[ngh]=qhv[slot]/2;h[ngh+1]=newhw;hv[ngh+1]=qhv[bins+slot]/2
        h[ngh+2]=wgd;hv[ngh+2]=qv[slot]*(rl/rh)**3;hf[ngh+2]=fql[slot]*(1-dl)*w
        q[slot]=entered_l;qh[slot]=entered_h;qh[bins+slot]=entered_w;fql[slot]=fel;fqh[slot]=feh;fqh[bins+slot]=fehw
        qv[slot]=mix_l/entered_l if entered_l>0 else BASE.copy();qhv[slot]=mix_h/entered_h if entered_h>0 else BASE.copy();qhv[bins+slot]=mix_w/entered_w if entered_w>0 else BASE.copy()
        slot=(slot+1)%bins
        nl,nld,rbl=retained_moments(g,gv,q,qv,ng+1,deadl,dvl,nd,rl);nh,nhd,rbh=retained_moments(h,hv,qh,qhv,ngh+3,deadh,dvh,nd,rh)
        if nl+nld<=1e-25:rbl=rl*vl**(1/3)
        if nh+nhd<=1e-25:rbh=rh*vh**(1/3)
        low=1e-12;high=max(R*2,R+abs(rhs)*dt+1)
        for _ in range(50):
            if high-R-dt*mixed_geometry(high,nl+nld,nh+nhd,rbl,rbh,c0,xl,xh,sl,sh)[4]>0:break
            high*=2
        for _ in range(40):
            mid=(low+high)/2
            if mid-R-dt*mixed_geometry(mid,nl+nld,nh+nhd,rbl,rbh,c0,xl,xh,sl,sh)[4]>0:high=mid
            else:low=mid
        R=(low+high)/2
    return result,trace
