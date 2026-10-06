# Mechanistic colony baseline: specification and derivation

Version: 2026-09-21. Start with [the brief workflow](workflow.md). This document specifies the generic baseline, not a particular
lineage's fitted coefficients. It describes the implemented fast approximation and its mapping to PhysiCell 1.14.2.

The compact simulator template is [PhysiCell_settings.xml](PhysiCell_settings.xml), with one necessary
[pressure rule](cell_rules.csv) and a consolidated [runtime adapter](baseline_runtime.cpp). XML values are neutral examples,
not the latest estimates. The engine itself is an external dependency. The approximation is a deterministic population model:
cell-cycle and volume cohorts coupled to one colony-radius equation. It does not simulate cell coordinates.

## 1. Scope, sharing, and units

A parameter-sharing group consists of lineages with documented recent common ancestry and no substantial intervening cell
transformation. Do not equate this grouping with a cell-line label, experimental arm, medium, or an arbitrary graph component.
Ploidy-changing transformations, major engineering, mixing, or other documented changes can require separate groups even with
common ancestry. Record the ancestry boundary and its rationale; there is no universal passage-count threshold for “recent.”

Each group has one shared mechanical parameter vector and one latent initialization. Episodes are repeated realizations of the
same process, observed at their own times since seeding. Changing medium changes designated rates through functional responses;
it does not create a fresh unconstrained parameter vector or initialization. This is a stationary baseline, not a model of inherited
adaptation or a literal continuation of one culture through every passage.

Use days and pixels in the approximation, minutes and pixels in the simulator. Densities are cells/pixel^2; volumes are pixel^3.
All images within a fit must have a consistent spatial scale (resample or convert to physical units otherwise). A radius inferred
in pixels is not a radius in microns. The baseline uses 2D positions and 3D spherical cell volumes.

## 2. Media response

For a nonnegative medium component x and a designated positive parameter p:

```text
H(0; x50,h) = 0
H(x>0; x50,h) = 1 / (1 + exp(-h*(log(x)-log(x50))))
p(x) = p_low + (p_high-p_low)*H(x; x50,h)
```

This is the numerically stable form of x^h/(x50^h+x^h). x50 is the half-response concentration in the same units as x.
h controls steepness. Both endpoints are positive; allowing either endpoint ordering permits increasing or decreasing responses.
Each ancestry group has its own endpoints, x50, and h. Do not fix h or share x50 by default. Search positive coefficients in log
coordinates; the baseline exponent bounds are 0.01–100. For oxygen, use percentage points (20.5 means 20.5%, not 0.205), with
O50 bounds 0.001–100 and G1-exit endpoints 0.1–24/day. These numerical bounds need explicit review for other compounds and units.

The fitted baseline makes only the uncrowded G1-exit rate, lambda0, medium-dependent. The general rule is to model *every varying
quantitative medium component* with Hill responses on a declared, biologically plausible subset of parameters. This does not mean
making every mechanistic parameter medium-dependent. Inventory exact compositions, not just medium labels. Components that never
vary have their effects absorbed into the shared baseline. Unknown compositions require resolution, not invented concentrations.

For multiple varying components, declare the combination rule before fitting. A positive separable extension is:

```text
p(x1,...,xJ) = p_ref * product_j( f_j(xj) / f_j(xj_ref) )
f_j(x) = 1 + (r_j-1)*H(x; x50_j,h_j),   r_j > 0
```

p_ref is the value at the reference composition; r_j is a high/low response ratio. Each group estimates its own response
coefficients. For one component this can be reparameterized as the two-endpoint curve above. This multiplicative extension is a
recommended convention, not something already evaluated by the oxygen-only implementation. Add interactions only as explicit
extensions. Perfectly co-varying components cannot have their effects separately identified from these observations.

Nominal zero is exactly zero in this model. Very small h can produce a large difference between zero and tiny positive x.
A fitted media association may also reflect exposure history; it is not automatically evidence of acute sensing.

## 3. Cell cycle, death, and population balance

