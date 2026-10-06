# Scientific decisions at execution

The scientific contract is a short, concrete record inside the current analysis folder. It should make the following decisions
reviewable without creating a separate planning bureaucracy. Preserve decisions already authorized in the conversation.

| Subject | Reusable core | Execution-specific decision |
|---|---|---|
| Cell biology | G1 waiting, fixed post-G1 phases, volume dynamics, pair mechanics, pressure inhibition | Applicability, cycle/death scenario and justified extensions |
| Culture conditions | Positive Hill responses and normalized reference rates are available mechanisms | Relevant changes, known concentrations, affected parameters, response shape and interactions; confirm with user |
| Lineage | Arbitrarily many independently parameterized groups | Evidence for shared versus separate coefficients; confirm distinct-lineage partition with user |
| Longitudinal change | Shared stationary biology; all fitted biology branch-specific in constant; default G1-only adaptation | Explain biological suitability, alternatives, branch boundaries, clock, origin and within-episode behavior |
| Initialization | Density, cluster size, volume multiplier and cycle fraction | Whether initialization can be shared; documented seeding changes and resets |
| Observation | Density/count conversion, envelope coverage, relative area and organization operators | Measurement meaning, image scale/crop, count-scale changes, supported terms, uncertainty and weights |
| Computation | Bounded multistart, exact nesting, simulator ranking, resumable dependencies | Starts, bounds, resource limits, simulation seeds/domain/resolution and runtime allocation |

Do not infer independent ancestry from labels, filename substrings, treatment assignment or arbitrary graph components. Do not
copy shared ancestral observations into every descendant. Document transformation/mixing boundaries and explicit episode membership.
Condition effects should encode plausible biology rather than create independent free parameters for every medium label. Quantitative
composition supports quantitative response models; unknown composition needs clarification or an explicitly agreed categorical model.
Perfectly co-varying components cannot be separated from this dataset alone.

Propose these before implementing the condition/group adapter:

1. Table of groups, included lineages and evidence for sharing/separation.
2. Table of condition changes, units/reference levels, proposed target parameters and response equations.
3. Stationary/constant/adaptation definitions and which parameters are shared; demonstrate proposed nesting.
4. Observation support, image geometry, uncertainty/weights, initialization and adaptation clock.
5. Measured runtime evidence and expected campaign shape/time/core budget, including preparation, checks and reporting.

Explain the default sharing and adaptation target in biological terms. Highlight apparent mismatches with the instances under
study, using the experimental selection or intervention and available evidence; propose alternatives for user consideration.
A useful concern belongs in the interpretation even when the user retains the default. Do not silently revise settled choices.

Before proposing different harvest or passage rules, show terminal abundance by lineage with medians/distributions, sample sizes,
count provenance and elapsed culture time. Distinguish recorded terminal observations from known confluence-triggered thresholds.
Use protocol evidence to decide latent initialization sharing; measured seeding counts need not be forced initial conditions.

Accumulated active-culture time is a possible adaptation clock; passage index is another. Choose from the experimental question
and evidence, declare units/origin, and exclude frozen intervals when using culture time. The core does not choose automatically.
A sigmoid may be frozen at episode start. Continuous within-episode change requires matching updates in both simulator and
approximation; XML constants alone do not implement it.

No current experiment's cell-line names, ploidy partition, oxygen schedule, medium labels, branch count, passage list, calibration
vectors, image paths or results belong in the skill. Those are adapter inputs and analysis outputs. Data rebuilding, segmentation,
and broader biological model discovery remain separate work; identify missing inputs rather than silently inventing them.
