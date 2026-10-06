---
name: physicell-modeling
description: Propose, fit and compare mechanistic cell-growth models using a fast approximation and PhysiCell, orchestrate bounded multistart campaigns, and produce interactive reports with matched microscopy. Use for PhysiCell calibration and reporting; dataset reconstruction and segmentation are separate tasks.
---

# PhysiCell modeling

Produce the best simulator-scored parameter sets reasonably attainable within the agreed time and CPU budget, together with
an inspectable HTML report. Use the approximation for guidance and PhysiCell for final ranking. The package is self-contained;
input data, Python environment, engine executable and scheduler resources are resolved at execution, never from historical fits
or a presumed installation path. Development used **PhysiCell 1.14.2**.

## Repository context

Follow `AGENTS.md` and begin new hypotheses from `dev/physicell_baseline/workflow.md`, explicitly extending the concrete model and
counterfactual. Historical hypothesis runners and planning requirements are deprecated. The nested stages below apply when the user
chooses this calibration comparison; they are not mandatory stages for every hypothesis. Fit and report only the agreed model and scope.
Keep outputs in the current hypothesis-test folder; use `tmp/` or `dev/` for other development tasks.

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
- The included baseline is a starting model, not an instruction to impose oxygen responses, ploidy groups or three treatment arms.
  Decide the adaptation coordinate, branches, seeding resets, measurements and weights for this execution.
- For a requested nested calibration comparison, the complete baseline is stationary -> constant -> adaptation plus reporting. Default to shared stationary biology,
  all fitted biological coefficients varying by branch in constant, and only G1 exit changing longitudinally in adaptation.
  Initialization and observation sharing are separate choices. Explain these defaults and flag biological mismatches before
  implementation; propose alternatives without silently changing the agreed model.

If approval is still needed, make the proposal reviewable first and continue independent data/resource inspection. Explain that
these two scientific checkpoints come from this skill. Do not start dependent modelling work while their answers are pending.

Communicate the current stage, completed work, next steps and blockers as work progresses. Distinguish confirmed choices,
proposals and routine implementation. Surface outstanding decisions with evidence, a recommendation and model consequences;
if none require input, say so and continue. Prior approvals and delegated decisions remain active.

## Prepare and execute

Read [nested biological parameterizations](references/adaptation.md), [execution](references/execution.md) and [adapter contract](references/adapter-contract.md). Copy reusable files into the
current analysis folder, freeze inputs and code, and implement the confirmed dataset adapter there. The bundled core provides
population/volume-cohort simulation, scoring, transfer, assumption diagnostics and image coloring; it deliberately has no
project-specific data loader or hardcoded ancestry/arm mapping.

Start stationary fits from scratch unless the user explicitly requests another initialization. For nested stages, initialize
half the new starts from the best simulator-scored parent and half from other diverse competitive parents; retain exact
embedded parents as permanent candidates. Use deterministic seeds and score/ID tie-breaking. Verify the nesting numerically.

Before proposing the campaign budget, use light runtime benchmarks at representative observed densities, including dense
harvest fields, unless applicable measured timings already exist or the user requests otherwise. Discuss implementation effort,
search breadth, simulation and reporting costs, per-stage elapsed time/CPU-hours and total resources; agree the user's preferred
resource envelope. Numerical defaults are proposals, never agreed budgets. See execution.md for timing and budgeting details.

Submit the agreed complete baseline and report in one dependency campaign, with no intermediate user checkpoints. Within each
stage, queue each candidate's PhysiCell evaluations as its optimization finishes; share one CPU cap across fitting, finalization
and simulation. Child fitting still waits for completed PhysiCell parent ranking. Every final vector receives evaluation; transfer
agreement is descriptive, not a hard eligibility gate.

Use `scripts/submit_campaign.py` with the adapter's explicit task counts and commands. Inspect its dry-run plan first. Submit
only the requested work. On failure, preserve completed results, identify the cause, and resume missing work without silently
expanding the agreed budget. If every fit in a required group fails, produce the failure report and stop its dependent fitting.

## Report and verify

Read [reporting](references/reporting.md) and [report data contract](references/report-data.md). Use the generic
[HTML template](assets/report/template.html) and `scripts/render_report.py`; supply the actual model definitions and protocol.
The report defaults to stage-best representatives and a separate 5% near-best cutoff for each stage. Include raw/mask/simulator
comparisons with all imaged passage timepoints stacked, 20-passage grids with selectable count/area/spatial views,
loss components, transfer agreement, parameter diversity and compute usage.

Check physical/numerical transfer, score accounting, inherited candidates, image/time matching and browser behavior. Provide
links to the finished report and frozen evidence, stating what was verified. Report facts and the actual protocol in professional
language. Do not substitute an optimizer loss for simulator performance or frame the report around repetitive disclaimers.

For reporting-only requests, reuse saved outputs and skip fitting. No engine run is required to re-render existing snapshots.