Let G(t) be live G1-cell density. q(a,t) is post-G1 cell density per unit cycle age, with 0 <= a < T. All post-G1 cells divide after
a fixed delay T; mu is the common live-cell death hazard. The baseline has no retained corpse population.

```text
lambda(t) = lambda0(media) / (1 + (P(t)/K)^2)
J(t) = lambda(t)*G(t)
partial_t q + partial_a q = -mu*q;   q(0,t) = J(t)
D(t) = q(T,t)
dG/dt = 2*D - J - mu*G
N(t) = G(t) + integral_0^T q(a,t) da
dN/dt = D - mu*N
```

The division term is D, not 2D, in total density because a mother is replaced by two daughters. For t >= T,
D(t) = exp(-mu*T)*J(t-T). Before T, initially cycling cells provide the division flux. These equations follow the stochastic
G1 waiting time, deterministic subsequent phases, and death hazard in the simulator, after taking population expectations and
replacing cell-specific pressure with one representative P.

The standard fixed delay is T = 13/24 days: S, G2, M durations are 480, 240, 60 minutes. The standard hazard is
mu = 0.0000531667*1440 = 0.076560048/day. Existing calibration also considers a 24-hour delay with the same phase proportions,
and a 13-hour delay with zero death. Choose a single scenario per ancestry group across all its media, under the same fit budget.
The media Hill exponent h is free; the *pressure* exponent 2 is a different, fixed baseline constant.

## 4. Volume cohorts and relative cell-area distribution

Track normalized nuclear solid n, cytoplasmic solid c, and fluid f for each age/birth cohort. Normalization is by the target G1
volume V0. The source proportions are nuclear solid 135/2494, cytoplasmic solid 488.5/2494, fluid 0.75. Their sum is one.
For target multiplier a = 1 in G1 and a = 2 after G1 exit:

```text
dn/dt = 7.92 * (a*135/2494 - n)
dc/dt = 6.48 * (a*488.5/2494 - c)
df/dt = 72 * (0.75*(n+c+f) - f)
v = n+c+f
r = r0*v^(1/3)
A = pi*r0^2*v^(2/3)
```

Rates are /day, converted from 0.0055, 0.0045, 0.05 /minute. Fluid relaxes toward 75% of current total volume, rather than
independently doubling at cycle entry. At division each daughter receives half of each mother component. Cohort weights double;
volume is conserved at division. The scalar mechanical model uses the cell-number-weighted mean radius rbar, not the radius of
the mean volume. Cohort merging replaces distinct states by their component means; nonlinear area/radius moments are approximate.

For observation, calculate mean area across the weighted live-cell distribution, then the 25 quantiles at probabilities
0.02, 0.06, ..., 0.98 of log(A/mean(A)). Equivalently compute quantiles of A then take their normalized logarithms.
The radius factor cancels, so relative area constrains cycle/volume composition rather than absolute scale directly. Baseline
observation log-width is fixed to zero. The reference implementation supports an optional mean-one lognormal multiplier with
21 deterministic normal-quantile nodes, but that additional heterogeneity is not fitted in this baseline.

## 5. Shared initialization

Four parameters specify initialization: density rho0, mean founding-cluster size m0, volume factor vinit, and G1 fraction fG.
Initial G1 density is rho0*fG. Post-G1 ages are uniform on [0,T), with total density rho0*(1-fG). For each cycling age, start at
normal G1 volume, integrate the doubled-target volume equations through that age, and multiply all components by vinit.
Initial G1 components are simply the normal G1 proportions times vinit. This defines rbar(0) without fitting individual cells.

Let xeq be equilibrium pair spacing divided by cell diameter. Define:

```text
c0 = rho0/m0                         # founding-center density, constant in time
s0 = sqrt(3)/2 * (2*rbar(0)*xeq)^2    # initial territory per cell
R(0) = sqrt(m0*s0/pi)                # founding-envelope radius
```

Every episode in the group restarts from this same latent distribution; random simulator realizations may differ. c0 counts
founding centers, not current connected colonies. The continuous m0 is rounded into an integer cluster population only on transfer.

