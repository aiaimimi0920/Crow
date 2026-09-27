"""Compatibility entrypoint for existing tools and the legacy contract route.

Collection writers import the native owner; no assignment forwarding is used.
"""

from src.collection.record_schema import (
    build_collection_record,
    get_collection_template,
    get_empty_collection_record,
    sync_collection_record,
)

__all__ = [
    "build_collection_record",
    "get_collection_template",
    "get_empty_collection_record",
    "sync_collection_record",
]
