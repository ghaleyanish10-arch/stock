"""Value provenance: the contract that keeps "missing" and "zero" apart.

This is the backbone of the whole application. NEPSE routinely reports `0` for
things that mean "none declared this year" (a 0% bonus share), and routinely
reports nothing at all for things nobody has published yet (a mutual fund's
NAV). Rendering both as `0` or `N/A` is how a market dashboard starts lying.

So every number that reaches the UI is wrapped in a `Measured`, which carries
*why* it looks the way it does:

    Measured.of(10.8)   -> value 10.8,  status ok
    Measured.of(0.0)    -> value 0.0,   status declared_zero   (NOT "no data")
    Measured.missing()  -> value None,   status not_reported
    Measured.not_published("NAV")  -> value None, status not_published

`status` drives the wording the frontend shows ("Not declared yet", "Not paid",
"Data unavailable") and the tooltip that explains the reason and the as-of
time. Rules:

* `None` never becomes `0`, `""` or `"N/A"`.
* A `0` is always labelled as a declared zero, never hidden.
* Every value can explain itself: source, as-of timestamp, and a note.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ValueStatus(str, Enum):
    """Why a value looks the way it does."""

    #: A real measurement taken from a source.
    OK = "ok"
    #: The source explicitly reported zero ("0.00% bonus share"). Real, not missing.
    DECLARED_ZERO = "declared_zero"
    #: The source has this field but left it empty for this entity.
    NOT_REPORTED = "not_reported"
    #: The source does not carry this field at all (e.g. NEPSE publishes no NAV).
    NOT_PUBLISHED = "not_published"
    #: The source carries the field but the fetch failed. Retryable.
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    #: Meaningless in this context (e.g. 52-week high before listing).
    NOT_APPLICABLE = "not_applicable"
    #: Expected but not yet announced (e.g. a dividend for a year still open).
    PENDING = "pending"


#: Short, human wording per status. The frontend uses these instead of
#: inventing its own, so the same reason always reads the same way.
STATUS_LABEL: dict[ValueStatus, str] = {
    ValueStatus.OK: "",
    ValueStatus.DECLARED_ZERO: "Declared as zero",
    ValueStatus.NOT_REPORTED: "Not declared yet",
    ValueStatus.NOT_PUBLISHED: "Not published by source",
    ValueStatus.UPSTREAM_UNAVAILABLE: "Data unavailable",
    ValueStatus.NOT_APPLICABLE: "Not applicable",
    ValueStatus.PENDING: "Not declared yet",
}

#: Longer explanation, shown as the tooltip / help text.
STATUS_EXPLANATION: dict[ValueStatus, str] = {
    ValueStatus.OK: "",
    ValueStatus.DECLARED_ZERO: (
        "The source reported an explicit zero. This is a real declared value, "
        "not missing data."
    ),
    ValueStatus.NOT_REPORTED: (
        "The source has this field but has not filled it in for this entity."
    ),
    ValueStatus.NOT_PUBLISHED: (
        "The source does not publish this field at all, so it cannot be known."
    ),
    ValueStatus.UPSTREAM_UNAVAILABLE: (
        "The upstream source could not be reached. This is usually temporary."
    ),
    ValueStatus.NOT_APPLICABLE: "The value does not apply to this entity.",
    ValueStatus.PENDING: "This has not been announced yet.",
}


def _is_zero(value: Any) -> bool:
    """True for a real numeric zero (not None, not False, not an empty string)."""
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value == 0
    if isinstance(value, str):
        return value.strip() in ("0", "0.0", "0.00")
    return False


class Measured(BaseModel, Generic[T]):
    """A value plus everything needed to judge how much to trust it."""

    value: Optional[T] = None
    status: ValueStatus = ValueStatus.NOT_REPORTED
    #: When the underlying fact was true (not when we fetched it).
    as_of: Optional[str] = None
    #: Which endpoint/file the value came from, e.g. "nepse:today-price".
    source: Optional[str] = None
    #: Extra context, e.g. "NEPSE does not publish mutual fund NAV".
    note: Optional[str] = None

    @property
    def is_missing(self) -> bool:
        return self.value is None

    @property
    def label(self) -> str:
        """Wording for the UI when the value cannot be shown as a number."""
        return STATUS_LABEL.get(self.status, "")

    def explain(self) -> str:
        """One-line explanation combining reason, as-of and note."""
        parts: list[str] = []
        expl = STATUS_EXPLANATION.get(self.status, "")
        if expl:
            parts.append(expl)
        if self.note:
            parts.append(self.note)
        if self.as_of:
            parts.append(f"Source timestamp: {self.as_of}.")
        if self.source:
            parts.append(f"Via {self.source}.")
        return " ".join(parts) if parts else ""

    # -- constructors ---------------------------------------------------

    @classmethod
    def of(
        cls,
        value: Optional[T],
        *,
        source: Optional[str] = None,
        as_of: Optional[Any] = None,
        note: Optional[str] = None,
    ) -> "Measured[T]":
        """Wrap a real value. `None` becomes not_reported; `0` becomes
        declared_zero so it is never mistaken for missing data."""
        if value is None:
            return cls.missing(source=source, as_of=as_of, note=note)
        status = ValueStatus.DECLARED_ZERO if _is_zero(value) else ValueStatus.OK
        return cls(value=value, status=status, source=source, as_of=_stamp(as_of), note=note)

    @classmethod
    def missing(
        cls,
        *,
        source: Optional[str] = None,
        as_of: Optional[Any] = None,
        note: Optional[str] = None,
    ) -> "Measured[T]":
        return cls(
            value=None,
            status=ValueStatus.NOT_REPORTED,
            source=source,
            as_of=_stamp(as_of),
            note=note,
        )

    @classmethod
    def not_published(
        cls,
        what: str,
        *,
        source: Optional[str] = None,
        note: Optional[str] = None,
    ) -> "Measured[T]":
        """The source has no such field. Permanent, not a transient failure."""
        full_note = f"{what} is not published by the source." if not note else note
        return cls(value=None, status=ValueStatus.NOT_PUBLISHED, source=source, note=full_note)

    @classmethod
    def unavailable(
        cls,
        *,
        source: Optional[str] = None,
        as_of: Optional[Any] = None,
        note: Optional[str] = None,
    ) -> "Measured[T]":
        return cls(
            value=None,
            status=ValueStatus.UPSTREAM_UNAVAILABLE,
            source=source,
            as_of=_stamp(as_of),
            note=note,
        )

    @classmethod
    def not_applicable(
        cls, *, source: Optional[str] = None, note: Optional[str] = None
    ) -> "Measured[T]":
        return cls(value=None, status=ValueStatus.NOT_APPLICABLE, source=source, note=note)

    @classmethod
    def pending(
        cls, *, source: Optional[str] = None, as_of: Optional[Any] = None, note: Optional[str] = None
    ) -> "Measured[T]":
        return cls(value=None, status=ValueStatus.PENDING, source=source, as_of=_stamp(as_of), note=note)


def _stamp(value: Optional[Any]) -> Optional[str]:
    """Normalize dates/datetimes to an ISO string; pass strings through."""
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def zero_is_meaningful(value: Any) -> bool:
    """Public helper mirroring `Measured.of`'s zero handling (used by tests)."""
    return _is_zero(value)


