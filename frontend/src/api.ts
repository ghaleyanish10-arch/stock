/* HTTP clients.
 *
 * Two response conventions coexist, so there are two request helpers:
 *
 *   envelope() - the legacy `/api/nepse/*` endpoints return
 *                `{success, data, error}` and signal failure in-band.
 *   plain()    - the Phase 1 endpoints return plain JSON and signal failure
 *                with an HTTP status plus FastAPI's `{"detail": ...}`.
 *
 * Both raise `ApiError`, so callers never have to branch on which family an
 * endpoint belongs to.
 */

import type {
  ApiEnvelope,
  AsOfResult,
  BackfillRunRow,
  BarsResponse,
  BrokerRow,
  BrokersResponse,
  ChartResponse,
  CompanyResponse,
  Coverage,
  DividendsResponse,
  EnrichResult,
  FundDetailResponse,
  FundsResponse,
  HeatmapResponse,
  IndicatorsResponse,
  IndexHistory,
  IndexSummary,
  MarketOverview,
  Measured,
  MoverRow,
  RunsResponse,
  ScreenerResponse,
  SectorRow,
  SecuritiesResponse,
  SessionsResponse,
  SizeMetric,
  Stock,
  StockListResponse,
  TokenResponse,
  User,
  VisualisationPeriods,
  PeriodKey,
  // Phase 4
  Portfolio,
  PortfoliosResponse,
  Transaction,
  TransactionsResponse,
  HoldingsResponse,
  ValuationResponse,
  XIRRResponse,
  Watchlist,
  WatchlistsResponse,
  WatchlistItem,
  WatchlistItemsResponse,
  AlertChannel,
  AlertChannelsResponse,
  AlertRule,
  AlertRulesResponse,
  AlertEventsResponse,
  BuySellResult,
  BonusRightResult,
  WACCResult,
  BreakEvenResult,
  DividendYieldResult,
  XIRRResult,
  BonusRightAdjustedPrice,
  NewsItem,
  NewsResponse,
  NewsSearchResponse,
  QuarterlyResponse,
  QuarterlyPeriodsResponse,
  // Phase 5
  AIStatus,
  AskRequest,
  AskResponse,
} from "./types";

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status = 0) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }

  /** True for failures worth retrying (network blips, upstream trouble). */
  get transient(): boolean {
    return this.status === 0 || this.status >= 500 || this.code === "NEPSE_UNAVAILABLE";
  }
}

/* -- auth token store ----------------------------------------------------- */

const TOKEN_KEY = "sa.access_token";

let accessToken: string | null = readStoredToken();
const tokenListeners = new Set<(token: string | null) => void>();

function readStoredToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    // Private browsing or a blocked storage partition: run unauthenticated.
    return null;
  }
}

export function getToken(): string | null {
  return accessToken;
}

export function setToken(token: string | null): void {
  accessToken = token;
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Storage is optional; the in-memory copy still works for this session.
  }
  tokenListeners.forEach((fn) => fn(token));
}

export function onTokenChange(fn: (token: string | null) => void): () => void {
  tokenListeners.add(fn);
  return () => tokenListeners.delete(fn);
}

function authHeaders(): Record<string, string> {
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

/* -- low-level ------------------------------------------------------------ */

async function readDetail(resp: Response): Promise<string> {
  try {
    const body = await resp.json();
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length) {
      // FastAPI validation errors arrive as a list of {loc, msg}.
      const first = detail[0] as { loc?: unknown[]; msg?: string };
      const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : null;
      return field ? `${String(field)}: ${first.msg ?? "invalid"}` : (first.msg ?? "invalid");
    }
    return `HTTP ${resp.status}`;
  } catch {
    return `HTTP ${resp.status}`;
  }
}

