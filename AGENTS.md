---
editor_options: 
  markdown: 
    wrap: 144
---

# Agent Notes for cloneID_rjb

Ignore all skills in the deprecated_skills folder.

This project is being used to test automated agentic research workflows. When working on a hypothesis test, keep all outputs within a single folder,
by default `hypothesis_tests/<YYYYMMDD_HHMMSS><_optional_descriptive_identifier>/*`. Ignore ALL outputs from old hypothesis test runs.

For other ad-hoc requests which are not part of a current hypothesis-testing workflow, default to project-local `tmp/` or `dev/` folders unless
directed otherwise.

Raw cloneID snapshots under `core_data/`, derived outputs under `data/`, and the live Markdown instance/protocol database under
`lab_records/instance_protocol_db/` are local state and must not be committed. Refresh and promote core data only through the documented
cloneID database skill workflow. Update the Markdown database serially and validate it after every bounded turn.

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
