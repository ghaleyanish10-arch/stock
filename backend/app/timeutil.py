"""Nepal time and calendar helpers (WP1).

Everything in this module is **pure** — no database, no clock, no I/O — so the
calendar logic can be unit tested with hand-computed expectations. The
database-backed helpers (`is_trading_day` and friends) take a session object,
which makes the holiday source injectable in tests.

Conventions (project rule 11):

* Nepal is UTC+05:45, no daylight saving — a fixed offset is exact.
* NEPSE trades **Sunday to Thursday**, roughly 11:00–15:00 NPT.
* The holiday set is data, not code: `trading_days` table rows with
  `is_session=False` and the admin-editable `holidays` table both count as
  non-trading days.
* Nothing here invents a holiday. Absent evidence a date is a trading day.

Bikram Sambat conversion wraps `nepali_datetime` (MIT) rather than embedding a
table: the library's coverage (1913–2044 AD) exceeds any need, its round trips
are verified over decades in the tests, and the official anchor pair
BS 2082-01-01 = AD 2025-04-14 is asserted there too. The BS calendar itself is
an unverified-in-part source (some historical year tables differ between
sources), so conversions outside the tested range raise rather than guess.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# NPT (Nepal Time)
# ---------------------------------------------------------------------------

#: Nepal is UTC+05:45 with no daylight saving, so a fixed offset is exact and
#: avoids a tzdata dependency. (Same definition as app.jobs.scheduler, kept
#: here so feature code does not import the scheduler.)
NPT = timezone(timedelta(hours=5, minutes=45))

#: NEPSE session window in NPT (approximate; published schedule says 11:00
#: start, 15:00 close on regular days).
SESSION_START = time(11, 0)
SESSION_END = time(15, 0)


def nepal_now() -> datetime:
    """Current wall-clock time in Nepal, regardless of the server timezone."""
    return datetime.now(NPT)


def to_nepal(value: datetime) -> datetime:
    """Convert a stored timestamp to Nepal time.

    The DB stores naive UTC (see `app.db.base.utcnow`); attaching the UTC
    explicitly first avoids Python assuming the server's local timezone.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).astimezone(NPT)
    return value.astimezone(NPT)


def npt_date(value: Optional[datetime] = None) -> date:
    """The current (or given) instant's calendar date **in Nepal**."""
    return (value if value is not None else nepal_now()).date()


# ---------------------------------------------------------------------------
# Trading calendar (weekend pattern + injected holiday set)
# ---------------------------------------------------------------------------

#: NEPSE trading days: Sunday(6) to Thursday(4) in Python's weekday numbering
#: (Monday=0 ... Sunday=6).
TRADING_WEEKDAYS = frozenset({6, 0, 1, 2, 3})


def is_weekend_trading_pattern(d: date) -> bool:
    """True when the date falls on the Nepali weekend (Friday/Saturday)."""
    return d.weekday() not in TRADING_WEEKDAYS


def is_trading_day(
    d: date,
    *,
    session: object = None,
    holidays: Iterable[str] | Iterable[date] = (),
) -> bool:
    """True when `d` is a NEPSE trading day.

    Two independent holiday sources, either of which may be supplied (or both):

    * `session` — a SQLAlchemy session; consults the admin-editable
      `holidays` table and the archive's `trading_days` table
      (`is_session=False` rows are confirmed non-sessions).
    * `holidays` — an explicit iterable of ISO strings or dates, for pure
      tests and callers that already hold the holiday set.

    A date is a trading day when it is not a Friday/Saturday and neither
    source marks it a holiday. No source ⇒ pattern-only answer.
    """
    if is_weekend_trading_pattern(d):
        return False
    iso = d.isoformat()
    for h in holidays:
        if (h.isoformat() if isinstance(h, date) else str(h)) == iso:
            return False
    if session is not None:
        if _session_holiday(session, d):
            return False
    return True


def _session_holiday(session: object, d: date) -> bool:
    """Consult the DB-backed tables. Imported lazily to keep import cost low
    and to avoid a models import cycle in tooling that only wants the pure
    helpers."""
    from sqlalchemy import select

    from app.db.models import Holiday, TradingDay

    iso = d.isoformat()
    # Admin table first: explicit and editable.
    row = session.get(Holiday, iso)
    if row is not None:
        return True
    # Archive's confirmed non-sessions (NEPSE-declared holidays/weekends).
    td = session.execute(
        select(TradingDay).where(TradingDay.business_date == iso)
    ).scalar_one_or_none()
    if td is not None and td.is_session is False:
        return True
    return False


def next_trading_day(
    d: date,
    *,
    session: object = None,
    holidays: Iterable[str] | Iterable[date] = (),
) -> date:
    """The first trading day strictly after `d`."""
    cur = d + timedelta(days=1)
    # A holiday burst can never exceed 7 consecutive days in practice, but the
    # loop is bounded for safety (a full year of non-days means broken data).
    for _ in range(366):
        if is_trading_day(cur, session=session, holidays=holidays):
            return cur
        cur += timedelta(days=1)
    raise ValueError(f"no trading day found within a year after {d}")