/** Plain-JSON request, for the Phase 1 endpoints. */
async function plain<T>(path: string, init: RequestInit = {}): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(path, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(),
        ...(init.headers ?? {}),
      },
    });
  } catch (err) {
    throw new ApiError(
      "NETWORK",
      err instanceof Error ? err.message : "Could not reach the server.",
    );
  }
  if (!resp.ok) {
    throw new ApiError(
      resp.status === 401 ? "UNAUTHORIZED" : `HTTP_${resp.status}`,
      await readDetail(resp),
      resp.status,
    );
  }
  return (await resp.json()) as T;
}

/** Envelope request, for the legacy `/api/nepse/*` endpoints. */
async function envelope<T>(path: string, signal?: AbortSignal): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`/api/nepse${path}`, { signal, headers: authHeaders() });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(
      "NETWORK",
      err instanceof Error ? err.message : "Could not reach the server.",
    );
  }
  let body: ApiEnvelope<T> | null = null;
  try {
    body = (await resp.json()) as ApiEnvelope<T>;
  } catch {
    throw new ApiError("BAD_RESPONSE", `HTTP ${resp.status}`, resp.status);
  }
  if (!body || body.success !== true || body.data === undefined) {
    const err = body?.error;
    throw new ApiError(
      err?.code ?? "UNKNOWN",
      err?.message ?? `HTTP ${resp.status}`,
      resp.status,
    );
  }
  return body.data;
}

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const out = search.toString();
  return out ? `?${out}` : "";
}

/* -- legacy market endpoints ---------------------------------------------- */

export const market = {
  overview: (signal?: AbortSignal) => envelope<MarketOverview>("/market", signal),
  indices: (signal?: AbortSignal) =>
    envelope<{ nepse: IndexSummary; sub_indices: IndexSummary[] }>("/indices", signal),
  indexHistory: (index: string, start?: string, end?: string, signal?: AbortSignal) =>
    envelope<IndexHistory>(
      `/indices/${encodeURIComponent(index)}/history${qs({ start, end })}`,
      signal,
    ),
  stocks: (signal?: AbortSignal) => envelope<StockListResponse>("/stocks", signal),
  stock: (symbol: string, signal?: AbortSignal) =>
    envelope<Stock>(`/stocks/${encodeURIComponent(symbol)}`, signal),
  topGainers: (limit = 10, signal?: AbortSignal) =>
    envelope<MoverRow[]>(`/top-gainers${qs({ limit })}`, signal),
  topLosers: (limit = 10, signal?: AbortSignal) =>
    envelope<MoverRow[]>(`/top-losers${qs({ limit })}`, signal),
};

/* -- archive -------------------------------------------------------------- */

export const archive = {
  coverage: (signal?: AbortSignal) => plain<Coverage>("/api/archive/coverage", { signal }),
  asOf: (date?: string, signal?: AbortSignal) =>
    plain<AsOfResult>(`/api/archive/as-of${qs({ date })}`, { signal }),
  sessions: (start?: string, end?: string, limit = 400, signal?: AbortSignal) =>
    plain<SessionsResponse>(`/api/archive/sessions${qs({ start, end, limit })}`, { signal }),
  bars: (symbol: string, start?: string, end?: string, signal?: AbortSignal) =>
    plain<BarsResponse>(`/api/archive/bars/${encodeURIComponent(symbol)}${qs({ start, end })}`, {
      signal,
    }),
  runs: (limit = 20, signal?: AbortSignal) =>
    plain<RunsResponse>(`/api/archive/runs${qs({ limit })}`, { signal }),
  backfill: (body: {
    start?: string;
    end?: string;
    pause_ms?: number;
    force?: boolean;
    symbol?: string;
  }) => plain<{ detail: string }>("/api/archive/backfill", { method: "POST", body: JSON.stringify(body) }),
};

/* -- analytics ------------------------------------------------------------ */

