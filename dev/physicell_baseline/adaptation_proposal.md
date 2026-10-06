# Proposed default adaptation extension

2026-09-21. Design recommendation for discussion, not an implemented or accepted change to the stationary baseline.

## One changing parameter

Let the uncrowded G1-exit rate change with lineage history. Keep pressure sensitivity K, mechanics, death, post-G1 duration, and
latent seeding initialization stationary within the baseline ancestry-sharing group. This changes proliferative propensity while
preserving the existing routes by which growth changes cell-cycle composition, crowding, and spatial organization. It does not
guarantee that spatial adaptation can be explained by this one parameter.

Use a phenomenological sigmoid, without attributing the change to mutation, selection, or plasticity. Here “adaptation” names a
longitudinal parameter trend; even an increasing rate is not by itself evidence of a heritable fitness advantage.

```text
S_l(s) = 1 / (1 + exp(-k_l * (s - m_l)))
r_l(s) = r_early_l + (r_late_l - r_early_l) * S_l(s)
lambda0_l(media,s) = h_group(media) * r_l(s)
lambda_l(t) = lambda0_l(media,s) / (1 + (P(t)/K)^2)
```

Index l denotes a declared longitudinal lineage branch; s is accumulated culture time in days from a documented origin.
r_early and r_late are positive reference-medium G1-exit rates (/day), m is the transition midpoint (days), and k > 0 is steepness
(/day). Both endpoint orderings are allowed. The endpoints are asymptotes, not necessarily rates at the first and last observations.
The 10%-to-90% transition duration is `2*log(9)/k`, approximately `4.394/k` days.

Estimate these four coefficients for each supported lineage branch. Keep the medium-response shape shared within its ancestry
group. h_group is the existing medium response normalized to one at a declared reference composition. If jointly refitting, replace
the original absolute medium-response scale with r_l; do not fit an additional free multiplicative amplitude. For example, the
single-component Hill response can be written:

```text
f(x) = 1 + (R-1)*H(x; x50,hill_exponent)
h_group(x) = f(x)/f(x_ref)
```

R is the positive high/low rate ratio. This retains the baseline Hill shape without a redundant scale. Alternatively, for an
extension of an already frozen baseline, normalize its fixed media curve and fit only the lineage sigmoid coefficients. State
whether calibration is frozen or joint; they answer different questions. Do not refit two independent media endpoints as well as
two independent adaptation endpoints. Medium and culture age must have adequate overlap to distinguish their effects.

## Culture clock and branches

Use accumulated time in active culture, excluding documented frozen storage. Start at the relevant experimental exposure or a
documented common origin. Do not reset at every passage, assay, or medium change. Passage number is a fallback if durations are
unavailable, with the resulting dependence on passaging practice made explicit. Do not use inferred population doublings as the
default clock: that would make the clock depend on the growth response being fitted.

Shared ancestral episodes are one set of observations, not independent copies for every descendant. Carry their history forward
at a split. For the simplest initial fit, declare branches after experimental allocation and fit their four-parameter curves on
post-allocation observations. This permits branch-specific initial levels and does not claim to model inheritance through the
split. If pre-split observations are included in a joint tree fit, use one ancestral trajectory and constrain child starting rates
to its terminal value; four independent coefficients per child no longer remain freely estimable. Defer that tree extension
unless the hypothesis needs it. Mixing or transformation requires an explicit new boundary.

## Constant within each passage by default

Evaluate r_l at accumulated culture time at the start of each episode, then hold that rate constant until its end. The ordinary
pressure response still changes during the episode. Retain the shared baseline seeding initialization: only the rate carries
longitudinal history in this extension. Refeeding does not constitute a new passage or reset the adaptation clock.

For PhysiCell transfer this needs only the episode-specific concrete G1 rate in exported XML. The stationary runtime can remain
unchanged. The fitting approximation must evaluate distinct `(media, episode-start adaptation rate)` trajectories; the baseline's
one-trajectory-per-medium shortcut no longer generally applies. No adaptation fitting code is supplied in this proposal.

Continuous within-passage change uses the same four coefficients: replace s with `s_start + t`, where t is days since seeding.
This is a small change to a time-stepped approximation and adds no optimization dimensions. PhysiCell also needs a runtime update
of the uncrowded rate coordinated with the pressure rule; changing XML alone is insufficient. Computational cost comes mainly
from more distinct trajectories, not sigmoid evaluation. Check the episode-frozen approximation by comparing the sigmoid at the
start and end of the longest episodes and, when the difference is material, comparing predictions using the continuous version.

## Comparison and interpretation

Retain the stationary baseline as the primary counterfactual. Also fit a constant rate per lineage when asking whether there is
longitudinal change: otherwise static lineage differences can masquerade as evidence for adaptation. The sigmoid includes that
constant case when its two endpoints are equal; midpoint and steepness are then unidentifiable and should not be interpreted.

Fit the original count and image observables jointly, rather than fitting a sigmoid to separately estimated passage growth rates.
Keep the same observation operators and objective weights. Use positive-coordinate searches, multiple starts, explicit bounds,
and the existing timestep checks. Rate bounds must apply to the effective media-adjusted rates, not just reference-medium endpoints.
Choose midpoint and transition-duration bounds from the recorded observation window and temporal resolution; report bound hits.

A four-parameter curve is a reasonable candidate, but sparse observations covering only part of a transition may leave its plateau,
midpoint, and steepness weakly constrained. Report supported rate trajectories rather than interpreting poorly determined
asymptotes. This is a design-specific concern, consistent with the broader importance of checking sigmoid parameter identifiability
([Simpson et al., 2022](https://pubmed.ncbi.nlm.nih.gov/34973274/)). Compare held-out episodes or temporal blocks, preserving lineage
dependence, and inspect profile discrepancy curves. The baseline loss is a composite discrepancy, not a calibrated likelihood;
do not apply ordinary likelihood-ratio significance tests directly to it.
