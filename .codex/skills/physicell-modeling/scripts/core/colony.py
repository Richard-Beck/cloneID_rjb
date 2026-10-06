"""Fresh implementation of references/canonical-model.md; days/pixels.
No old hypothesis-run code, fitted values, or generated observations are imported.
"""
import numpy as np
from numba import njit
BASE=np.array([135/2494,488.5/2494,.75])
@njit(cache=True)
def volume(v,target,dt):
    n,c,f=v[0],v[1],v[2]
    return np.array([n+dt*7.92*(target*BASE[0]-n),c+dt*6.48*(target*BASE[1]-c),f+dt*72*(.75*(n+c+f)-f)])
@njit(cache=True,inline='always')
def update_volume(v,j,target,dt):
    n,c,f=v[j,0],v[j,1],v[j,2]
    v[j,0]=n+dt*7.92*(target*BASE[0]-n)
    v[j,1]=c+dt*6.48*(target*BASE[1]-c)
    v[j,2]=f+dt*72*(.75*(n+c+f)-f)
@njit(cache=True)
def init_volume(age,factor):
    v=BASE.copy();n=int(np.ceil(age*1440))
    if n:
        for _ in range(n):v=volume(v,2.,age/n)
    return v*factor
@njit(cache=True)
def geometry(R,N,r,c0,xeq,speed):
    eta=c0*np.pi*R*R;U=max(-np.expm1(-eta),1e-15)
    L=U*np.exp(min(eta,80))/(c0*np.pi*R)
    rho=N/U;d=np.sqrt(2/(np.sqrt(3)*rho));ne=max(1.,rho*np.pi*L*L)
    z=max(0.,min(ne-1,6-2*np.sqrt(12*ne-3)/ne))
    ov=max(0.,1-d/(2*r));a=max(0.,1-d/(2*1.25*r));b=(1-xeq)/(1-xeq/1.25)
    P=z*ov*ov/.027288820670331;rhs=z*d*speed*(ov*ov-b*b*a*a)/L
    return U,d,P,rhs
@njit(cache=True)
def moments(g,gv,q,qv,ng,r0):
    N=0.;r=0.
    for j in range(ng):
        N+=g[j];r+=g[j]*r0*(gv[j,0]+gv[j,1]+gv[j,2])**(1/3)
    for j in range(len(q)):
        N+=q[j];r+=q[j]*r0*(qv[j,0]+qv[j,1]+qv[j,2])**(1/3)
    return N,r/N
@njit(cache=True)
def area_q(g,gv,q,qv,ng):
    a=np.empty(ng+len(q));w=np.empty(len(a))
    for j in range(ng):a[j]=(gv[j,0]+gv[j,1]+gv[j,2])**(2/3);w[j]=g[j]
    for j in range(len(q)):a[ng+j]=(qv[j,0]+qv[j,1]+qv[j,2])**(2/3);w[ng+j]=q[j]
    order=np.argsort(a);a=a[order];w=w[order];mean=np.sum(a*w)/np.sum(w);cum=np.cumsum(w)/np.sum(w)
    return np.log(np.interp(np.arange(.02,1.,.04),cum,a)/mean)
@njit(cache=True)
def simulate_with_geometry(p,lam,times,dt=1/240,T=13/24,mu=.076560048):
    # p = xeq,speed,K,r0,rho0,m0,vinit,fG
    xeq,speed,K,r0,rho0,m0,vinit,fG=p
    bins=max(1,int(np.rint(T/dt)));steps=int(np.max(np.rint(times/dt)))
    g=np.zeros(steps+2);gv=np.zeros((steps+2,3));g[0]=rho0*fG;gv[0]=BASE*vinit
    q=np.full(bins,rho0*(1-fG)/bins);qv=np.zeros((bins,3));fq=q.copy();fg=g[0]
    for j in range(bins):qv[j]=init_volume((bins-j-.5)*dt,vinit)
    N,r=moments(g,gv,q,qv,1,r0);c0=rho0/m0;R=np.sqrt(m0*np.sqrt(3)/2*(2*r*xeq)**2/np.pi)
    result=np.full((len(times),29),np.nan);trace=np.full((steps+1,4),np.nan);cursor=0;slot=0
    for step in range(steps+1):
        ng=step+1;N,r=moments(g,gv,q,qv,ng,r0)
        if not np.isfinite(N+r) or N<=0 or N>10:return result,trace
        U,d,P,rhs=geometry(R,N,r,c0,xeq,speed)
        trace[step,0]=step*dt;trace[step,1]=r;trace[step,2]=d;trace[step,3]=P
        if cursor<len(times) and int(np.rint(times[cursor]/dt))==step:
            aa=np.log(2)/(np.pi*c0);gap=aa/(np.sqrt(R*R+aa)+R)
            w=min(1.,(fg+fq.sum())/(N*m0));ce=w+(1-w)*2*np.sqrt(N)*d
            aq=area_q(g,gv,q,qv,ng)
            while cursor<len(times) and int(np.rint(times[cursor]/dt))==step:
                result[cursor,0]=np.log(N);result[cursor,1]=U;result[cursor,2]=np.log(gap);result[cursor,3]=ce
                result[cursor,4:]=aq;cursor+=1
        if step==steps:break
        entry=lam/(1+(P/K)**2)*dt;surv=1-mu*dt
        if entry>1 or surv<0:return np.full_like(result,np.nan),trace
        entered=0.;mix=np.zeros(3)
        for j in range(ng):
            update_volume(gv,j,1.,dt);g[j]*=surv
            e=g[j]*entry;entered+=e
            for v in range(3):mix[v]+=e*gv[j,v]
            g[j]-=e
        fg*=surv;fe=fg*entry;fg-=fe
        for j in range(bins):update_volume(qv,j,2.,dt);q[j]*=surv;fq[j]*=surv
        g[ng]=2*q[slot];gv[ng]=qv[slot]/2
        q[slot]=entered;fq[slot]=fe
        if entered>0:qv[slot]=mix/entered
        else:qv[slot]=BASE
        slot=(slot+1)%bins
        N,r=moments(g,gv,q,qv,ng+1,r0)
        low=1e-12;high=max(R*2,R+abs(rhs)*dt+1)
        for _ in range(50):
            if high-R-dt*geometry(high,N,r,c0,xeq,speed)[3]>0:break
            high*=2
        for _ in range(40):
            mid=(low+high)/2;v=mid-R-dt*geometry(mid,N,r,c0,xeq,speed)[3]
            if v>0:high=mid
            else:low=mid
        R=(low+high)/2
    return result,trace

@njit(cache=True)
def simulate(p,lam,times,dt=1/240,T=13/24,mu=.076560048):
    return simulate_with_geometry(p,lam,times,dt,T,mu)[0]
