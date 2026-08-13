# Local cloneID core-data snapshot

The CSV files in this directory are local canonical inputs and are intentionally excluded from Git. Do not place credentials here.

Use the cloneID database skill's `workflows/refresh-core-data.md` workflow to download a staged snapshot under `tmp/core_data_refresh/`.
Review its manifest, schema, diffs, and validation report before separately promoting the accepted `passaging.csv`, `media.csv`,
`perspective.csv`, and `liquid_nitrogen.csv` files into this directory.

Derived graph and coherent-span products belong under the ignored `data/` directory and can be rebuilt from these local inputs.