## 6. Poisson colony geometry

Approximate founding centers as a homogeneous Poisson process of density c0, each with a common circular footprint radius R.
For a point to be outside all footprints, its radius-R neighborhood must contain zero centers. The Poisson void probability gives:

```text
eta = c0*pi*R^2
U = 1 - exp(-eta)                    # occupied colony-envelope fraction
E = 2*pi*c0*R*exp(-eta)              # exposed perimeter per unit total area
L = 2*U/E = U*exp(eta)/(c0*pi*R)      # effective escape length
rho = N/U                           # local live density inside envelopes
d = sqrt(2/(sqrt(3)*rho))             # representative neighbor spacing
```

E follows by differentiating U with respect to R. For sparse, nonoverlapping discs, U approximately equals c0*pi*R^2 and L
approximately equals R. Overlap removes exposed perimeter and increases L. The formula for d follows from triangular territory
area sqrt(3)*d^2/2 = 1/rho. U is an envelope fraction, not raw cell-mask coverage or summed projected cell area.

The current implementation uses the infinite homogeneous Poisson closure. It does not use the finite-number correction from
earlier derivation prototypes, a literal finite-well singleton rule, or a cap on effective patch size at the total cell count.
It neglects boundaries, colony-size dispersion, heterogeneous packing, center motion, and correlations between founding centers.

Approximate contact coordination using an escape-sized patch:

```text
n_eff = max(1, rho*pi*L^2)
z_hex = 6 - 2*sqrt(12*n_eff-3)/n_eff
z = max(0, min(n_eff-1, z_hex))
```

For complete hexagonal patches with k shells, n = 1+3*k*(k+1) and mean degree is
6 - 6*(2*k+1)/n. Eliminating k gives z_hex. Extending it to arbitrary n_eff is a closure assumption. The n_eff-1 cap enforces
at most one neighbor for an effective two-cell patch. Coordination tends to six for large patches.

## 7. Mechanical equation and pressure

For an equal-radius pair, the PhysiCell overdamped pair-velocity contribution is:

```text
ell = 1.25
b = (1-xeq)/(1-xeq/ell)
F(d) = s * ( max(0,1-d/(2*rbar))^2
             - b^2*max(0,1-d/(2*ell*rbar))^2 )
```

s is the repulsion speed coefficient in pixels/day; adhesion is s*b^2. Setting F(2*rbar*xeq)=0 derives the ratio b^2. This
separates equilibrium spacing from rearrangement speed. F has velocity units; no independent friction coefficient is introduced.

Under isotropic contact directions in 2D, the pair-virial stress is Pi = rho*z*d*F/4: divide by two to count each pair once and
by two for the isotropic trace. For uniform circular expansion, assume v(r) = v_edge*r/R and force balance
rho*v = -gradient(Pi). Setting edge stress to zero and averaging the resulting parabolic stress profile gives
mean(Pi) = rho*v_edge*R/4. Replacing the isolated radius by L = 2U/E yields:

```text
dR/dt = 4*Pi/(rho*L) = z*d*F(d)/L
```

This extension to overlapping footprints is the principal mechanical closure, not an exact consequence of arbitrary agent
configurations. Repulsion expands envelopes; adhesion permits contraction. Growth changes density and radius through the cohorts.

PhysiCell's dimensionless overlap pressure is distinct from signed stress Pi:

```text
Cp = 0.027288820670331
P = (z/Cp) * max(0,1-d/(2*rbar))^2
lambda = lambda0(media) / (1+(P/K)^2)
```

Cp is the normalization in the local PhysiCell source. Pressure excludes the attractive contribution. K is its half-inhibition
value. Closure uses mean geometry, whereas the agent model sums overlaps separately for each cell. No fitted global carrying
capacity is imposed; crowding slows entry through this feedback.

## 8. Organization observation operators

### Empty-space distance: colony scale

For a random background point, let D be its distance to the envelope. Conditional on being outside a radius-R footprint union:

