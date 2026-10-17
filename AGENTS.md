---
editor_options: 
  markdown: 
    wrap: 144
---

# Agent Notes for cloneID_rjb

Ignore all skills in the deprecated_skills folder.

## Storage and compute budgets (2026-10-17)

Before substantial work, read project-local resource rules and the user's current budget. If no explicit rules are available, assume a
20 GB total disk cap and up to 32 CPU cores for 2 hours (64 CPU-hours), state those assumptions to the user, and plan within them.
Existing explicit instructions override these defaults; do not repeatedly ask for an already specified budget.

For cloneID_rjb, the default budgets are:

- **Durable storage: 50 GB for the whole project.**
- **Transient peak storage: 100 GB for the whole project during an active task**, returning to at most 50 GB after completion,
  failure or cancellation.
- **Compute: up to 1,000 concurrent CPU cores for 1 hour**, with a maximum of 1,000 CPU-hours, unless the user specifies otherwise.

GB means 1,000,000,000 bytes. Storage includes all project-created files: the checkout, local data, runs, temporary files, caches,
archives and copies on shared or node-local storage. Symlinks and moving files to another volume do not remove them from this budget.
Shared source data maintained independently of this project, such as CellSegmentations, are excluded; project-created copies count.

Measure allocated filesystem blocks, including per-file and per-directory overhead, rather than only logical file lengths. Include
this overhead in reservations; many small records can occupy much more space than their contents.

Estimate current durable use, peak concurrent output and inode demand before launch. Use task-scoped scratch, bounded concurrency or
disk reservations, and prompt measurement/compaction so simulations do not accumulate unbounded raw output. Retain compact prepared
inputs, fitted parameters, scores, provenance, accounting and the small selection of fields needed for reporting. Remove expendable
raw trajectories, duplicate copies and temporary products after measurement, including on failures and cancellation. Reclaim external
shared-storage products as well as files under the checkout. Never expand storage silently or substitute a larger filesystem for a cap.

Respect disk and compute limits while finishing the workflow: harvest available checkpoints, report incomplete or poor results honestly,
and run cleanup instead of abandoning the report at a quality threshold or resource limit. Report measured CPU-hours, elapsed time and
post-cleanup storage. Resource budgets do not authorize deleting source code, irreplaceable input evidence or another agent's active work.

## Current direction (2026-10-16)

Stricken text below (2026-09-21) is not necessarily entirely superseded but should be viewed with healthy skepticism. 



## ~~Current research direction (2026-09-21)~~

~~All prior hypothesis-testing workflows and plans are deprecated, including hypothesis-workflow instructions still present in skills or
reference documents. Start new user-specified hypotheses from `dev/physicell_baseline/workflow.md`: a concrete modelling example and
counterfactual to extend explicitly. Do not automatically invoke legacy hypothesis runners, model-selection requirements, or planning
deliverables. Database preparation and laboratory-record maintenance remain supporting infrastructure. The output-location and local-state rules
below still apply.~~

~~This project is being used to test automated agentic research workflows. When working on a hypothesis test, keep all outputs within a single
folder, by default `hypothesis_tests/<YYYYMMDD_HHMMSS><_optional_descriptive_identifier>/*`. Ignore ALL outputs from old hypothesis test runs.~~

~~The narrow exception is reusable per-analysis-group longitudinal evidence: canonical growth and spatial products belong under
`data/longitudinal_analysis/<analysis_group_id>/`. The hypothesis-specific canonical audit, report, figures, interpretation, and downstream work
must remain in the current hypothesis-test folder. Reuse canonical products through `data/`; never recover them from an old hypothesis-test
run.~~

~~For other ad-hoc requests which are not part of a current hypothesis-testing workflow, default to project-local `tmp/` or `dev/` folders
unless directed otherwise.~~

~~Raw cloneID snapshots under `core_data/`, derived outputs under `data/`, and the live Markdown instance/protocol database under
`lab_records/instance_protocol_db/` are local state and must not be committed. Refresh and promote core data only through the documented cloneID
database skill workflow. Update the Markdown database serially and validate it after every bounded turn.~~

## Imaging and segmentation data

Use only **CellSegmentations**, including its subdirectories, for imaging, segmentation masks and per-cell feature products. On RED the root is
`/share/lab_crd/CellSegmentations`. It is also mounted on the workstation; resolve that machine's mount locally rather than assuming the RED
path. Prefer `CELLSEGMENTATIONS_ROOT` or an explicit path, keep manifest paths relative to that root, and do not silently fall back to older
image collections. A manifest records available products; verify image/mask/feature matching for each analysis. Detailed manifests are local
state and distributed only in encrypted snapshots, not committed in plaintext.

## Terminal-readable communication

The user reads responses and Markdown documents in a terminal where LaTeX does not render. Write equations in plain ASCII, preferably in fenced
`text` code blocks, and define symbols in ordinary language. Use readable notation such as `dN/dt`, `sqrt(x)`, `x^2`, `sum(...)`, and named
operators such as `gradient` and `divergence`. Do not rely on LaTeX delimiters or commands for mathematical content unless the user explicitly
requests a rendered-math format. Explain what each equation means alongside the notation.

## Environments/Coding

Check for available conda environments - likely one is available with the dependencies you need.

Use `scripts/agentRrunner.sh` as the default wrapper for all R execution by the LLM agent. This includes `Rscript`, `R CMD`,
`rmarkdown::render()`, and any other R commands run for inspection, analysis, plotting, or report rendering.

For long running or compute-heavy jobs (\>4 cores, \>10mins,GPU required, \>8GbRAM) use SLURM.

Current QOS settings from `sacctmgr show qos format=Name,Priority,MaxTRESPU,MaxJobsPU,MaxSubmitJobsPU,GrpTRES -P`:

``` text
Name|Priority|MaxTRESPU|MaxJobsPU|MaxSubmitPU|GrpTRES
normal|0|cpu=64|1000001||
small|0|cpu=475|1000001||
large|0|cpu=1425|1000001||
xlarge|0|cpu=1800|1000001||
partsmall|0||1000001||cpu=250
medium|0|cpu=950|1000001||
xxlarge|0|cpu=3000|1000001||
```

For future Slurm submissions, choose the QOS that is likely to get the fastest deployment for the requested job shape instead of defaulting to
`normal`. For large arrays of small single-CPU jobs, `small` or `large` may be more appropriate than `normal` depending on the desired
concurrency and current limits.

Do not add Slurm array throttles such as `--array=1-100%10` by default. A `%` limit should only be used when there is a clear resource,
filesystem, scheduler, or user-requested reason to cap concurrency. When a higher-concurrency QOS is chosen for many small jobs, leaving the
array unthrottled is usually the intended behavior.

##Subagents/Teams. Two main modes for teamwork: 1) When the user asks you to work *with/in/as-part-of* a team, self-organize into whatever
hierarchy seems most effective for the given task (subject to any explicit user requests). 2) When the user asks you to *launch/deploy* a team,
create a subagent team but do not participate in the team or attempt to micromanage it. The initiating agent's role is to create a team quickly
and return to the user thread immediately, without overseeing the team's progress.
