# Collection publication recovery

Seed updates enrich existing fields rather than overwrite committed detail evidence.
The seed publisher commits to the database and reads back its canonical record before
publishing the JSON snapshot. JSON-only merging uses the same recursive fill-missing
rules, including empty lists. A seed event is not a detail replacement event.

Cooperating seed and detail publishers hold the archive transaction lock across both
stores. Detail publication preserves the existing JSON-first failure contract. Before
writing detail JSON it creates a per-item `.pending-db-<item hash>` marker. If JSON or
the database operation fails, the marker remains. Seed publication for that item then
fails closed, preserving the possibly newer JSON evidence instead of replacing it
with an older database snapshot. A successful retry of the detail operation removes
the marker. Marker write/removal failures are failures, not successful completion.

## Recovery

- Keep the capture, archive, marker, and failure receipt. Do not delete the marker to
  unblock seed ingestion, and do not blindly replay an unknown database operation.
- For captured-detail failures, repair the storage failure and retry the retained
  capture through the normal detail processor. A pending rejected/failed JSON record
  is not treated as a completed terminal state by that retry.
- For manual patch or HTML-status submission failures, resubmit the original intended
  operation after repairing storage. These paths do not promise automatic recovery.
- Verify the database and archive result, marker removal, and only then successful
  seed ingestion. Other items have separate markers.

## Limits

This is not an atomic distributed transaction. During recovery the two stores can
still differ. The marker protects evidence and blocks acknowledgement of unsafe seed
publication; it is not a transaction log containing the complete operation.

The lock covers cooperating writers using the same local archive path. Database-only
writers, different archive paths for one item, older binaries, and network filesystem
lock semantics are outside that guarantee. Stop old writers before activating this
change. Normal process-crash recovery is covered; power-loss durability of directory
entries is not guaranteed. No production deployment is implied by these tests.
