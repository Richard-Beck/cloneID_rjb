"""Days/pixels colony closure with retained, shrinking, nondividing corpses.

p = xeq, speed, K, r0, rho0_total, m0, vinit, fG_live.
All initial corpses have age zero and the same pre-death phase-volume mixture
as live cells. A death-time cohort pools incoming volume components by mass.
"""
import numpy as np
from numba import njit

BASE = np.array([135 / 2494, 488.5 / 2494, .75])
# Frozen standard XML apoptosis rates, converted from minutes to days.
DEAD_RATES = np.array([.00583333, .0166667, .05]) * 1440

@njit(cache=True)
def volume(v, target, dt):
    n, c, f = v[0], v[1], v[2]
    return np.array([n + dt*7.92*(target*BASE[0]-n),
                     c + dt*6.48*(target*BASE[1]-c),
                     f + dt*72*(.75*(n+c+f)-f)])

@njit(cache=True, inline='always')
def update_volume(v, j, target, dt):
    n, c, f = v[j, 0], v[j, 1], v[j, 2]
    v[j, 0] = n + dt*7.92*(target*BASE[0]-n)
    v[j, 1] = c + dt*6.48*(target*BASE[1]-c)
    v[j, 2] = f + dt*72*(.75*(n+c+f)-f)

@njit(cache=True)
def init_volume(age, factor):
    v = BASE.copy()
    n = int(np.ceil(age*1440))
    if n:
        for _ in range(n):
            v = volume(v, 2., age/n)
    return v*factor

@njit(cache=True)
def geometry(R, N, r, c0, xeq, speed):
    eta = c0*np.pi*R*R
    U = max(-np.expm1(-eta), 1e-15)
    L = U*np.exp(min(eta, 80))/(c0*np.pi*R)
    rho = N/U
    d = np.sqrt(2/(np.sqrt(3)*rho))
    ne = max(1., rho*np.pi*L*L)
    z = max(0., min(ne-1, 6-2*np.sqrt(12*ne-3)/ne))
    ov = max(0., 1-d/(2*r))
    a = max(0., 1-d/(2*1.25*r))
    b = (1-xeq)/(1-xeq/1.25)
    P = z*ov*ov/.027288820670331
    rhs = z*d*speed*(ov*ov-b*b*a*a)/L
    return U, d, P, rhs

@njit(cache=True)
def moments(g, gv, q, qv, ng, r0):
    N = 0.
    r = 0.
    for j in range(ng):
        N += g[j]
        r += g[j]*r0*max(gv[j].sum(), 1e-300)**(1/3)
    for j in range(len(q)):
        N += q[j]
        r += q[j]*r0*max(qv[j].sum(), 1e-300)**(1/3)
    return N, r/max(N, 1e-300)

@njit(cache=True)
def pooled_moments(g, gv, q, qv, ng, dead, dv, nd, r0):
    live, r = moments(g, gv, q, qv, ng, r0)
    radius_sum = live*r
    D = 0.
    for j in range(nd):
        D += dead[j]
        radius_sum += dead[j]*r0*max(dv[j].sum(), 1e-300)**(1/3)
    return live, D, radius_sum/max(live+D, 1e-300)

@njit(cache=True)
def pooled_area_q(g, gv, q, qv, ng, dead, dv, nd):
    # Drop zero-weight cohorts before interpolation, avoiding duplicate CDF knots.
    a = np.empty(ng+len(q)+nd)
    w = np.empty(len(a))
    k = 0
    for j in range(ng):
        if g[j] > 0:
            a[k] = max(gv[j].sum(), 1e-300)**(2/3)
            w[k] = g[j]
            k += 1
    for j in range(len(q)):
        if q[j] > 0:
            a[k] = max(qv[j].sum(), 1e-300)**(2/3)
            w[k] = q[j]
            k += 1
    for j in range(nd):
        if dead[j] > 0:
            a[k] = max(dv[j].sum(), 1e-300)**(2/3)
            w[k] = dead[j]
            k += 1
    a = a[:k]
    w = w[:k]
    order = np.argsort(a)
    a = a[order]
    w = w[order]
    mean = np.sum(a*w)/np.sum(w)
    cum = np.cumsum(w)/np.sum(w)
    return np.log(np.interp(np.arange(.02, 1., .04), cum, a)/mean)