export const analytics = {
  indicators: (symbol: string, signal?: AbortSignal) =>
    plain<IndicatorsResponse>(`/api/analytics/indicators/${encodeURIComponent(symbol)}`, { signal }),
  summary: (symbol: string, signal?: AbortSignal) =>
    plain<Record<string, unknown>>(`/api/analytics/summary/${encodeURIComponent(symbol)}`, {
      signal,
    }),
  compare: (symbols: string[], signal?: AbortSignal) =>
    plain<Record<string, unknown>>("/api/analytics/compare", {
      method: "POST",
      body: JSON.stringify({ symbols }),
      signal,
    }),
  periods: (signal?: AbortSignal) =>
    plain<VisualisationPeriods>("/api/analytics/visualisation/periods", { signal }),
  heatmap: (
    params: { period?: PeriodKey; size?: SizeMetric; limit?: number } = {},
    signal?: AbortSignal,
  ) =>
    plain<HeatmapResponse>(`/api/analytics/visualisation/heatmap${qs(params)}`, { signal }),
  screener: (params: Record<string, string | number | boolean | undefined>, signal?: AbortSignal) =>
    plain<ScreenerResponse>(`/api/analytics/screener${qs(params)}`, { signal }),
  chart: (
    symbol: string,
    params: { range?: string; mode?: string; indicators?: string } = {},
    signal?: AbortSignal,
  ) =>
    plain<ChartResponse>(`/api/analytics/chart/${encodeURIComponent(symbol)}${qs(params)}`, {
      signal,
    }),
};

/** The one composite company response, so the page needs a single request. */
// Moved to reference.company for consistency with other reference endpoints.

/* -- reference ------------------------------------------------------------ */

export const reference = {
  securities: (search?: string, activeOnly = true, signal?: AbortSignal) =>
    plain<SecuritiesResponse>(
      `/api/reference/securities${qs({ search, active_only: activeOnly })}`,
      { signal },
    ),
  sectors: (signal?: AbortSignal) =>
    plain<{ count: number; sectors: SectorRow[] }>("/api/reference/sectors", { signal }),
  brokers: (
    filters: { province?: string; search?: string; active_only?: boolean } = {},
    signal?: AbortSignal,
  ) => plain<BrokersResponse>(`/api/reference/brokers${qs(filters)}`, { signal }),
  funds: (tab?: string, signal?: AbortSignal) =>
    plain<FundsResponse>(`/api/reference/funds${qs({ tab })}`, { signal }),
  fundDetail: (symbol: string, signal?: AbortSignal) =>
    plain<FundDetailResponse>(`/api/reference/funds/${encodeURIComponent(symbol)}`, { signal }),
  fundNavImport: (symbol: string, payload: { nav: number; nav_date: string; source?: string }) =>
    plain<{ code: string; nav: number; nav_date: string; source: string }>(
      `/api/reference/funds/${encodeURIComponent(symbol)}/nav`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  fundNavHistory: (symbol: string, signal?: AbortSignal) =>
    plain<{ code: string; name: string | null; count: number; points: { nav_date: string; nav: number; source: string | null; created_at: string | null }[] }>(
      `/api/reference/funds/${encodeURIComponent(symbol)}/nav-history`,
      { signal },
    ),
  dividends: (symbol: string, signal?: AbortSignal) =>
    plain<DividendsResponse>(`/api/reference/dividends/${encodeURIComponent(symbol)}`, { signal }),
  dividendAnalysis: (params: { fiscal_year?: string; symbol?: string; min_consecutive?: number } = {}, signal?: AbortSignal) =>
    plain<any>(`/api/reference/dividends/analysis${qs(params)}`, { signal }),
  corporateActionsFeed: (params: { sector?: string; action_type?: string; date_from?: string; date_to?: string; upcoming_only?: boolean } = {}, signal?: AbortSignal) =>
    plain<any>(`/api/reference/corporate-actions${qs(params)}`, { signal }),
  upcomingCorporateActions: (params: { days?: number } = {}, signal?: AbortSignal) =>
    plain<any>(`/api/reference/corporate-actions/upcoming${qs(params)}`, { signal }),
  enrich: (symbol: string) =>
    plain<EnrichResult>(`/api/reference/enrich/${encodeURIComponent(symbol)}`, { method: "POST" }),
  enrichAll: (params: { limit?: number; resume?: boolean } = {}) =>
    plain<{ attempted: number; enriched: number; failed: string[]; remaining_without_listed_shares: number }>(
      "/api/reference/enrich-all",
      { method: "POST", body: JSON.stringify(params) },
    ),
  sync: () =>
    plain<{ securities: number; sectors: number; brokers: number; funds: number; hint: string }>(
      "/api/reference/sync",
      { method: "POST" },
    ),
  company: (symbol: string, signal?: AbortSignal) =>
    plain<CompanyResponse>(`/api/reference/companies/${encodeURIComponent(symbol)}`, { signal }),
};

/* -- auth ----------------------------------------------------------------- */

export const auth = {
  register: (email: string, password: string, display_name?: string) =>
    plain<TokenResponse>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, display_name: display_name || null }),
    }),
  login: (email: string, password: string) =>
    plain<TokenResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  me: (signal?: AbortSignal) => plain<User>("/api/auth/me", { signal }),
  logout: () => plain<{ detail: string }>("/api/auth/logout", { method: "POST" }),
  changePassword: (current_password: string, new_password: string) =>
    plain<{ detail: string }>("/api/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    }),
  setTheme: (theme: string) =>
    plain<User>("/api/auth/me", { method: "PATCH", body: JSON.stringify({ theme }) }),
};

