# Crow project-local runtime data

`CrowData/` is the default management root for new installations. Existing
installations with runtime contents in `FPFData/` keep that exact directory.
No rename, copy, synchronization, database migration or service restart is
performed by the path resolver. See [the compatibility guide](../docs/runbooks/crow-data-root-compatibility.md).

Only this README and `.gitignore` are versioned. Everything else, including
secrets, browser profiles, cookies, database backups, live PostgreSQL data,
logs and generated artifacts, stays outside Git and Docker build contexts.
The legacy archive importer remains available and never mirrors deletions;
its name is a compatibility entry point, not a request to move existing data.
