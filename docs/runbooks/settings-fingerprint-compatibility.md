# Settings request fingerprint compatibility proposal

This change is a draft adoption proposal. It does not migrate a running service
or the user's database. Review the rollback consequence before merging or
deploying it alongside other local changes.

## Adoption and rollback consequence

The previous binary understands only unversioned SHA-256 fingerprints. It
cannot accept an exact retry for a request stored in the new format. Do not
run old and new settings API writers against the same database. Returning to
the previous binary requires a separately reviewed rollback plan; copying an
old database over current state could lose revisions and replay protections.
This change does not perform a rollback or alter backups.

The HTTP request/response format, request IDs, command claims, revision checks,
single-flight behavior, key handoff and key erasure remain unchanged. Existing
agent binaries use those public contracts, not the stored fingerprint format.

## New requests and exact historical retries

New accepted requests store `pbkdf2-sha256-v1$600000$<salt>$<digest>`: a random
16-byte public salt and a 32-byte PBKDF2-HMAC-SHA256 result with a fixed 600,000
iteration count. The input is domain separated and binds the same canonical
settings plus optional API key as before. This raises the cost of guessing a
weak manually supplied key from a copied current record. It is not an
authentication token and creates no new persistent access credential.

Only the known format, exact work factor and fixed lowercase hexadecimal
lengths are accepted. Malformed or unknown versions fail closed before KDF
work. Comparisons use `hmac.compare_digest`.

An existing unversioned 64-character SHA-256 record remains verifiable using
the original payload. A matching retry upgrades only that row's fingerprint
inside the existing SQLite transaction. It does not change public response
fields, timestamps, revision, status or command ownership. A mismatching retry
cannot upgrade or rebind the row. The original handoff key does not have to
exist: the retry already supplies the original optional key. An erased key is
not recreated and a completed/claimed command is not replayed.

Status reads and controller polls do not scan or rehash old rows. There is no
active whole-database migration. Unretried old rows and historical database
copies retain the old weak-key guessing risk. Updating a logical SQLite row is
not physical secure erasure: the previous digest can remain in database pages,
journals, WAL files or backups. No runtime erasure or vacuum operation is added.
The compatibility SHA-256
verifier remains visible to CodeQL; this proposal does not claim zero alerts
or complete elimination of historical risk.

## Resource and verification boundary

Both settings transports authenticate the operator before accessing storage
or running a KDF. The main server authenticates before reading the body; the
TLS gateway parses its capped body before dispatch authorization. Both cap the
body at 16 KiB. The store validates closed settings fields and the API key's
maximum 2,048-character length. The fingerprint helper also bounds direct
inputs before encoding. Work factors cannot be chosen by the request or a
stored record. A new request rejected for stale/offline/single-flight state
does not run a KDF. KDF work for the same database is serialized by its existing
`BEGIN IMMEDIATE` transaction and ten-second SQLite timeout.

The service has no per-operator rate limiter for this route. An authorized
caller can still consume CPU and contend on the mailbox with repeated valid
requests; serialization is not a complete denial-of-service defense. Synthetic
measurements in the review environment were about 118–149 ms per KDF operation;
deployment hardware and load must be considered before adoption.

Offline tests cover fixed old/new vectors, malformed versions and cost fields,
all six historical request states, erased-key retries, concurrent migration,
wrong-key/config refusal and rollback after KDF or commit failure. They do not
use user databases or credentials.

Algorithm guidance: [CodeQL weak-sensitive-data-hashing](https://codeql.github.com/codeql-query-help/python/py-weak-sensitive-data-hashing/)
and [OWASP Password Storage: PBKDF2](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html#pbkdf2).