/* -- Phase 4: Portfolio --------------------------------------------------- */

export const portfolio = {
  create: (name: string, base_currency = "NPR") =>
    plain<Portfolio>("/api/portfolio", {
      method: "POST",
      body: JSON.stringify({ name, base_currency }),
    }),
  list: () =>
    plain<PortfoliosResponse>("/api/portfolio"),
  get: (id: string) =>
    plain<Portfolio>(`/api/portfolio/${encodeURIComponent(id)}`),
  update: (id: string, name?: string, base_currency?: string) =>
    plain<Portfolio>(`/api/portfolio/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ name, base_currency }),
    }),
  delete: (id: string) =>
    plain<{ detail: string }>(`/api/portfolio/${encodeURIComponent(id)}`, { method: "DELETE" }),
  addTransaction: (portfolioId: string, tx: {
    symbol: string;
    side: "buy" | "sell";
    quantity: number;
    price: number;
    trade_date: string;
    fees?: number;
    note?: string;
  }) =>
    plain<Transaction>(`/api/portfolio/${encodeURIComponent(portfolioId)}/transactions`, {
      method: "POST",
      body: JSON.stringify(tx),
    }),
  listTransactions: (portfolioId: string, params: { symbol?: string; limit?: number; offset?: number } = {}) =>
    plain<TransactionsResponse>(`/api/portfolio/${encodeURIComponent(portfolioId)}/transactions${qs(params)}`),
  updateTransaction: (portfolioId: string, transactionId: string, updates: Record<string, any>) =>
    plain<Transaction>(`/api/portfolio/${encodeURIComponent(portfolioId)}/transactions/${encodeURIComponent(transactionId)}`, {
      method: "PATCH",
      body: JSON.stringify(updates),
    }),
  deleteTransaction: (portfolioId: string, transactionId: string) =>
    plain<{ detail: string }>(`/api/portfolio/${encodeURIComponent(portfolioId)}/transactions/${encodeURIComponent(transactionId)}`, {
      method: "DELETE",
    }),
  getHoldings: (portfolioId: string) =>
    plain<HoldingsResponse>(`/api/portfolio/${encodeURIComponent(portfolioId)}/holdings`),
  getValuation: (portfolioId: string) =>
    plain<ValuationResponse>(`/api/portfolio/${encodeURIComponent(portfolioId)}/valuation`),
  getXIRR: (portfolioId: string) =>
    plain<XIRRResponse>(`/api/portfolio/${encodeURIComponent(portfolioId)}/xirr`),
};

/* -- Phase 4: Watchlist --------------------------------------------------- */

export const watchlist = {
  create: (name: string) =>
    plain<Watchlist>("/api/watchlist", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  list: () =>
    plain<WatchlistsResponse>("/api/watchlist"),
  get: (id: string) =>
    plain<Watchlist>(`/api/watchlist/${encodeURIComponent(id)}`),
  update: (id: string, name: string) =>
    plain<Watchlist>(`/api/watchlist/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),
  delete: (id: string) =>
    plain<{ detail: string }>(`/api/watchlist/${encodeURIComponent(id)}`, { method: "DELETE" }),
  addItem: (watchlistId: string, symbol: string, note?: string) =>
    plain<WatchlistItem>(`/api/watchlist/${encodeURIComponent(watchlistId)}/items`, {
      method: "POST",
      body: JSON.stringify({ symbol, note }),
    }),
  removeItem: (watchlistId: string, symbol: string) =>
    plain<{ detail: string }>(`/api/watchlist/${encodeURIComponent(watchlistId)}/items/${encodeURIComponent(symbol)}`, {
      method: "DELETE",
    }),
  getItems: (watchlistId: string) =>
    plain<WatchlistItemsResponse>(`/api/watchlist/${encodeURIComponent(watchlistId)}/items`),
  reorderItem: (watchlistId: string, symbol: string, position: number) =>
    plain<{ detail: string }>(`/api/watchlist/${encodeURIComponent(watchlistId)}/items/${encodeURIComponent(symbol)}/reorder`, {
      method: "PATCH",
      body: JSON.stringify({ position }),
    }),
};

