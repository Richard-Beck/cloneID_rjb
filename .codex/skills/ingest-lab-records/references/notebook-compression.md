# Notebook Compression

## Role

Compress exactly one supplied laboratory-notebook text. Preserve information before attempting interpretation or cross-notebook
normalization. The packet contains stable source spans from one HTML notebook; treat those spans as the complete task input and do not open
the source HTML, other notebooks, prior outputs, or unrelated skill resources.

Fidelity is more important than a particular compression ratio. Do not omit a unique fact merely because it is difficult to classify.

Protected information must occur in `compressed_text`. Repeating or claiming it in `source_accounting` does not count as retention.

## Compression-first workflow

### 1. Segment locally; do not normalize globally

Use the existing boundaries:

```text
notebook -> section -> experiment or activity -> dated entries
```

This segmentation requires little interpretation. It does not require deciding whether tokens such as `P1`, `P2`, `RevC`, `RevG`, `A3`,
`A3K`, or `8NS_8N` belong to a common identifier system. Retain such strings verbatim. Their relationships may become apparent only after
the compressed collection can be considered together.

### 2. Protect information classes

Retain the following automatically, regardless of whether its eventual importance is understood.

#### Dates and chronology

- Every date as written.
- Keep the complete date token: for example, do not shorten `8-31-2024` to `8-31` or rewrite it in another format.
- Date ranges and treatment durations.
- Event order.
- Planned versus actual timing.
- Interruptions, delays, repeats, and missing dates.

#### Identifiers and names

- Cell-line names.
- Population, clone, passage, and lineage labels.
- Media identifiers.
- Sample identifiers.
- Plate, well, flask, image, database, Sequel, stock, and storage identifiers.
- Drug and reagent names.
- Instrument and core-facility names.
- People associated with execution, transfer, or analysis.
- Locally relevant URLs, DOIs, and cited publications.
- Image and attachment filenames even when their contents cannot be interpreted from the extracted text.

Examples include:

```text
SNU-668_P1
SNU-668_P2
SNU-668_RevC
SNU-668_RevG
HGC-27_RevG2
DKMGS_S5_8N
MDA-MB-231_NLS_4N_A3_harvest_T
media 82
media 96
SUM-159_A3T2
X-232
```

The notebooks contain one-off lineage events, accidental mixtures, discarded samples, stock locations, passage labels, media transitions,
and renamed populations. Premature canonicalization is dangerous.

#### Quantitative information

- Cell numbers and densities.
- Volumes and concentrations.
- Dilution series and replicate numbers.
- Centrifugation speed and duration.
- Incubation periods and passage ratios.
- Storage quantities.
- Calculations when they define what was actually prepared.

Preserve every unique number-unit pair. An intermediate calculation may be factored only when its inputs, formula, and final quantity remain
available.

A dilution or dose series is a set of protected values. Do not replace its members with only a minimum, maximum, step count, or statement
such as `10-point curve`. Either list every supplied value locally or define the complete series once and refer to that definition. Repeat
the unit on each value (for example, `0 uM, 0.06 uM, 0.19 uM`) so the retained number-unit pairs remain explicit and mechanically auditable.

#### Relationships and state transitions

Preserve who or what was:

- seeded in;
- treated with;
- switched from or to;
- mixed with;
- thawed from;
- split or passaged into;
- fixed, frozen, lysed, stained, sorted, or discarded;
- derived from;
- provided to or received from; and
- renamed or entered into a database.

#### Validity and interpretation

Preserve:

- mistakes and deviations;
- contamination or accidental mixing;
- sample loss and incorrect seeding;
- poor staining or segmentation;
- inconclusive or excluded experiments;
- negative results and observations;
- hypotheses and proposed explanations; and
- decisions about repeats or follow-up work.

These are often more important than routine protocol details.

### 3. Factor repeated information

#### Factor definitions

Store a recurring definition once in its relevant scope. For example:

```text
M82 = RPMI, 11.111 mM glucose, 10% dialyzed FBS, P/S
M83 = 365 mL glucose-free RPMI + 135 mL regular RPMI
      + 50 mL dialyzed FBS + 5 mL P/S; final glucose 3 mM
M84 = 450 mL phosphate-free RPMI + 50 mL regular RPMI
      + 50 mL dialyzed FBS + 5 mL P/S; final phosphate 10%
```

Later entries may refer to `M82/M83/M84` once those definitions remain complete and unambiguous in the compressed notebook.