```text
Pr(D > x | background) = exp(-c0*pi*((R+x)^2-R^2)), x >= 0
a = log(2)/(pi*c0)
median(D | background) = sqrt(R^2+a)-R = a/(sqrt(R^2+a)+R)
```

The numerator uses the void probability for a radius R+x and the conditioning denominator uses radius R. The last form avoids
cancellation. This is a conditional background median, not distance from all pixels to a centroid. It responds to gaps between
colony envelopes beyond the nearest-cell scale. Only its median enters the current objective.

### Clark–Evans: nearest-neighbor scale

For a homogeneous 2D Poisson cell process of global density N, survival of nearest-neighbor distance is exp(-pi*N*x^2).
Integrating gives mean d_P = 1/(2*sqrt(N)). Let F_old(t) be surviving, never-divided original-cell density, tracked through
G1 exit and post-G1 progression but not inherited by daughters. The current interpolation is:

```text
w = min(1, F_old/(N*m0))
d_NN = w/(2*sqrt(N)) + (1-w)*d
Clark_Evans = 2*sqrt(N)*d_NN
```

This heuristic interpolates between dispersed founders and local packing; the m0 factor accommodates clustered initial states.
It is not an exact cluster-process nearest-neighbor law and never feeds back into growth. Both organization metrics are useful,
but remain correlated through geometry; equal weights do not establish statistical independence.

### Images and simulator snapshots

Construct colony envelopes by closing the raw cell-mask union with a circular radius of 10 pixels. Reflect-pad by 30 pixels for
morphology, then exclude a 30-pixel image border for quantitative summaries. Coverage is the mean envelope indicator inside this
interior. For empty space, sample background on a stride-4 grid; distance to the nearest envelope is right-censored at distance
to the trusted-interior boundary. Use the spatial Kaplan–Meier median; report missing if it cannot be estimated (including fewer
than 100 sampled background locations). Do not replace an unobserved median with zero.

Clark–Evans uses all labeled-cell centroids in the full field: CE = 2*sqrt(n_cells/field_area)*mean(nearest_distance).
The fitted baseline does not edge-correct this statistic; it is missing with fewer than two cells. This finite-window bias is
retained for consistency and should be changed only with a corresponding refit. Relative area uses segmented object areas. Apply matched operators to simulated cells: rasterize projected
cell disks for coverage/gaps, use their centers for Clark–Evans, and use pi*r^2 for individual area. The fixed pixel-scale settings
above must be rescaled if image resolution changes. Colony-envelope coverage is deliberately the measurement target.

## 9. Composite calibration objective

The objective is a balanced composite discrepancy (a pseudo-likelihood if exponentiated), not an independent-data likelihood.
For each acquisition, define standardized squared residuals:

```text
count:        ((log(N_pred)+b-log(count_observed))/0.20)^2
coverage:     ((U_pred-U_observed)/s_U)^2
relativeArea: mean_over_25_quantiles( ((q_pred-q_observed)/s_q)^2 )
emptySpace:   ((log(gap_pred)-log(gap_observed))/s_gap)^2
ClarkEvans:   ((CE_pred-CE_observed)/s_CE)^2
```

For image summaries, s^2 = field-bootstrap variance + floor^2, using 300 field-bootstrap draws. Floors are 0.05 for coverage,
0.08 for each relative log-area quantile, 0.20 for log empty distance, and 0.08 for Clark–Evans. Counts use the fixed 0.20 log scale.
Bootstrap fields, not every cell as an independent sample. At acquisition level, average coverage and finite Clark–Evans values
across fields; average log field-level empty-space medians over fields with finite positive medians. For relative area, pool all
segmented cell areas across fields before mean normalization and quantiles. Recompute these summaries for each bootstrap draw.
Thus coverage/gap/Clark–Evans aggregate fields equally, whereas the relative-area distribution pools cells.

