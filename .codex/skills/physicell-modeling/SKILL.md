---
name: physicell-modeling
description: Propose, fit and compare mechanistic cell-growth models using a fast approximation and PhysiCell, orchestrate bounded multistart campaigns, and produce interactive reports with matched microscopy. Use for PhysiCell calibration and reporting; dataset reconstruction and segmentation are separate tasks.
---

# PhysiCell modeling

Fit mechanistic cell-growth models within the agreed time and CPU budget and produce inspectable reports. Use the approximation for
guidance and PhysiCell for native evaluation. Resolve prepared inputs, Python environment, engine executables and scheduler resources
explicitly. Development used **PhysiCell 1.14.2**.

## Repository context

Follow `AGENTS.md` and the user's model and scope. A baseline supplies a fitted mechanistic reference for hypothesis-driven changes,
refitting and comparison. In a lineage-determined baseline, lineage evidence defines identity and biological parameter sharing. In a
perspective-guided baseline, investigator-chosen accompanying measurements define states and parameter sharing. SUM-159 hypoxia is a
pilot case study, not a universal choice of cell line, conditions or states.

For these baselines and fresh fitting from prepared data, read [prepared-baselines](references/prepared-baselines.md). It routes to
the dedicated runner, observer and fixed screening/refinement/validation procedure. The completed pilots and the scientifically
unexecuted scratch runner are distinct evidence. Do not impose the older stationary/constant/adaptation comparison on this workflow.

For other requested model comparisons, use the general guidance below and the relevant references. Keep full runs and private
provenance local, normally under `hypothesis_tests/`; use `tmp/` or `dev/` for development. Track reusable code/configuration and selected
public figures/text rather than the full run directory.

Use only CellSegmentations, recursively including segmentation masks and per-cell features, for imaging inputs. Resolve its root from
`CELLSEGMENTATIONS_ROOT` or an explicit path. `/share/lab_crd/CellSegmentations` is the RED location; the workstation has its own mount.
Keep manifest paths relative to the root and verify image/mask/feature matches before using them. Never fall back to another collection.

## Establish the scientific contract

Read [scientific decisions](references/scientific-decisions.md) and the associated [canonical model](references/canonical-model.md).
Inspect the actual data, lineage evidence, condition changes, seeding and measurement protocols. Separate biological choices
from implementation choices. Present a concrete proposed model, parameter-sharing map, observation mapping and budget.

- When culture conditions obviously change, propose the affected mechanism and response form. **Obtain user confirmation before
  embedding that condition response in PhysiCell and its approximator.** A medium label alone does not identify a mechanism.
- Clearly distinct lineages suggest separate parameter sets. **Confirm the sharing/separation decision before execution.**
- Existing explicit agreement satisfies these checkpoints; do not ask again. Resolve routine implementation choices autonomously.
- The included models are starting points, not instructions to impose oxygen responses, ploidy groups or three treatment arms.
  Decide the adaptation coordinate, branches, seeding resets, measurements and weights for this execution.
- For a requested stationary -> constant -> adaptation comparison, default to shared stationary biology,
  all fitted biological coefficients varying by branch in constant, and only G1 exit changing longitudinally in adaptation.
  Initialization and observation sharing are separate choices. Explain these defaults and flag biological mismatches before
  implementation; propose alternatives without silently changing the agreed model.

If approval is still needed, make the proposal reviewable first and continue independent data/resource inspection. Explain that
these two scientific checkpoints come from this skill. Do not start dependent modelling work while their answers are pending.

Communicate the current stage, completed work, next steps and blockers as work progresses. Distinguish confirmed choices,
proposals and routine implementation. Surface outstanding decisions with evidence, a recommendation and model consequences;
if none require input, say so and continue. Prior approvals and delegated decisions remain active.

## Prepare and execute

For the prepared-baseline runner, follow its linked reference. For another model/adapter, read
[execution](references/execution.md) and [adapter contract](references/adapter-contract.md); read
[nested biological parameterizations](references/adaptation.md) when that comparison is requested. Freeze inputs and code in the current
analysis folder and implement the confirmed adapter there. The generic bundled core provides population/volume-cohort simulation,
scoring, transfer, assumption diagnostics and image coloring. Its older 29-column/five-component observer is a different contract from
the prepared SUM-159 baseline's 30-column/six-component observer; never substitute one silently for the other.

Start fresh fits without historical fitted vectors unless the user requests another initialization. For the nested comparison, initialize
half the new starts from the best simulator-scored parent and half from other diverse competitive parents; retain exact
embedded parents as permanent candidates. Use deterministic seeds and score/ID tie-breaking. Verify the nesting numerically.

Before proposing the campaign budget, use light runtime benchmarks at representative observed densities, including dense
harvest fields, unless applicable measured timings already exist or the user requests otherwise. Discuss implementation effort,
search breadth, simulation and reporting costs, per-stage elapsed time/CPU-hours and total resources; agree the user's preferred
resource envelope. Numerical defaults are proposals, never agreed budgets. See execution.md for timing and budgeting details.

Submit the agreed models, phases and report in one dependency campaign, with no unnecessary intermediate user checkpoints. Within each
stage, queue each candidate's PhysiCell evaluations as its optimization finishes; share one CPU cap across fitting, finalization
and simulation. Child fitting still waits for completed PhysiCell parent ranking. Every final vector receives evaluation; transfer
agreement is descriptive, not a hard eligibility gate.

For a generic adapter campaign, use `scripts/submit_campaign.py` with explicit task counts and commands. The prepared-baseline workflow
uses its dedicated runner instead. Inspect the applicable dry-run plan first. Submit
only the requested work. On failure, preserve completed results, identify the cause, and resume missing work without silently
expanding the agreed budget. If every fit in a required group fails, produce the failure report and stop its dependent fitting.

## Report and verify

For generic reports, read [reporting](references/reporting.md) and [report data contract](references/report-data.md). Use the generic
[HTML template](assets/report/template.html) and `scripts/render_report.py`; supply the actual model definitions and protocol.
The report defaults to stage-best representatives and a separate 5% near-best cutoff for each stage. Include raw/mask/simulator
comparisons with all imaged passage timepoints stacked, 20-passage grids with selectable count/area/spatial views,
loss components, transfer agreement, parameter diversity and compute usage.

Check physical/numerical transfer, score accounting, inherited candidates, image/time matching and browser behavior. Keep parameter and
mixture settings explicit when relating image and assay scores. Provide
links to the finished report and frozen evidence, stating what was verified. Report facts and the actual protocol in professional
language. Do not substitute an optimizer loss for simulator performance or frame the report around repetitive disclaimers.

For reporting-only requests, reuse saved outputs and skip fitting. No engine run is required to re-render existing snapshots.