#### Collapse repeated routine actions

Retain every date while factoring identical routine actions:

```text
2023-10-01, 10-02, 10-03:
  routine = refresh assigned media 82-96; acquire and assess CLONEID images
```

Keep exceptions separate:

```text
2023-10-04:
  routine except HGC-27_C/RevC; both confluent and split.
```

#### Compact plate maps

Factor repeated dimensions without losing layout, conditions, replicates, malformed wells, exceptions, or duplicated wells:

```text
Gemcitabine: 0, 3.125, 6.25, 12.5, 25, 50, 100, 200, 400, 800 nM
Populations: SUM-159 2N, SUM-159 4N
Replicates: 4
Layout: 2N rows A-D; 4N rows E-H
```

#### Refer to copied boilerplate

Long vendor descriptions and published protocols may be reduced to a complete local definition plus a source reference:

```text
SYTOX Deep Red: Thermo Fisher S11381; stock 1 mM.
Working concentration in this experiment: 0.5 uM.
Copied vendor block accounted as VENDOR-S11381.
```

Do not remove locally used values, deviations, lot/catalog identifiers, URLs, or experiment-specific changes with the boilerplate.
Retain the exact URL or DOI, not a placeholder such as `vendor URL`, `Cayman URL`, or `published protocol`.

### 4. Use light local structure

A compressed local record may use:

```text
NB23.E1 | SNU-668/HGC-27 nutrient-deprivation evolution

Aim: Test glucose/phosphate deprivation effects on ploidy.

Entities:
SNU-668_C,G1,G2,P1,P2,RevC,RevG,RevG2
HGC-27_C,G1,G2,P1,P2,RevC,RevG,RevG2

Defs:
M82=...
M83=...

Events:
2023-08-10: Seed 5e5 SNU-668 and HGC-27 cells/T75 in 20 mL regular RPMI+10% FBS.
2023-08-11: Switch cultures to M82/M83/M84/M85; M85 contains 0.5 uM reversine.
2023-08-12: Wash out reversine after 30 h; replace with M82.

Observations:
Phosphate deprivation caused elongation, rapid media acidification, and poor CLONEID segmentation.

Deviations:
2023-08-30 hurricane closure: media change and analysis skipped.
2023-09-19 HGC-27_C accidentally mixed with HGC-27_RevC; mixed culture discarded; RevC restarted from A2 stock.

Outputs/status:
...
```

Use enough structure to remain intelligible without imposing a universal identifier ontology or experimental schema.

### 5. Make compression auditable

For every source span:

- Account for it exactly once in `source_accounting`.
- Map it either to compressed content or to an allowed factoring reason: `factored_definition`, `collapsed_routine`, `vendor_reference`,
  `duplicate`, or `empty_placeholder`.
- Cite retained source spans in the compressed text using their exact IDs where practical.

An accounting record may group at most 20 consecutive spans that share one genuinely local disposition and compressed location. Never use
one blanket record for a whole notebook or a long heterogeneous section. The ledger demonstrates source traversal; it is not evidence that a
fact was retained.

Before returning, verify:

- Every source span is accounted for exactly once.
- Every date is preserved as written.
- Every protected identifier is preserved verbatim.
- Every unique number-unit pair is preserved unless a reversible calculation was factored.
- Every exact URL, DOI, image filename, and attachment filename is preserved.
- Every member of every dilution or dose series is preserved, potentially through one complete factored definition.
- Every lineage or handoff statement is preserved.
- Every deviation, negative result, exclusion, and uncertainty is preserved.
- The notebook ID and source provenance remain visible.

## Output

Return one object matching the task-listed schema:

- `compressed_text`: the compressed notebook only;
- `source_accounting`: an audit ledger covering every input span exactly once; and
- `quality_notes`: uncertainties or source-quality problems that could affect fidelity.

The audit ledger is not part of the compressed representation and is evaluated separately. Keep it concise. Do not pad the compressed text to
improve apparent coverage, and do not sacrifice protected information to improve the compression ratio.

## Postflight acceptance

Run `scripts/evaluate-notebook-compression.py` after the workers finish. Treat span omissions, duplicate or unknown span accounting, an
accounting record covering more than 20 spans, or any missing exact protected token as an automated failure requiring review and normally a
targeted retry. Compression ratios are descriptive only and never override a fidelity failure. The lexical audit is deliberately conservative:
inspect its missing-token list to distinguish a worker omission from a matcher false positive, then record any reviewer waiver explicitly.
