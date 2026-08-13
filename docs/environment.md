# Environment and external tools

Most Python workflow code uses the standard library. `scripts/labarchives_dump.py` additionally requires `beautifulsoup4`.

R execution goes through `scripts/agentRrunner.sh`, which runs the configurable `CONTAINER_URI` with Apptainer. Core-data refresh requires the
R packages `DBI`, `RMariaDB`, and `digest`; joint-state growth models additionally require `TMB` and a working C++ toolchain.

Notebook compression and hypothesis execution require the Codex CLI. Their shell launchers also use `jq`, standard checksum/archive tools,
and SLURM commands including `sbatch`, `squeue`, and `sacct`. The reviewed hypothesis runner checks its command dependencies before launch.

Database credentials must remain outside the repository. The supported default is `~/.config/cloneid/db.env` with mode `600`, as documented
in the cloneID database refresh workflow.
