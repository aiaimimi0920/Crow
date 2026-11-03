"""Add listing queue indexes explicitly, never in application startup."""

from alembic import op

revision = "20261104_0014"
down_revision = "20260922_0013"
branch_labels = None
depends_on = None

INDEXES = {
    "ix_property_listing_status_auction_date": ["status", "auction_date"],
    "ix_property_listing_status_is_deleted": ["status", "is_deleted"],
}


def upgrade() -> None:
    context = op.get_context()
    if context.dialect.name == "postgresql":
        # PostgreSQL concurrent DDL cannot run inside a transaction. A failure
        # remains visible to the deployment instead of being swallowed at startup.
        with context.autocommit_block():
            for name, columns in INDEXES.items():
                op.create_index(
                    name,
                    "property_listing",
                    columns,
                    postgresql_concurrently=True,
                    if_not_exists=True,
                )
    else:
        for name, columns in INDEXES.items():
            op.create_index(name, "property_listing", columns, if_not_exists=True)


def downgrade() -> None:
    context = op.get_context()
    if context.dialect.name == "postgresql":
        with context.autocommit_block():
            for name in reversed(INDEXES):
                op.drop_index(
                    name, table_name="property_listing", postgresql_concurrently=True
                )
    else:
        for name in reversed(INDEXES):
            op.drop_index(name, table_name="property_listing")
