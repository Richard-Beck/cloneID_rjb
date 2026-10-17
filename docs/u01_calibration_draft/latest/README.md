# Approved baseline figure

[Preview](preview.html) · [PNG](baseline_multipanel.png) · [PDF](baseline_multipanel.pdf) · [Text and legend](calibration.md)

This folder is self-contained. The bundled reporting data rebuild the approved SUM-159 pilot figure without pilot directories,
private provenance, raw imaging collections, database access, a simulator or a scheduler. The figure's models, results, layout,
representative 25% display windows and approved text are unchanged.

Use Python 3.10 and the pinned plotting environment for pixel-identical output:

```sh
python -m pip install -r docs/u01_calibration_draft/latest/requirements.txt
python docs/u01_calibration_draft/latest/build_figure.py
```

The folder can also be copied anywhere and rebuilt with `python build_figure.py`. Rebuilding checks bundle hashes, reconstructs
the full-support component losses and CPU estimates, recomputes the representative windows, and checks the PNG's pixels against
the approved image hash. PNG/PDF and the offline preview are regenerated; `.rebuild/` holds local numerical checks and is ignored
by Git. Other plotting-library versions may render different pixels even when the data agree.

[figure_data/manifest.json](figure_data/manifest.json) lists every bundled input, its hash and size, source campaign identities and
original evidence hashes. [DATA_BUNDLE.md](DATA_BUNDLE.md) describes the compact schema, provenance and projection assumptions.
These are reporting inputs, not initialization data for fresh fits. No fitting or simulation code is imported or run.

A shows the lineage and oxygen history. B pools 220 chromosome measurements. C compares measured CPU use with a hypothetical
PhysiCell-only inference budget. D shows living 4N fractions for hypoxia 1 and hypoxia 2. E illustrates the six weighted cost
components using the Lineage-guided example linked to F2. F retains all four acquisitions in a compact 2x2 arrangement, with
brightfield, segmentation and both model fields. The gold frames identify the observed/segmented field and Lineage-guided field
used by E. Complete-field statistics remain complete-field; the displayed windows do not define fitted scores.
