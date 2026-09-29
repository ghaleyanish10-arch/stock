"""Lightweight schema migrations.

`Base.metadata.create_all` only creates missing tables; it never alters one.
That is fine for a greenfield app but leaves a trap for anyone who ran an
earlier build, so the few column-level changes we have made are recorded here
as idempotent steps applied after `create_all`.

Deliberately not Alembic: the schema is small, the changes are additive or
renames, and a dependency-free runner keeps `python -m app.main` working with
no extra install. If the schema ever needs data backfills or multi-step
dialect branching, this is the file to replace with a real migration tool.
"""

from __future__ import annotations

import logging

from sqlalchemy import Engine, inspect, text

logger = logging.getLogger(__name__)

#: Each entry is `(name, table, from_column, to_column)`. A step is skipped
#: when the table is absent or the old column is already gone, so running the
#: list repeatedly is safe.
_RENAME_STEPS: tuple[tuple[str, str, str, str], ...] = (
    # NEPSE's numeric security id was misspelled in the first schema.
    ("rename_securities_neopse_security_id", "securities", "neopse_security_id", "nepse_security_id"),
)

#: Each entry is `(name, table, column, ddl_type)`. A step is skipped when the
#: table is absent or the column already exists, so running repeatedly is safe.
_ADD_STEPS: tuple[tuple[str, str, str, str], ...] = (
    # Promoter/public shareholding, synced from nots/security/{id} during the
    # per-symbol enrich (VERIFIED 2026-09-28 for NABIL; see docs/data-sources.md).
    ("add_securities_promoter_shares", "securities", "promoter_shares", "FLOAT"),
    ("add_securities_public_shares", "securities", "public_shares", "FLOAT"),
    ("add_securities_promoter_pct", "securities", "promoter_pct", "FLOAT"),
    ("add_securities_public_pct", "securities", "public_pct", "FLOAT"),
    # Rights issues, from the same corporate-actions rows as bonus shares; the
    # adjustment factor for ADJUSTED candles needs it when present.
    ("add_corporate_actions_right_pct", "corporate_actions", "right_pct", "FLOAT"),
    # Fund metadata from NEPSE security detail enrich (Phase 3)
    ("add_funds_scheme_description", "funds", "scheme_description", "TEXT"),
    ("add_funds_scheme_name", "funds", "scheme_name", "VARCHAR(240)"),
    ("add_funds_close_ended", "funds", "close_ended", "BOOLEAN"),
    ("add_funds_maturity_date", "funds", "maturity_date", "VARCHAR(10)"),
    ("add_funds_face_value", "funds", "face_value", "FLOAT"),
    ("add_funds_units", "funds", "units", "INTEGER"),
    ("add_funds_fund_size", "funds", "fund_size", "FLOAT"),
    ("add_funds_listing_date", "funds", "listing_date", "VARCHAR(10)"),
    ("add_funds_isin", "funds", "isin", "VARCHAR(32)"),
)


def _columns(engine: Engine, table: str) -> set[str]:
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return set()
    return {col["name"] for col in inspector.get_columns(table)}


def apply_migrations(engine: Engine) -> list[str]:
    """Apply pending migrations. Returns the names of the steps that ran."""
    applied: list[str] = []
    for name, table, column, ddl in _ADD_STEPS:
        existing = _columns(engine, table)
        if not existing or column in existing:
            continue
        with engine.begin() as conn:
            conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl}'))
        logger.info("migration applied: %s (%s.%s added)", name, table, column)
        applied.append(name)
    for name, table, old, new in _RENAME_STEPS:
        existing = _columns(engine, table)
        if not existing:
            continue
        if old not in existing:
            if new not in existing:
                logger.warning("migration %s: neither %s nor %s found on %s", name, old, new, table)
            continue
        if new in existing:
            logger.warning(
                "migration %s: %s.%s and %s both exist; leaving the schema untouched",
                name,
                table,
                old,
                new,
            )
            continue

        # SQLite >= 3.25 supports RENAME COLUMN, and recreates the index that
        # was declared on the old name, so the `index=True` above still holds.
        with engine.begin() as conn:
            conn.execute(text(f'ALTER TABLE "{table}" RENAME COLUMN "{old}" TO "{new}"'))
        logger.info("migration applied: %s (%s.%s -> %s)", name, table, old, new)
        applied.append(name)
    return applied