#: Fields NEPSE simply does not publish, with the reason shown in the UI.
#: Centralised so every screen says the same thing instead of each one
#: inventing its own wording.
NOT_PUBLISHED_BY_NEPSE: dict[str, str] = {
    "fund_nav": "Mutual fund NAV is not published by NEPSE; it is declared by the fund manager.",
    "nav_date": "Mutual fund NAV dates come from the fund manager, not NEPSE.",
    "eps": "EPS is not published in the NEPSE market feed; it comes from company financial statements.",
    "net_profit": "Net profit is not published in the NEPSE market feed.",
    "quarterly_statements": "NEPSE publishes market statistics, not company financial statements.",
    "broker_attribution": (
        "NEPSE's floorsheet payload carries buyer/seller broker fields but leaves them null, "
        "and its broker filter is not honoured, so per-broker flow cannot be derived."
    ),
    "intraday_candles": "NEPSE publishes session snapshots and market depth, not intraday candles.",
    "intraday_ticks": "NEPSE publishes session snapshots, not tick data.",
    "intraday_ohlcv_history_5y": (
        "NEPSE's per-security history covers roughly one year; longer ranges are "
        "built up by this app's own daily archive."
    ),
    "fund_holdings": "Mutual fund portfolio holdings are not published in the NEPSE feed.",
    "promoter_public_split": (
        "Promoter/public shareholding comes from NEPSE's per-security detail "
        "(nots/security/{id}: promoterShares, publicShares, promoterPercentage, "
        "publicPercentage). Verified 2026-09-28 for NABIL: promoterShares=158121099, "
        "publicShares=112448885, promoterPercentage=58.44, publicPercentage=41.56 "
        "(sums match stockListedShares). A symbol not yet enriched carries this note; "
        "once enriched, the split is available."
    ),
    "company_news": (
        "Company news and notices come from NEPSE's application/company-news/{id} "
        "endpoint (verified 2026-09-28: 39 items for NABIL). An empty list means "
        "NEPSE has published nothing for this symbol, not that news is unavailable."
    ),
    "book_value_per_share": (
        "Book value per share is not published in the NEPSE market feed; it comes "
        "from the company's financial statements."
    ),
    "market_depth": (
        "NEPSE's market depth lives at nots/nepse-data/marketdepth/{id}. During "
        "trading hours it returns the live order book; outside the session it "
        "answers HTTP 200 with an empty body (verified 2026-09-28 for NABIL). "
        "An empty payload means 'no live order book right now', not that the "
        "endpoint is unavailable or the data is structurally missing."
    ),
    "corporate_actions_complete": (
        "NEPSE publishes only the corporate actions it has recorded. Absence of a "
        "row means no action is recorded, not that none occurred."
    ),
}