@njit(cache=True)
def simulate_with_geometry(p, lam, times, dt=1/240, T=13/24,
                           mu=.076560048, dead_duration_hours=8.6,
                           initial_dead_fraction=0., observation_area=1540000.):
    """n x 30 observations and time/radius/spacing/pressure geometry trace.

    Death is a live hazard /day. Residence is a deterministic duration; dead
    components decay with the standard apoptosis rates. Initial death age is 0.
    rho0 denotes all seeded objects; fG denotes G1 fraction conditional on life.
    Count outputs are log1p(mean count/field), using the known field area.
    """
    xeq, speed, K, r0, rho0, m0, vinit, fG = p
    bins = max(1, int(np.rint(T/dt)))
    steps = int(np.max(np.rint(times/dt)))
    result = np.full((len(times), 30), np.nan)
    trace = np.full((steps+1, 4), np.nan)
    if (dt <= 0 or mu < 0 or dead_duration_hours <= 0 or
            initial_dead_fraction < 0 or initial_dead_fraction >= 1 or
            observation_area <= 0 or mu*dt > 1):
        return result, trace
    g = np.zeros(steps+2)
    gv = np.zeros((steps+2, 3))
    g[0] = rho0*(1-initial_dead_fraction)*fG
    gv[0] = BASE*vinit
    q = np.full(bins, rho0*(1-initial_dead_fraction)*(1-fG)/bins)
    qv = np.zeros((bins, 3))
    fq = q.copy()
    fg = g[0]
    # First bins+1 cohorts preserve the complete initial pre-death mixture.
    dead = np.zeros(steps+bins+2)
    dv = np.zeros((steps+bins+2, 3))
    born = np.zeros(steps+bins+2)
    old_dead = np.zeros(steps+bins+2)
    dead[0] = rho0*initial_dead_fraction*fG
    dv[0] = BASE*vinit
    for j in range(bins):
        qv[j] = init_volume((bins-j-.5)*dt, vinit)
        dead[j+1] = rho0*initial_dead_fraction*(1-fG)/bins
        dv[j+1] = qv[j]
    old_dead[:bins+1] = dead[:bins+1]
    nd = bins+1
    live, D, r = pooled_moments(g, gv, q, qv, 1, dead, dv, nd, r0)
    c0 = rho0/m0
    R = np.sqrt(m0*np.sqrt(3)/2*(2*r*xeq)**2/np.pi)
    cursor = 0
    slot = 0
    lifetime = dead_duration_hours/24
    # Analytic exponential corpse decay avoids coarse-grid negative volumes.
    # Native integration uses its fixed 3-minute phenotype updates.
    decay = np.exp(-DEAD_RATES*dt)
    for step in range(steps+1):
        ng = step+1
        live, D, r = pooled_moments(g, gv, q, qv, ng, dead, dv, nd, r0)
        N = live+D
        if not np.isfinite(N+r) or N <= 0 or N > 10 or r <= 0:
            return result, trace
        U, d, P, rhs = geometry(R, N, r, c0, xeq, speed)
        trace[step, 0] = step*dt
        trace[step, 1] = r
        trace[step, 2] = d
        trace[step, 3] = P
        if cursor < len(times) and int(np.rint(times[cursor]/dt)) == step:
            aa = np.log(2)/(np.pi*c0)
            gap = aa/(np.sqrt(R*R+aa)+R)
            old = fg+fq.sum()+old_dead[:nd].sum()
            w = min(1., old/(N*m0))
            ce = w+(1-w)*2*np.sqrt(N)*d
            aq = pooled_area_q(g, gv, q, qv, ng, dead, dv, nd)
            while cursor < len(times) and int(np.rint(times[cursor]/dt)) == step:
                result[cursor, 0] = np.log1p((live+D)*observation_area)
                result[cursor, 1] = np.log1p(D*observation_area)
                result[cursor, 2] = U
                result[cursor, 3] = np.log(max(gap, 1.))
                result[cursor, 4] = ce
                result[cursor, 5:] = aq
                cursor += 1
        if step == steps:
            break
        entry = lam/(1+(P/K)**2)*dt
        survival = 1-mu*dt
        if entry > 1 or survival < 0:
            return np.full_like(result, np.nan), trace
        # Existing corpses shrink and expire. All apoptosis targets are zero.
        next_t = (step+1)*dt
        for j in range(nd):
            if dead[j] > 0:
                dv[j] *= decay
                if next_t-born[j] >= lifetime-1e-12:
                    dead[j] = 0.
                    old_dead[j] = 0.
        entered = 0.
        mix = np.zeros(3)
        died = 0.
        death_mix = np.zeros(3)
        for j in range(ng):
            update_volume(gv, j, 1., dt)
            loss = g[j]*mu*dt
            died += loss
            death_mix += loss*gv[j]
            g[j] *= survival
            e = g[j]*entry
            entered += e
            mix += e*gv[j]
            g[j] -= e
        dead_founders = fg*mu*dt
        fg *= survival
        fe = fg*entry
        fg -= fe
        for j in range(bins):
            update_volume(qv, j, 2., dt)
            loss = q[j]*mu*dt
            died += loss
            death_mix += loss*qv[j]
            dead_founders += fq[j]*mu*dt
            q[j] *= survival
            fq[j] *= survival
        dead[nd] = died
        born[nd] = next_t
        old_dead[nd] = dead_founders
        if died > 0:
            dv[nd] = death_mix/died
        nd += 1
        g[ng] = 2*q[slot]
        gv[ng] = qv[slot]/2
        q[slot] = entered
        fq[slot] = fe
        if entered > 0:
            qv[slot] = mix/entered
        else:
            qv[slot] = BASE
        slot = (slot+1) % bins
        live, D, r = pooled_moments(g, gv, q, qv, ng+1, dead, dv, nd, r0)
        N = live+D
        low = 1e-12
        high = max(R*2, R+abs(rhs)*dt+1)
        for _ in range(50):
            if high-R-dt*geometry(high, N, r, c0, xeq, speed)[3] > 0:
                break
            high *= 2
        for _ in range(40):
            mid = (low+high)/2
            residual = mid-R-dt*geometry(mid, N, r, c0, xeq, speed)[3]
            if residual > 0:
                high = mid
            else:
                low = mid
        R = (low+high)/2
    return result, trace

@njit(cache=True)
def simulate(p, lam, times, dt=1/240, T=13/24, mu=.076560048,
             dead_duration_hours=8.6, initial_dead_fraction=0.,
             observation_area=1540000.):
    return simulate_with_geometry(p, lam, times, dt, T, mu,
                                  dead_duration_hours,
                                  initial_dead_fraction, observation_area)[0]
