# Nested biological parameterizations

The complete baseline includes all three stages after confirming the group/branch structure and condition response.
Stationary shares fitted biology within a group. Constant allows every fitted biological coefficient to differ by branch,
including mechanics, pressure response, and any fitted cycle/death or condition-response coefficients. Fixed model constants
remain fixed. Adaptation retains those branch-specific coefficients but changes only G1 exit longitudinally by default.
Initialization and observation/count-conversion sharing are agreed separately and preserved across stages.

Explain these defaults and identify where they may conflict with the experimental biology; suggest appropriate adaptation
targets when warranted. Do not silently replace the agreed target. Let h(branch,c) be the agreed positive condition multiplier,
normalized to 1 at a declared reference composition; its fitted coefficients follow the stage's biology-sharing map. Use only
one reference-rate amplitude; an additional free condition amplitude would duplicate it.

```text
stationary: r(branch,s) = r_shared
constant:   r(branch,s) = r_branch
adaptation: r(branch,s) = early_branch + (late_branch-early_branch) * S(s)
S(s) = 1 / (1 + exp(-2*log(9)*(s-midpoint_branch)/width_branch))
lambda0 = h(branch,condition) * r(branch,s)
lambda(t) = lambda0 / (1 + (pressure(t)/K_branch)^2)
```

K_branch denotes the branch's pressure half-inhibition coefficient; stationary constrains it and every other fitted biological
coefficient to equality across branches. The equations above display the G1 component of the complete parameter-sharing map.

Early/late are positive asymptotic reference G1-exit rates (/day), not observed initial/final rates or total division rates.
Midpoint is the coordinate at half-transition; positive width is the 10%-90% span. Either endpoint ordering is allowed.
The adaptation coordinate s and its units/origin are execution-specific (for example active-culture days or passage index).
By default evaluate at episode start and hold lambda0 constant within the episode. Pressure still changes over time.

Stationary embeds exactly into constant by copying every shared fitted biological coefficient to every branch, including rates.
Constant embeds into adaptation by equal early/late G1 endpoints; midpoint/width then have no effect. Copy every other branch
coefficient unchanged, and preserve initialization, observation mapping and count offset. `embed_rates` handles the G1 block;
`embed_branch_parameters` handles other fitted biological coefficients. The adapter routes each branch's complete parameter set
to both engines. Check equality of all effective parameters and schedules at every included setting before reusing outputs. The exact embedded parent remains eligible
regardless of whether new optimization improves on it.

Review bounds on effective condition-adjusted rates, not just reference endpoints. Choose timing bounds from the actual coordinate
range and resolution. Shared ancestry is counted once. Separate branch sigmoids do not automatically implement ancestry constraints
at a split. If continuity or continuous within-episode rates are required, implement that extension in both engines.

Use stage-specific 5% near-best plots to show retained solution diversity. Compare early/late endpoints across stages by duplicating
stationary/constant values for display only. Omit timing parameters for flat curves. Plot positive values on log10 axes; declare any
shift for parameters that can be zero. Do not take logarithms of a nonpositive coordinate or silently impose passage-specific shifts
when the chosen clock uses other units.