Within each subcomponent, first average available acquisition residuals within each episode, then average supported episodes
across the entire ancestry-sharing group. Missing spatial measurements do not discard valid counts. Media levels with fewer
episodes do not receive an artificial equal-condition weight. Let the resulting five errors be B_count, B_U, B_A, B_gap, B_CE:

```text
loss = (B_count + (B_U+B_A)/2 + (B_gap+B_CE)/2)/3
     = B_count/3 + B_U/6 + B_A/6 + B_gap/6 + B_CE/6
b = sum_i w_count_i * (log(count_observed_i)-log(N_pred_i))
```

w_count sums to one using the episode-balanced scheme. b is the analytic optimum of the quadratic count error: differentiating
with respect to b gives the weighted mean above. One b is shared across the group. It converts latent density to the count
measurement scale and is not a biological growth rate. If vessel formats or count definitions change, standardize measurements
or explicitly revise this observation model. Do not silently fit an offset per medium.

## 10. Numerical implementation

Maintain a fixed-delay post-G1 queue and G1 birth cohorts, carrying weight, volume components, and undivided-founder weight.
Round T/dt to an integer number of bins. Initialize cycling bins uniformly with midpoint ages; initialize their component volumes
using substeps no larger than one minute. At each step, compute geometry and lambda, update volumes with forward Euler, apply
survival 1-mu*dt, transfer fraction lambda*dt of G1 to the queue, release the oldest bin as two half-volume daughters, then update R.
Entry cohorts combine volume components by flux-weighted means. These are discretizations of the balances above, not exact
exponential-hazard updates. Require lambda*dt <= 1 and mu*dt <= 1.

Mechanics uses implicit Euler with a positive-radius bracket and 40 bisection iterations:

```text
R_next - R_now - dt * mechanical_rhs(R_next, N_next, rbar_next) = 0
```

The implementation floors U at 1e-15 and caps exp(eta) at exp(80) in L for numerical protection. It returns invalid predictions
for nonfinite/nonpositive density or N > 10 cells/pixel^2. These are numerical safeguards, not biological laws. Observation times
are rounded to the nearest solver step; duplicate rounded times share a prediction.

Use dt = clip(max_duration/1200, 1/240, 1/120) days per medium trajectory during search (6–12 minutes). Rescore and refine at
6 minutes, then check against 3 minutes. Across all fitted observation times, maximum absolute differences must be below 0.02
in log density, 0.02 in coverage, 0.03 in relative log-area quantiles, 0.03 in log gap, and 0.02 in Clark–Evans. Timestep checks
establish numerical consistency, not biological adequacy. Age-cohort work grows approximately quadratically in the number of steps.

## 11. Parameters and simulator transfer

The single-component baseline has 12 continuous coefficients per ancestry group, plus profiled b and a discrete kinetic scenario.
Bounds below reproduce the baseline search; they are not claims about universal biological ranges.

| Parameter | Bounds | Search scale |
|---|---:|---|
| G1 low/high endpoints (/day), each | 0.1–24 | log |
| oxygen half-response (%) | 0.001–100 | log |
| media Hill exponent | 0.01–100 | log |
| equilibrium_spacing xeq | 0.55–0.995 | linear |
| repulsion speed s (pixels/day) | 0.1–100000 | log |
| pressure half-inhibition K | 0.03–100 | log |
| target G1 radius r0 (pixels) | 3–120 | log |
| initial density rho0 (cells/pixel^2) | 0.000001–0.005 | log |
| initial cluster size m0 | 1–1000 | log |
| initial volume multiplier vinit | 0.25–4 | log |
| initial G1 fraction fG | 0.02–0.98 | linear |

For each requested medium, evaluate the Hill function first and write a concrete configuration:

| PhysiCell setting | Value |
|---|---|
| Cycle model | separated flow cytometry, code 6 |
| G1 duration, stochastic | 1440/lambda0(media), minutes |
| S/G2/M, fixed | (480,240,60)*(T*1440/780), minutes |
| Apoptosis hazard | mu/1440, /minute |
| Apoptotic duration | 0; immediate removal at the simulator's update resolution |
| Necrosis, motility, secretion, uptake, transformation | disabled/zero |
| G1 target total volume | V0 = 4*pi*r0^3/3 |
| G1 target nuclear volume | V0*540/2494 |
| Repulsion | s/1440, pixels/minute |
| Adhesion | (s/1440)*((1-xeq)/(1-xeq/1.25))^2 |
| Relative adhesion range | 1.25 |
| Pressure rule | default,pressure,decreases,cycle entry,0,K,2,0 |
| Simulator diffusion-clock / mechanics / phenotype steps | 0.5 / 0.5 / 6 minutes |

The inactive substrate is identically zero. The runtime skips its diffusion solve. Oxygen is a *condition-level input* evaluated
before export, not a dynamically consumed substrate in this baseline. Varying media during a trajectory or allowing oxygen gradients
requires an explicit extension to the exporter and runtime; merely adding XML user parameters would not implement it.

Generate N0 = max(1,round(rho0*W*H)) cells and C0 = min(N0,max(1,round(N0/m0))) centers, uniformly in the domain. Allocate cluster
sizes as evenly as possible, shuffle sizes, and place each cluster as a compact triangular lattice patch with random orientation
and spacing 2*rbar(0)*xeq. Wrap *initial* positions into the rectangle. Subsequent mechanics uses the XML virtual walls, not periodic
boundaries. Initial phases sample G1 with probability fG, otherwise a uniform post-G1 age; pre-grow volumes at one-minute steps
and multiply by vinit. Use the sample mean initialized radius for simulator lattice spacing. Record integer rounding and the seed.

The CSV header is `x,y,phase,elapsed,nuclear_solid,cytoplasmic_solid,fluid`; phase indexes are 0:G1, 1:S, 2:G2, 3:M. Elapsed times
are minutes within the current phase; volumes are absolute pixel^3. The adapter sets cycle state and doubled post-G1 targets,
then overwrites component volumes and recomputes geometry. `sample_times.txt` contains sorted unique times in minutes, one per line.
Round requested observation times upward to the 0.5-minute simulator clock and keep the acquisition-to-output mapping.

The template domain is 4200 by 3300 pixels; a central 1400 by 1100 crop was used to reduce wall effects. These dimensions are
examples to match a particular image scale, not biological constants. Choose and record domain/crop sizes for each dataset.
Set mechanics voxel size at least max(40, 2.5*r0*(2*max(1,vinit))^(1/3)+5) pixels, revisiting this for extensions with larger cells.
The runtime has a 200000-cell resource guard and stops after saving all requested samples. Output folder must exist.

## 12. Provenance and limitations

This specification follows the accepted Hill calibration's `colony.py`, `joint.py`, `scoring.py`, `spatial.py`, and `RUN.md` in
`hypothesis_tests/20260921_130639_hill_g1/`, and the simulator adapter/export mapping in the immediately preceding accepted pooled
baseline `hypothesis_tests/20260921_114920_pooled_colony/physicell/`. These are provenance records, not required input sources for
future fits. New evidence should come from canonical `data/longitudinal_analysis/` products and the current run's frozen frame.
The original force/volume/cycle implementation is in the local PhysiCell 1.14.2 source. The runtime retains its source license.

Earlier finite-well derivation prototypes motivated the virial closure; the equations above explicitly specify the current
Poisson-density implementation instead. No old fitted trajectories or lineage-specific coefficients are embedded in this template.

Major approximations are common colony size, homogeneous centers, representative local pressure and radius, mean-volume cohort
merging, fixed center density despite death/coalescence, heuristic nearest-neighbor mixing, and shared stationary initialization.
The pressure response is nonlinear, so applying it to mean pressure need not equal averaging single-cell entry rates. The fast
model therefore requires agent-based validation on counts, both area measures, and both organization measures. Wall and observation
operators can also cause discrepancies. Neither the smooth surrogate nor a successful timestep check establishes global optimum,
parameter identifiability, adaptation mechanism, or validated transfer of a newly calibrated parameter set.
