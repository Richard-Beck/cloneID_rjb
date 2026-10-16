U01 calibration-progress draft, 13 October 2026

USER-NOTE: PLEASE KEEP THIS REPO ORGANIZED. I HAVE NEITHER READ NOR NECESSARILY APPROVE
THE CONTENTS OF THE README BELOW. I FOUND A LOT OF RANDOM STUFF IN THIS DIRECTORY AND SHIFTED
IT TO LOST AND FOUND. I WANT THE FOLLOWING:

latest - currently approved figure and accompnaying text.
revisions - when a new revision is in place move the incumbent latest to the revisions folder, and repopulate the latest folder.

CURRENT LATEST (2026-10-16): latest/preview.html and latest/baseline_multipanel.png
show the compact A--F figure rebuilt from the concluded October 16 lineage and
perspective pilots. SUM-159 hypoxia is the pilot for two reusable baseline definitions.

The figure measures 11.5 x 7.65 inches. Panel F retains all four acquisitions and
modalities in a 2x2 group layout, with labels inside the images. Quarter-field
windows are selected against each field's own full-field summaries. Full-field
fit statistics remain unchanged.

latest/ contains the PNG/PDF, rewritten calibration.md and matching caption.md,
preview.html, source notes, build_figure.py, crop_selection.py, config.json and
Git-ignored local provenance. Rebuild from the project root:
  conda run -n cpose python docs/u01_calibration_draft/latest/build_figure.py

The actual preceding latest was preserved intact in revisions/revision_08/.
The earlier local revisions, including revision_06 and revision_07, remain intact.
Revision archives and private local evidence are excluded from the Git checkpoint;
normal rebuilding does not require historical revision archives.
Older revisions and lost and found remain historical. Their source descriptions
and reproduction instructions do not describe the current figure.

The current perspective example uses its final frozen fitted trajectory and
matching native fields. The figure and source notes retain its 8.27-percentage-point
composition recheck shift and 127/128 probe support. Actual CPU accounting replaces
the older hypothetical PhysiCell-only projection. The broader grant source was not edited.
