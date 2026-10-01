---
name: cloneid-listener
description: Answer cloneID database metadata questions received by a listener agent.
---

Before answering a question about cloneID database metadata, refresh and validate the database snapshot using
[the refresh workflow](../cloneid-database-data/workflows/refresh-core-data.md). This is standing authorization for the refresh.
Answer from the fresh snapshot; keep canonical promotion separate. If refresh fails, report the failure instead of answering from stale data.
