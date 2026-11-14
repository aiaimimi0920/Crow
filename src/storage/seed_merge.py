"""Seed enrichment never replaces detail evidence from a newer committed row."""

from copy import deepcopy

from .models import (
    PropertyAudit,
    PropertyLegalContext,
    PropertyListing,
    PropertyRiskFlags,
)


def locked_listing(session, item_id):
    connection = session.connection()
    if connection.dialect.name == "sqlite":
        # sqlite3 legacy transaction mode does not begin a transaction on SELECT.
        # Reserve the writer before reading the merge base, not after it is stale.
        raw = connection.connection.driver_connection
        if not raw.in_transaction:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
    return session.get(
        PropertyListing, item_id, with_for_update=True, populate_existing=True
    )


def fill_missing(current, incoming):
    result = deepcopy(current)
    for key, value in incoming.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = fill_missing(existing, value)
        elif existing in (None, "", []) and value not in (None, "", []):
            result[key] = deepcopy(value)
    return result


def merge_seed(repository, session, listing, incoming):
    current = repository._listing_payload_from_rows(
        listing,
        session.get(PropertyRiskFlags, listing.item_id),
        session.get(PropertyLegalContext, listing.item_id),
        session.get(PropertyAudit, listing.item_id),
    )
    return fill_missing(current, incoming)
