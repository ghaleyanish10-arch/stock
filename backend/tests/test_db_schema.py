"""Schema integrity tests.

Guards the invariants that are easy to break by hand and expensive to
discover in production. The `DailyBar` composite key is the motivating
example: when `symbol` accidentally lost `primary_key=True`, the primary key
silently became `business_date` alone and the archive overwrote each session
with a single symbol - losing ~440 rows per day with no error raised.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect

from app.db.base import Base
from app.db.models import (
    Broker,
    DailyBar,
    Fund,
    Security,
    TradingDay,
    User,
)

TABLES = set(Base.metadata.tables)


class TestPrimaryKeys:
    def test_every_table_has_a_primary_key(self):
        missing = [
            name
            for name, table in Base.metadata.tables.items()
            if not table.primary_key.columns
        ]
        assert missing == []

    @pytest.mark.parametrize(
        ("table", "expected"),
        [
            (TradingDay, ["business_date"]),
            (DailyBar, ["business_date", "symbol"]),
            (Security, ["symbol"]),
            (Broker, ["member_code"]),
            (Fund, ["code"]),
            (User, ["id"]),
        ],
    )
    def test_expected_primary_keys(self, table, expected):
        assert [c.name for c in table.__table__.primary_key.columns] == expected

    def test_daily_bar_composite_key(self):
        """Regression guard: the archive's most damaging possible bug."""
        pk = [c.name for c in DailyBar.__table__.primary_key.columns]
        assert pk == ["business_date", "symbol"], (
            "DailyBar must be keyed by (business_date, symbol); otherwise a "
            "re-run collapses an entire session into one symbol."
        )


class TestNullableColumns:
    """Market values must default to NULL, never 0."""

    #: Provenance bookkeeping, which legitimately carries defaults.
    META_COLUMNS = {"business_date", "symbol", "source", "updated_at"}

    def test_daily_bar_value_columns_are_nullable(self):
        for column in DailyBar.__table__.columns:
            if column.name in self.META_COLUMNS:
                continue
            assert column.nullable, f"{column.name} must be nullable (None, not 0)"

    def test_daily_bar_values_have_no_defaults(self):
        """A market value must never be silently defaulted - not to 0, not at all."""
        for column in DailyBar.__table__.columns:
            if column.name in self.META_COLUMNS:
                continue
            assert column.default is None, f"{column.name} must not have a default"

    def test_fund_nav_is_nullable_with_explicit_status(self):
        # NAV NULL plus an explicit status column is how "NEPSE does not
        # publish NAV" is represented, instead of a 0 or a bare dash.
        assert Fund.__table__.c.nav.nullable is True
        assert Fund.__table__.c.nav_status.nullable is False

    def test_security_listed_shares_nullable(self):
        assert Security.__table__.c.listed_shares.nullable is True


class TestIndexes:
    def test_archive_lookup_indexes_exist(self):
        indexes = {ix.name for ix in DailyBar.__table__.indexes}
        assert "ix_daily_bars_symbol_date" in indexes
        assert "ix_daily_bars_date_symbol" in indexes

    def test_symbol_lookup_index(self):
        indexes = {ix.name for ix in Security.__table__.indexes}
        assert any("nepse_security_id" in name for name in indexes)


class TestSqliteRoundTrip:
    def test_create_all_produces_every_table(self):
        from sqlalchemy import create_engine

        engine = create_engine("sqlite://", future=True)
        Base.metadata.create_all(bind=engine)
        created = set(inspect(engine).get_table_names())
        engine.dispose()
        assert TABLES <= created

    def test_portable_types_only(self):
        """No SQLite-only column types, so Postgres stays a config change."""
        for table in Base.metadata.tables.values():
            for column in table.columns:
                type_name = type(column.type).__name__.upper()
                assert "JSONB" not in type_name
                assert "SQLITE" not in type_name
                assert type_name != "VARCHAR" or column.type.length

    def test_enum_columns_render_as_varchar(self):
        """native_enum=False, so the DDL is identical on SQLite and Postgres."""
        from app.db.models import Transaction

        for column in Transaction.__table__.columns:
            if column.name == "side":
                assert type(column.type).__name__ == "Enum"
                assert column.type.native_enum is False
