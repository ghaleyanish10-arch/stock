"""Application-level NEPSE exceptions.

The rest of the application only ever sees these - never the exceptions
raised by the `nepse-api` wrapper itself.
"""

from __future__ import annotations


class NepseServiceError(Exception):
    """Base class for all NEPSE service errors."""

    code = "NEPSE_API_ERROR"
    message = "Unable to retrieve NEPSE data"


class NepseUnavailableError(NepseServiceError):
    """NEPSE (or its API) could not be reached / is down."""

    code = "NEPSE_UNAVAILABLE"
    message = "NEPSE service is currently unavailable"


class NepseTimeoutError(NepseServiceError):
    """NEPSE did not answer within the configured timeout."""

    code = "NEPSE_TIMEOUT"
    message = "NEPSE request timed out"


class NepseInvalidResponseError(NepseServiceError):
    """NEPSE answered, but with something we cannot use."""

    code = "NEPSE_INVALID_RESPONSE"
    message = "NEPSE returned an unexpected response"


class NepseAuthError(NepseServiceError):
    """NEPSE rejected our authentication token, even after a forced
    re-authentication and retry. Usually a transient flap of NEPSE's WASM
    token service; persistent occurrences may mean the salt scheme changed."""

    code = "NEPSE_AUTH_FAILED"
    message = "NEPSE rejected our authentication token (re-authentication was attempted)"


class NepseRateLimitedError(NepseServiceError):
    """NEPSE answered HTTP 429: too many requests. Backoff and retry."""

    code = "NEPSE_RATE_LIMITED"
    message = "NEPSE is rate-limiting requests; retry shortly"


class SymbolNotFoundError(NepseServiceError):
    """The requested stock symbol does not exist."""

    code = "NEPSE_SYMBOL_NOT_FOUND"
    message = "Stock symbol not found"


class DataNotFoundError(NepseServiceError):
    """No data exists for the requested date/period."""

    code = "NEPSE_DATA_NOT_FOUND"
    message = "No NEPSE data found for the requested date"


class NepseDateOutOfRangeError(NepseServiceError):
    """The requested business date is older than NEPSE's served history.

    NEPSE answers HTTP 500 with the body "Searched Date is not valid." for any
    date outside its ~227-session window. This is *permanent*, not transient:
    retrying the same date will never succeed, and the archive uses it to
    discover the earliest date it can obtain rather than treating the request
    as a failure.

    Observed 2026-09-28: 2025-12-01 returns 325 rows, 2025-08-24 raises this.
    """

    code = "NEPSE_DATE_OUT_OF_RANGE"
    message = "The requested date is outside the range NEPSE publishes"


class NepseAuthRequiredError(NepseServiceError):
    """The endpoint requires NEPSE's WASM token but it was not accepted."""

    code = "NEPSE_AUTH_REQUIRED"
    message = "NEPSE requires an authenticated session for this endpoint"