def previous_trading_day(
    d: date,
    *,
    session: object = None,
    holidays: Iterable[str] | Iterable[date] = (),
) -> date:
    """The last trading day strictly before `d`."""
    cur = d - timedelta(days=1)
    for _ in range(366):
        if is_trading_day(cur, session=session, holidays=holidays):
            return cur
        cur -= timedelta(days=1)
    raise ValueError(f"no trading day found within a year before {d}")


def trading_days_between(
    start: date,
    end: date,
    *,
    session: object = None,
    holidays: Iterable[str] | Iterable[date] = (),
) -> int:
    """Count trading days in the inclusive range [start, end].

    Returns 0 when start > end (an empty range, not an error — callers use
    this for "how many sessions were open", which is legitimately zero).
    """
    if start > end:
        return 0
    count = 0
    cur = start
    while cur <= end:
        if is_trading_day(cur, session=session, holidays=holidays):
            count += 1
        cur += timedelta(days=1)
    return count


def last_day_to_buy(
    book_close: date,
    settlement_days: int,
    *,
    session: object = None,
    holidays: Iterable[str] | Iterable[date] = (),
) -> date:
    """Last date on which a buy still settles before the book-close date.

    This is the WP4 helper, placed here because it is pure calendar logic:
    walk back `settlement_days` trading days from (book_close - 1 day).

    Hand example (the WP4 test asserts this): book close on Thursday
    2026-10-08, N=2 settlement days → walk back Thu→Wed→**Tuesday 2026-10-06**.

    `settlement_days` is an unverified config value (see UNVERIFIED list);
    callers must surface that to the user.
    """
    if settlement_days < 0:
        raise ValueError("settlement_days must be >= 0")
    # Start from the book-close date itself when it is a trading day; when it
    # is not (e.g. a Sunday book close), the nearest trading day strictly
    # before it is the effective deadline anchor — a non-trading day can never
    # be a "last day to buy".
    cur = (
        book_close
        if is_trading_day(book_close, session=session, holidays=holidays)
        else previous_trading_day(book_close, session=session, holidays=holidays)
    )
    for _ in range(settlement_days):
        cur = previous_trading_day(cur, session=session, holidays=holidays)
    return cur


# ---------------------------------------------------------------------------
# Bikram Sambat conversion
# ---------------------------------------------------------------------------

def ad_to_bs(d: date) -> tuple[int, int, int]:
    """AD date → (bs_year, bs_month, bs_day).

    Raises `BikramSambatError` outside the library's verified table range;
    callers should surface that as a provenance problem, not a crash.
    """
    import nepali_datetime

    bs = nepali_datetime.date.from_datetime_date(d)
    return bs.year, bs.month, bs.day


def bs_to_ad(year: int, month: int, day: int) -> date:
    """(bs_year, bs_month, bs_day) → AD date.

    Raises on impossible BS dates (e.g. day 33) — that is the honest answer
    for a date that does not exist.
    """
    import nepali_datetime

    return nepali_datetime.date(year, month, day).to_datetime_date()


def bs_month_length(year: int, month: int) -> int:
    """Days in a BS month (Baisakh 1 etc. differ year to year; 29–32 days)."""
    if month == 12:
        nxt = bs_to_ad(year + 1, 1, 1)
    else:
        nxt = bs_to_ad(year, month + 1, 1)
    return (nxt - bs_to_ad(year, month, 1)).days


def format_bs(d: date) -> str:
    """Render an AD date as `YYYY-MM-DD (BS 2082-11-15)` for UI display.

    Used beside AD dates in the calendar, tables, tooltips and alerts (WP9
    consumes this). Raises BikramSambatError outside the supported range —
    the caller decides how to present that.
    """
    y, m, day = ad_to_bs(d)
    return f"{d.isoformat()} (BS {y:04d}-{m:02d}-{day:02d})"


# ---------------------------------------------------------------------------
# Fiscal year (Shrawan start)
# ---------------------------------------------------------------------------

def fiscal_year_start(ad_today: date) -> date:
    """First day of the Nepali fiscal year containing `ad_today`.

    The Nepali fiscal year starts at Shrawan 1 (BS), which lands in mid-July
    AD. Computed via the BS calendar rather than a hardcoded AD date, so it
    stays correct across years.

    Quarter boundaries within the year (Shrawan/Ashwin/Kartik... ends) are
    **config, unverified** — see UNVERIFIED list; this function only returns
    the year start, which is the part with a single well-known convention.
    """
    y, _, _ = ad_to_bs(ad_today)
    start = bs_to_ad(y, 4, 1)  # Shrawan is BS month 4
    # If Shrawan 1 of this BS year is after `ad_today`... it cannot be:
    # ad_today maps into BS year y, and Shrawan 1 is early in BS year y
    # (months 1-3 are the last fiscal year's tail). So for dates in
    # Baisakh-Ashadh (BS months 1-3) of BS year y, the fiscal year began in
    # BS year y-1.
    if start > ad_today:
        start = bs_to_ad(y - 1, 4, 1)
    return start


def fiscal_year_label(ad_today: date) -> str:
    """`FY 2083/84`-style label for the fiscal year containing `ad_today`."""
    y, _, _ = ad_to_bs(ad_today)
    start = fiscal_year_start(ad_today)
    start_year, _, _ = ad_to_bs(start)
    return f"FY {start_year}/{(start_year + 1) % 100:02d}"
