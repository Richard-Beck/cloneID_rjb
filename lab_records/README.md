# Local laboratory-record knowledge base

`instance_protocol_db/` is the stable location for the live Markdown database of experimental instances, reusable protocols, source
snapshots, queue history, and turn notes. The database is durable local state but is intentionally excluded from Git because it is updated
independently of the repository source.

Use the `ingest-lab-records` skill for every update. Updates must be serial, resolved queue history must be preserved, and the database must
pass `validate-instance-protocol-db.py` after each bounded turn. Timestamped test directories may contain frozen copies for audit purposes,
but must not become competing live databases.

Do not remove evidence locations named in `instance_protocol_db/sources.md` merely because they live under an ignored generated-data path.
An older test-run database path may be retained as a compatibility symlink to the stable live database so existing bounded-update commands
continue to address the same state.
