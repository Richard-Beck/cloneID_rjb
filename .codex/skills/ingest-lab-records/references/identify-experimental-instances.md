# Identify Experimental Instances

Use this workflow to find experiments that could test a hypothesis and to recover their design from available evidence. Do not assume that an
instance/protocol database exists.

## Desired result

Return one or more candidate instances with enough context to decide whether and how they can test the hypothesis:

- experimental aim and relevant contrast;
- biological material, arms, controls, interventions, and longitudinal structure;
- measurements or samples that are available or plausibly linked;
- identifiers that connect the instance to underlying data;
- important uncertainties and reasonable, clearly labelled assumptions.

An **instance** is one execution of an experimental plan with a shared objective and coordinated arms. It may cross dates, conditions, media,
lineages, or data files. Separate the experiment that generated or maintained cells from later experiments that sampled, characterized, or
assayed them.

## Workflow

1. Translate the hypothesis into design needs: relevant population, exposure or adaptation history, comparison, longitudinal scale, outcomes,
   and replication.
2. Search the evidence that is actually available. Sources may include user-provided facts, instance or protocol records, laboratory notebooks
   and summaries, cloneID lineage metadata, filenames, analysis notes, assay records, or other project documentation.
3. Reconstruct candidate instances progressively. Prefer evidence of shared aim, coordinated arms, named experiments, direct lineage
   continuity, planned condition changes, or explicit sampling relationships. Dates, medium, or cell line alone do not establish one instance.
4. Follow relevant upstream and downstream relationships. Ask both what generated or maintained the material and what later experiments
   sampled or measured it.
5. Report the best candidates and why they are useful. Distinguish recorded facts, reasonable working assumptions, and unresolved questions.

If `lab_records/instance_protocol_db/` is available, catalog or search it, then read only the relevant instance, protocol, and related-instance
records. Treat it as an index into evidence rather than the only possible source. Its absence is not an error: continue with other records and
state what could not be reconstructed.

Use compressed notebooks or canonical metadata for factual support when the claim exceeds what an instance summary establishes. Do not edit
the knowledge base during this workflow.
