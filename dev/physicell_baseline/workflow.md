# PhysiCell baseline and hypothesis starting point

This is the concrete modelling example and counterfactual for new user-specified hypotheses in cloneID_rjb. Extend it explicitly rather
than invoking the deprecated hypothesis runners or planning requirements. The template numbers are illustrative, not fitted coefficients.

## Describe the extension

Read the [mechanistic model and derivation](mechanistic_model.md), inspect the relevant lineage, media and laboratory evidence, and state
which mechanism changes relative to the stationary baseline. Explain the counterfactual, biological parameter sharing and observation
mapping. Distinguish a hypothesis about biology from a change in measurement or initialization. Use only CellSegmentations and its
subdirectories for images, masks and per-cell features, with a configurable machine-local root.

The [adaptation specification](adaptation_proposal.md) is an example extension of G1-exit kinetics, not a required hypothesis. Its dataset
and branch choices are illustrative; reconstruct the current user's inputs rather than inheriting old analysis selections or results.

## Calibrate only the agreed model

Use the repo-local [physicell-modeling skill](../../.codex/skills/physicell-modeling/SKILL.md) for portable fitting primitives, resource
inspection, a confirmed dataset adapter, PhysiCell scoring and report generation. Its stationary/constant/adaptation comparison is available
when that nested comparison is requested. Agree the scientific choices and compute budget for the present question before dependent work.
Do not treat historical optimizer counts, CPU allocations or model-selection plans as authorization to run a campaign.

Keep inputs, code, observations, QC, seeds and compute accounting in a new `hypothesis_tests/<timestamp>_<description>/` folder.
Reusable canonical evidence remains under `data/`; never recover it from previous hypothesis-test runs.

## Inspect the generic simulator assets

This portable baseline retains the [XML template](PhysiCell_settings.xml), [pressure-rule CSV](cell_rules.csv) and
[runtime adapter](baseline_runtime.cpp). They describe the example's simulator behavior. They require a compatible external PhysiCell
engine, generated initial cells and sample times; the XML alone is not a ready-to-run experiment. The derivation documents units and
transfer assumptions. Development used PhysiCell 1.14.2.

The modelling skill bundles its maintained exporter/runtime and report assets. Use that package together for new calibration work;
record engine version, code/input hashes and verify transfer for the actual adapter. These example assets preserve the baseline
specification and should not be silently mixed with a different exporter or changed biology.

Produce a report with simulator-scored results, matched microscopy where available, actual protocol, limitations and compute use.
A synthetic package check establishes software behavior, not biological validation or correctness of a newly assembled dataset.
