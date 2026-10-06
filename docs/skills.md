# Using the cloneID research skills

This checkpoint supplies three reusable skills: `cloneid-database-data`, `ingest-lab-records`, and `physicell-modeling`.
Their entrypoints and supporting code live under [`.codex/skills/`](../.codex/skills/). Work from the repository root so relative paths resolve.
The listener skill is not part of this distribution's supported workflow.

## Prepare your local data

Download the encrypted database tables, processed laboratory notebook, and imaging manifest from the snapshot page. Obtain the shared
password separately. Follow [snapshot download and decryption instructions](publishing.md); plaintext data and archives remain local.
The public snapshot metadata distinguishes source last-updated dates from the date the archive was packaged. Notebook processing coverage
and validation results are recorded inside its snapshot; a processed snapshot does not imply every notebook experiment has been curated.

Place the database inputs under `core_data/`, following the archive's layout. Metadata rebuilding needs `passaging.csv`, `media.csv` and
`perspective.csv`; LiquidNitrogen records use `liquid_nitrogen.csv`. Restore processed notebook evidence and the instance/protocol database
to their documented `lab_records/` locations. Keep source-accountability links and source snapshots together with the processed records.

The imaging archive is an inventory, not a copy of the images or segmentations. Access the **CellSegmentations** mount separately and set:

```bash
# RED only:
export CELLSEGMENTATIONS_ROOT=/share/lab_crd/CellSegmentations

# On the workstation, use its actual mount instead:
# export CELLSEGMENTATIONS_ROOT=/your/workstation/mount/CellSegmentations
```

Only this folder and its subdirectories are supported, including segmentation masks and per-cell features. Manifest paths are relative to
this root. A listed file is available evidence; it is not a guarantee of successful image/mask/feature matching. See
[imaging data guidance](imaging-data.md) for inventory fields and interpretation.

Inspect existing conda environments before installing dependencies. Metadata querying and laboratory-record helpers mostly use Python's
standard library. Metadata rebuilding and live database export use R; run all agent R work through `scripts/agentRrunner.sh`, which uses
Apptainer and a configurable container. Inspect a script's `--help` or referenced workflow for its exact dependencies.
The PhysiCell skill uses numpy, scipy, numba, pandas, scikit-image, matplotlib and plotly; its simulator requires a compatible external
PhysiCell engine (development version 1.14.2). The engine is not bundled. SLURM is required for substantial fitting campaigns on RED.

## Ask for a specific outcome

Name the skill explicitly in your request when you want its workflow. These example prompts describe tasks; they do not launch work merely
by reading this guide.

| Skill | Example request | What to expect |
| --- | --- | --- |
| `cloneid-database-data` | `Use $cloneid-database-data to trace the ancestry of clone <ID> and summarize its media changes using the local snapshot.` | A metadata answer with lineage/QC caveats; no live database refresh. |
| `cloneid-database-data` | `Use $cloneid-database-data to validate core_data and rebuild cleaned metadata.` | Validation plus graph tables under `data/`. |
| `cloneid-database-data` | `Use $cloneid-database-data to download a staged database refresh for review.` | A staged export, provenance and diffs under `tmp/core_data_refresh/`; promotion remains separate. |
| `ingest-lab-records` | `Use $ingest-lab-records to identify experiments relevant to <question> and reconstruct their design from the processed notebook.` | Read-only evidence retrieval with source references. |
| `ingest-lab-records` | `Use $ingest-lab-records to update one bounded item in the local instance/protocol database and validate it.` | A serial local update, turn note and validation results. |
| `physicell-modeling` | `Use $physicell-modeling to propose a model extending the PhysiCell baseline for <question>, using <lineages> and a budget of <resources>.` | A concrete scientific model, data/observation mapping and resource proposal before dependent fitting. |
| `physicell-modeling` | `Use $physicell-modeling to rebuild the report from these saved results: <current result folder>.` | An inspectable HTML report without starting new fits. |

For a new hypothesis, start with the concrete [PhysiCell baseline](../dev/physicell_baseline/workflow.md), name the counterfactual and the
extension you want to test. Older hypothesis runners and planning requirements are deprecated. A skill should follow your requested scope,
not automatically run every workflow it contains. Explicitly agreed scientific choices and budgets carry forward; repeat approval is not
required for the same decision.

## Inspect and retain outputs

- `core_data/`: local raw database inputs, never committed.
- `data/`: cleaned metadata, inventory and reusable analysis products, never committed.
- `lab_records/instance_protocol_db/`: local curated instances/protocols, updated serially and validated after each bounded turn.
- `hypothesis_tests/<timestamp>_<description>/`: the current hypothesis's frozen inputs, code, reports, figures and interpretation.
- `tmp/` or `dev/`: other development and temporary work.

Reuse canonical analysis products through `data/`, with appropriate freshness and coverage checks. Do not retrieve observations or results
from old hypothesis-test folders. The imaging inventory and notebook are evidence sources; assess protocol, timing, identity and coverage
before treating them as measurements for a model.

The relevant skill entrypoint links its validators and workflows. Useful read-only checks include:

```bash
python3 .codex/skills/cloneid-database-data/scripts/validate_core_inputs.py
python3 .codex/skills/ingest-lab-records/scripts/validate-instance-protocol-db.py --help
python3 .codex/skills/physicell-modeling/scripts/test_package.py
```

The last command checks bundled model/report primitives on synthetic inputs. It neither invokes PhysiCell nor submits jobs, and does not
validate a new dataset adapter or fitted biological model.