/* -- Phase 4: Alerts ------------------------------------------------------ */

export const alerts = {
  // Channels
  createChannel: (channel_type: "email" | "telegram" | "in_app", config: Record<string, any>) =>
    plain<AlertChannel>("/api/alerts/channels", {
      method: "POST",
      body: JSON.stringify({ channel_type, config }),
    }),
  listChannels: () =>
    plain<AlertChannelsResponse>("/api/alerts/channels"),
  updateChannel: (channelId: string, config?: Record<string, any>, is_active?: boolean) =>
    plain<AlertChannel>(`/api/alerts/channels/${encodeURIComponent(channelId)}`, {
      method: "PATCH",
      body: JSON.stringify({ config, is_active }),
    }),
  deleteChannel: (channelId: string) =>
    plain<{ detail: string }>(`/api/alerts/channels/${encodeURIComponent(channelId)}`, { method: "DELETE" }),
  // Rules
  createRule: (rule: {
    kind: string;
    symbol?: string;
    params: Record<string, any>;
    channel_id?: string;
    cooldown_seconds?: number;
    is_one_shot?: boolean;
  }) =>
    plain<AlertRule>("/api/alerts/rules", {
      method: "POST",
      body: JSON.stringify(rule),
    }),
  listRules: () =>
    plain<AlertRulesResponse>("/api/alerts/rules"),
  getRule: (ruleId: string) =>
    plain<AlertRule>(`/api/alerts/rules/${encodeURIComponent(ruleId)}`),
  updateRule: (ruleId: string, updates: Record<string, any>) =>
    plain<AlertRule>(`/api/alerts/rules/${encodeURIComponent(ruleId)}`, {
      method: "PATCH",
      body: JSON.stringify(updates),
    }),
  deleteRule: (ruleId: string) =>
    plain<{ detail: string }>(`/api/alerts/rules/${encodeURIComponent(ruleId)}`, { method: "DELETE" }),
  getRuleEvents: (ruleId: string, limit = 100) =>
    plain<AlertEventsResponse>(`/api/alerts/rules/${encodeURIComponent(ruleId)}/events${qs({ limit })}`),
  evaluateRule: (kind: string, symbol: string, params: Record<string, any>) =>
    plain<{ triggered: boolean; result: any }>("/api/alerts/evaluate", {
      method: "POST",
      body: JSON.stringify({ kind, symbol, params }),
    }),
};

/* -- Phase 4: Calculator -------------------------------------------------- */

export const calculator = {
  buySell: (quantity: number, price: number, side: "buy" | "sell") =>
    plain<BuySellResult>("/api/calculator/buy-sell", {
      method: "POST",
      body: JSON.stringify({ quantity, price, side }),
    }),
  bonusRight: (original_quantity: number, bonus_ratio: number, right_ratio: number, right_price?: number) =>
    plain<BonusRightResult>("/api/calculator/bonus-right", {
      method: "POST",
      body: JSON.stringify({ original_quantity, bonus_ratio, right_ratio, right_price }),
    }),
  wacc: (transactions: { date: string; side: "buy" | "sell"; quantity: number; price: number; fees?: number }[]) =>
    plain<WACCResult>("/api/calculator/wacc", {
      method: "POST",
      body: JSON.stringify({ transactions }),
    }),
  breakEven: (avg_cost: number, current_price?: number) =>
    plain<BreakEvenResult>("/api/calculator/break-even", {
      method: "POST",
      body: JSON.stringify({ avg_cost, current_price }),
    }),
  dividendYield: (face_value: number, cash_dividend_pct: number, ltp?: number, avg_cost?: number) =>
    plain<DividendYieldResult>("/api/calculator/dividend-yield", {
      method: "POST",
      body: JSON.stringify({ face_value, cash_dividend_pct, ltp, avg_cost }),
    }),
  xirr: (cashflows: { date: string; amount: number }[]) =>
    plain<XIRRResult>("/api/calculator/xirr", {
      method: "POST",
      body: JSON.stringify({ cashflows }),
    }),
  adjustPrice: (symbol: string, original_price: number, bonus_events: { date: string; ratio: number }[], right_events: { date: string; ratio: number; price: number }[]) =>
    plain<BonusRightAdjustedPrice>("/api/calculator/adjust-price", {
      method: "POST",
      body: JSON.stringify({ symbol, original_price, bonus_events, right_events }),
    }),
};

/* -- Phase 4: News -------------------------------------------------------- */

export const news = {
  list: (params: { symbol?: string; news_type?: string; date_from?: string; date_to?: string; limit?: number; offset?: number } = {}) =>
    plain<NewsResponse>(`/api/news${qs(params)}`),
  get: (newsId: string) =>
    plain<NewsItem>(`/api/news/${encodeURIComponent(newsId)}`),
  sync: (symbol?: string, limit = 100) =>
    plain<NewsResponse>("/api/news/sync", {
      method: "POST",
      body: JSON.stringify({ symbol, limit }),
    }),
  search: (q: string, limit = 20) =>
    plain<NewsSearchResponse>(`/api/news/search${qs({ q, limit })}`),
};

/* -- Phase 4: Quarterly Analysis ------------------------------------------ */

export const quarterly = {
  getPeriods: () =>
    plain<QuarterlyPeriodsResponse>("/api/analytics/quarterly/periods"),
  getAnalysis: (symbol: string, fiscal_year?: string, quarter?: number) =>
    plain<QuarterlyResponse>(`/api/analytics/quarterly/${encodeURIComponent(symbol)}${qs({ fiscal_year, quarter })}`),
  getHistory: (symbol: string, limit = 20) =>
    plain<QuarterlyResponse>(`/api/analytics/quarterly/${encodeURIComponent(symbol)}/history${qs({ limit })}`),
};

/* -- Phase 5: AI -------------------------------------------------------- */

export const ai = {
  status: () =>
    plain<AIStatus>("/api/ai/status"),
  statusPublic: () =>
    plain<AIStatus>("/api/ai/status/public"),
  ask: (request: AskRequest) =>
    plain<AskResponse>("/api/ai/ask", {
      method: "POST",
      body: JSON.stringify(request),
    }),
  stream: (request: AskRequest) =>
    fetch("/api/ai/stream", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(),
      },
      body: JSON.stringify(request),
    }).then(async (resp) => {
      if (!resp.ok) throw new Error(await resp.text());
      return resp.body;
    }),
};

export type { Measured, BackfillRunRow, BrokerRow };
