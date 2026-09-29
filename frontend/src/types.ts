/* Types mirroring the backend.

 * Two response shapes coexist:
 *   1. The legacy `/api/nepse/*` endpoints wrap payloads in an envelope
 *      (`{success, data, error}`) - see ApiEnvelope.
 *   2. The Phase 1 endpoints (`/api/archive`, `/api/analytics`, `/api/reference`,
 *      `/api/auth`) return plain JSON.
 *
 * Both are declared here so nothing is cast to `any` at a call site.
 */

/* -- legacy envelope ------------------------------------------------------ */

export interface ApiEnvelope<T> {
  success: boolean;
  data?: T;
  error?: { code: string; message: string };
}

export interface MarketStatus {
  is_open: boolean;
  as_of: string | null;
}

export interface MarketSummary {
  business_date: string | null;
  total_turnover: number | null;
  total_traded_shares: number | null;
  total_transactions: number | null;
  traded_scrips: number | null;
}

export interface IndexSummary {
  name: string;
  value: number | null;
  change: number | null;
  change_percentage: number | null;
  /** True when `value` is the last known close, not a live tick. */
  is_closed?: boolean | null;
}

export interface MarketOverview {
  status: MarketStatus;
  summary: MarketSummary | null;
  nepse_index: IndexSummary | null;
}

export interface IndexPoint {
  index_name: string;
  business_date: string | null;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  turnover: number | null;
  volume: number | null;
  total_transactions: number | null;
}

export interface Stock {
  symbol: string;
  security_id: number;
  security_name: string | null;
  open_price: number | null;
  high_price: number | null;
  low_price: number | null;
  close_price: number | null;
  last_traded_price: number | null;
  previous_close: number | null;
  change_percentage: number | null;
  total_traded_quantity: number | null;
  total_traded_value: number | null;
  total_trades: number | null;
  fifty_two_week_high: number | null;
  fifty_two_week_low: number | null;
  last_updated: string | null;
}

export interface StockListResponse {
  count: number;
  stocks: Stock[];
}

export interface MoverRow {
  symbol: string;
  security_name?: string;
  ltp?: number;
  cp?: number;
  point_change?: number;
  percentage_change?: number;
}

export interface IndexHistory {
  index: string;
  start: string | null;
  end: string | null;
  count: number;
  history: IndexPoint[];
}

/* -- provenance ----------------------------------------------------------- */

/** Mirrors `app.core.provenance.ValueStatus`. */
export type ValueStatus =
  | "ok"
  | "declared_zero"
  | "not_reported"
  | "not_published"
  | "upstream_unavailable"
  | "not_applicable"
  | "pending";

/**
 * Mirrors `app.core.provenance.Measured`.
 *
 * `value: null` never means zero, and a `status` of `declared_zero` means the
 * source really did report 0. The UI must render the status, not just the
 * number.
 */
export interface Measured {
  value: number | null;
  status: ValueStatus;
  as_of: string | null;
  source: string | null;
  note: string | null;
}

/* -- archive -------------------------------------------------------------- */

export interface Coverage {
  first_session: string | null;
  last_session: string | null;
  known_days: number;
  sessions: number;
  non_sessions: number;
  unknown_days: number;
  bars: number;
  symbols: number;
  nepse_published_floor: string;
  note: string;
}

export interface AsOfResult {
  requested: string;
  resolved: string | null;
  walked_back: boolean;
  reason: string | null;
}

export interface SessionRow {
  business_date: string;
  is_session: boolean | null;
  row_count: number | null;
  fetched_at: string | null;
  note: string | null;
}

export interface SessionsResponse {
  days: SessionRow[];
  legend: Record<string, string>;
}

export interface DailyBarRow {
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  prev_close: number | null;
  volume: number | null;
  turnover: number | null;
  trades: number | null;
  vwap: number | null;
  high_52w: number | null;
  low_52w: number | null;
  market_cap: number | null;
}

export interface BarsResponse {
  symbol: string;
  count: number;
  first: string | null;
  last: string | null;
  bars: DailyBarRow[];
}

export interface BackfillRunRow {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: string;
  sessions: number;
  non_sessions: number;
  failed: number;
  rows_written: number;
  note: string | null;
}

export interface RunsResponse {
  runs: BackfillRunRow[];
}

/* -- analytics ------------------------------------------------------------ */

export interface SeriesPoint {
  date: string;
  value: number | null;
}

export interface IndicatorSeries {
  [name: string]: SeriesPoint[];
}

export interface PriceSeries {
  dates: string[];
  open: (number | null)[];
  high: (number | null)[];
  low: (number | null)[];
  close: (number | null)[];
  volume: (number | null)[];
}

export interface IndicatorsResponse {
  symbol: string;
  as_of: string;
  sessions: number;
  first: string;
  price: PriceSeries;
  indicators: IndicatorSeries;
  notes: Record<string, string>;
}

export interface AnalyticsSummary {
  symbol: string;
  as_of: string;
  [indicator: string]: Measured | string;
}

/* -- reference ------------------------------------------------------------ */

export interface SecurityRow {
  symbol: string;
  name: string | null;
  sector: string | null;
  type: string | null;
  listed_shares: number | null;
  isin: string | null;
  tick_size: number | null;
  face_value: number | null;
  listing_date: string | null;
  credit_rating: string | null;
  is_active: boolean;
}

export interface SecuritiesResponse {
  count: number;
  securities: SecurityRow[];
}

export interface SectorRow {
  code: string;
  name: string;
  index: string | null;
}

export interface SectorsResponse {
  count: number;
  sectors: SectorRow[];
}

export interface BrokerRow {
  member_code: string;
  member_name: string;
  is_dealer: boolean | null;
  is_active: boolean | null;
  province: string | null;
  district: string | null;
  phone: string | null;
  email: string | null;
  website: string | null;
}

export interface BrokersResponse {
  count: number;
  brokers: BrokerRow[];
  provinces: string[];
  attribution: { available: boolean; reason: string };
}

export interface FundRow {
  code: string;
  name: string | null;
  manager: string | null;
  category: string | null;
  scheme_description: string | null;
  scheme_name: string | null;
  close_ended: boolean | null;
  maturity_date: string | null;
  face_value: number | null;
  units: number | null;
  fund_size: number | null;
  listing_date: string | null;
  isin: string | null;
  nav: Measured;
  premium_discount: number | null;
  premium_discount_status: string;
  premium_discount_reason: string | null;
  dividend_count: number;
}

export interface FundDetailResponse {
  code: string;
  name: string | null;
  manager: string | null;
  category: string | null;
  scheme_description: string | null;
  scheme_name: string | null;
  close_ended: boolean | null;
  maturity_date: string | null;
  face_value: number | null;
  units: number | null;
  fund_size: number | null;
  listing_date: string | null;
  isin: string | null;
  nav: Measured;
  premium_discount: number | null;
  premium_discount_status: string;
  premium_discount_reason: string | null;
  dividends: {
    count: number;
    actions: DividendRow[];
  };
  nav_history: {
    nav_date: string;
    nav: number;
    source: string | null;
    created_at: string | null;
  }[];
  updated_at: string | null;
}

export interface FundsResponse {
  count: number;
  total: number;
  tab: string | null;
  funds: FundRow[];
  nav_note: string;
  unsynced: UnsyncedFund[];
  unsynced_count: number;
}

export interface UnsyncedFund {
  symbol: string;
  name: string | null;
  reason: string;
  nepse_security_id: number | null;
  listed_shares: number | null;
  promoter_pct: number | null;
  public_pct: number | null;
}

export interface DividendRow {
  fiscal_year: string;
  cash_dividend_pct: Measured;
  bonus_pct: Measured;
  book_close: string | null;
  agm_date: string | null;
  source: string | null;
}

export interface DividendsResponse {
  symbol: string;
  count: number;
  actions: DividendRow[];
  note: string;
}

export interface EnrichResult {
  symbol: string;
  sector: string | null;
  security_type: string | null;
  security_type_name: string | null;
  is_mutual_fund: boolean;
  listed_shares: number | null;
  isin: string | null;
  credit_rating: string | null;
}

/* -- auth ----------------------------------------------------------------- */

export interface User {
  id: string;
  email: string;
  display_name: string | null;
  is_admin: boolean;
  theme: string | null;
  created_at: string | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
  user: User;
}

/* -- Phase 2: market visualisation --------------------------------------- */

export type PeriodKey = "1D" | "1W" | "1M" | "3M" | "6M" | "1Y" | "YTD";
export type SizeMetric = "market_cap" | "volume" | "turnover";

export interface ArchiveCoverage {
  first: string | null;
  last: string | null;
  sessions: number;
  note: string;
}

export interface VisualisationPeriods {
  periods: { value: PeriodKey; label: string; calendar_days: number | null }[];
  size_metrics: { value: SizeMetric; label: string }[];
  legend: { min_pct: number; max_pct: number };
  coverage: ArchiveCoverage;
}

export interface TreemapTile {
  symbol: string;
  name: string | null;
  sector: string | null;
  size: number;
  change_pct: number;
  ltp: number | null;
  market_cap: number | null;
}

export interface SectorSlice {
  sector: string;
  size: number;
  symbols: number;
  change_pct: number | null;
}

export interface HeatmapResponse {
  period: PeriodKey;
  period_label: string;
  size: SizeMetric;
  legend: { min_pct: number; max_pct: number };
  tiles: TreemapTile[];
  sectors: SectorSlice[];
  counts: { scanned: number; drawn: number; skipped: number; truncated: number };
  skipped: { symbol: string; reason: string }[];
  coverage: ArchiveCoverage;
  notes: Record<string, string>;
}

/* -- Phase 2: screener ---------------------------------------------------- */

export interface ScreenerRow {
  symbol: string;
  name: string | null;
  sector: string | null;
  as_of: string;
  sessions: number;
  ltp: number | null;
  prev_close: number | null;
  change: number | null;
  change_pct: number | null;
  market_cap: number | null;
  listed_shares: number | null;
  volume: number | null;
  turnover: number | null;
  trades: number | null;
  day_high: number | null;
  day_low: number | null;
  ret_5d: number | null;
  ret_1m: number | null;
  ret_3m: number | null;
  ret_6m: number | null;
  ret_1y: number | null;
  ret_ytd: number | null;
  vwap_180d: number | null;
  rsi_14: number | null;
  high_52w: number | null;
  low_52w: number | null;
  /** Why a null is null. Absent keys resolved successfully. */
  reasons: Record<string, string>;
}

export interface ScreenerResponse {
  rows: ScreenerRow[];
  total: number;
  offset: number;
  limit: number;
  sort: string;
  descending: boolean;
  columns: { field: string; label: string }[];
  rejected_by: { field: string; count: number }[];
  undecidable: { field: string; count: number; reason: string }[];
  coverage: ArchiveCoverage;
  fundamentals: { available: boolean; status: string; reason: string };
  earnings: { available: boolean; reason: string };
  notes: Record<string, string>;
}

/* -- Phase 2: company ----------------------------------------------------- */

/** A section NEPSE does not publish: explicit absence, never a bare null. */
export interface Unavailable {
  available: false;
  status?: string;
  reason: string;
}

export interface CompanyProfile {
  symbol: string;
  name: string | null;
  sector: string | null;
  isin: string | null;
  security_type: string | null;
  board: string | null;
  tick_size: number | null;
  face_value: number | null;
  listing_date: string | null;
  credit_rating: string | null;
  is_active: boolean | null;
  needs_enrichment?: string[];
}

export interface PromoterPublicSplit {
  available: true;
  promoter_shares: number | null;
  public_shares: number | null;
  promoter_pct: number | null;
  public_pct: number | null;
  source: string;
  as_of: string | null;
}

export interface NewsSection {
  available: true;
  count: number;
  source: string;
  items: {
    id: string | null;
    headline: string | null;
    type: string | null;
    source: string | null;
    published_at: string | null;
    parsed: Record<string, string> | null;
    body: string | null;
  }[];
}

export interface NoticeFact {
  available: true;
  value: string;
  verbatim: true;
  from_headline: string | null;
  published_at: string | null;
  note: string;
}

export interface MarketDepthSection {
  available: true;
  source: string;
  payload: any;
  note: string;
}

export interface MarketDepthUnavailable extends Unavailable {
  checked_at?: string;
}

export interface CompanyResponse {
  symbol: string;
  profile: CompanyProfile;
  price: {
    as_of: string | null;
    sessions: number;
    change: number | null;
    change_pct: number | null;
    day_high: number | null;
    day_low: number | null;
    high_52w: number | null;
    low_52w: number | null;
    volume: number | null;
    turnover: number | null;
    reasons: Record<string, string>;
  };
  valuation: {
    ltp: { value: number | null; as_of?: string; reason?: string };
    market_cap: { value: number | null; formula?: string; as_of?: string; reason?: string };
    dividend_yield_pct: {
      value: number | null;
      fiscal_year?: string;
      cash_dividend_pct?: number;
      face_value?: number;
      basis?: string;
      reason?: string;
    };
    ratios: Record<string, { available: false; reason: string }>;
  };
  dividends: {
    count: number;
    actions: DividendRow[];
    coverage_note: string;
  };
  promoter_public_split: PromoterPublicSplit | Unavailable;
  news: NewsSection | Unavailable;
  book_closure: NoticeFact | Unavailable;
  agm: NoticeFact | Unavailable;
  market_depth: MarketDepthSection | MarketDepthUnavailable;
  notes: string[];
}

/* -- Phase 2: technical chart --------------------------------------------- */

export interface ChartSeries {
  dates: string[];
  open: (number | null)[];
  high: (number | null)[];
  low: (number | null)[];
  close: (number | null)[];
  volume: (number | null)[];
}

export type IndicatorKey =
  | "sma_20"
  | "ema_20"
  | "wma_20"
  | "hma_16"
  | "dema_20"
  | "tema_20"
  | "trix_15"
  | "adx"
  | "plus_di"
  | "minus_di"
  | "dx"
  | "aroon_up"
  | "aroon_down"
  | "rsi_14"
  | "macd"
  | "macd_signal"
  | "macd_histogram"
  | "bb_upper"
  | "bb_middle"
  | "bb_lower"
  | "vwap"
  | "obv"
  | "accumulation_distribution"
  | "chaikin_money_flow_20"
  | "money_flow_index_14"
  | "psar"
  | "supertrend"
  | "vortex_plus"
  | "vortex_minus"
  | "ichimoku_tenkan"
  | "ichimoku_kijun"
  | "ichimoku_senkou_a"
  | "ichimoku_senkou_b"
  | "ichimoku_chikou"
  | "roc_1";

export interface ChartRangeOption {
  value: string;
  available: boolean;
  complete: boolean;
  first_shown: string;
}

export interface ChartResponse {
  symbol: string;
  name: string | null;
  sector: string | null;
  as_of: string;
  series: ChartSeries;
  indicators: Partial<Record<IndicatorKey, (number | null)[]>>;
  range: {
    requested: string;
    available: boolean;
    complete: boolean;
    first_shown: string;
    sessions_shown: number;
    days_available: number;
    days_requested: number;
    reason: string | null;
    options: ChartRangeOption[];
  };
  price_mode: {
    requested: string;
    applied: string;
    differs_from_requested: boolean;
    reason: string | null;
  };
  panel: {
    day: {
      as_of: string | null;
      open?: number | null;
      high?: number | null;
      low?: number | null;
      ltp?: number | null;
      prev_close?: number | null;
      change?: number | null;
      change_pct?: number | null;
      incomplete_note?: string;
      reason?: string;
    };
    week_52: {
      high: number | null;
      low: number | null;
      sessions: number;
      reason: string | null;
    };
    recent_5_days: { date: string; close: number | null }[];
    performance: { label: string; pct: number | null; available: boolean }[];
  };
  notes: Record<string, string>;
}

/* -- Phase 4: Portfolio ---------------------------------------------------- */

export interface Portfolio {
  id: string;
  name: string;
  base_currency: string;
  created_at: string | null;
}

export interface PortfoliosResponse {
  portfolios: Portfolio[];
}

export interface Transaction {
  id: string;
  symbol: string;
  side: "buy" | "sell";
  quantity: number;
  price: number;
  trade_date: string;
  fees: number | null;
  note: string | null;
  created_at: string | null;
}

export interface TransactionsResponse {
  transactions: Transaction[];
}

export interface Holding {
  symbol: string;
  quantity: number;
  avg_cost: number;
  total_cost: number;
  first_bought_at: string | null;
  last_transacted_at: string | null;
}

export interface HoldingsResponse {
  holdings: Holding[];
}

export interface ValuationHolding {
  symbol: string;
  quantity: number;
  avg_cost: number;
  total_cost: number;
  ltp: number | null;
  market_value: number | null;
  unrealized_pl: number | null;
  unrealized_pl_pct: number | null;
  ltp_as_of: string | null;
  ltp_reason: string | null;
}

export interface ValuationResponse {
  portfolio_id: string;
  base_currency: string;
  holdings: ValuationHolding[];
  total_cost: number;
  total_market_value: number | null;
  total_unrealized_pl: number | null;
  total_unrealized_pl_pct: number | null;
  as_of: string;
}

export interface XIRRResponse {
  xirr: number | null;
  xirr_pct: number | null;
}

/* -- Phase 4: Watchlist ---------------------------------------------------- */

export interface Watchlist {
  id: string;
  name: string;
  created_at: string | null;
}

export interface WatchlistsResponse {
  watchlists: Watchlist[];
}

export interface WatchlistItem {
  symbol: string;
  note: string | null;
  created_at: string | null;
  ltp: number | null;
  change_pct: number | null;
  ltp_as_of: string | null;
  ltp_reason: string | null;
}

export interface WatchlistItemsResponse {
  items: WatchlistItem[];
}

/* -- Phase 4: Alerts ------------------------------------------------------- */

export interface AlertChannel {
  id: string;
  type: "email" | "telegram" | "in_app";
  config: Record<string, any>;
  is_active: boolean;
  is_verified: boolean;
  verified_at: string | null;
}

export interface AlertChannelsResponse {
  channels: AlertChannel[];
}

export interface AlertRule {
  id: string;
  kind: string;
  symbol: string | null;
  params: Record<string, any>;
  channel_id: string | null;
  cooldown_seconds: number;
  is_one_shot: boolean;
  is_active: boolean;
  trigger_count: number;
  last_triggered_at: string | null;
  created_at: string | null;
}

export interface AlertRulesResponse {
  rules: AlertRule[];
}

export interface AlertEvent {
  id: string;
  symbol: string;
  triggered_at: string | null;
  triggered_params: Record<string, any>;
  trigger_value: number | null;
  delivery_status: Record<string, any>;
}

export interface AlertEventsResponse {
  events: AlertEvent[];
}

/* -- Phase 4: Calculator --------------------------------------------------- */

export interface BuySellResult {
  gross_amount: number;
  broker_commission: number;
  sebon_fee: number;
  dp_charge: number;
  stt: number;
  total_fees: number;
  net_amount: number;
}

export interface BonusRightResult {
  original_quantity: number;
  bonus_shares: number;
  right_shares: number;
  new_quantity: number;
  additional_cost: number;
}

export interface WACCResult {
  symbol: string;
  total_quantity: number;
  total_cost: number;
  wacc: number;
}

export interface BreakEvenResult {
  symbol: string;
  avg_cost: number;
  break_even_price: number;
  break_even_pct: number;
}

export interface DividendYieldResult {
  symbol: string;
  face_value: number;
  cash_dividend_pct: number;
  dividend_per_share: number;
  yield_on_ltp: number | null;
  yield_on_cost: number | null;
  ltp: number | null;
  avg_cost: number | null;
}

export interface XIRRResult {
  xirr: number | null;
  xirr_pct: number | null;
  iterations: number;
  cashflows: { date: string; amount: number }[];
}

export interface BonusRightAdjustedPrice {
  symbol: string;
  original_price: number;
  adjusted_price: number;
  adjustment_factor: number;
}

/* -- Phase 4: News --------------------------------------------------------- */

export interface NewsItem {
  id: string;
  symbol: string | null;
  headline: string;
  news_type: string | null;
  news_source: string | null;
  published_at: string | null;
  body: string | null;
  parsed: Record<string, string> | null;
}

export interface NewsResponse {
  total: number;
  limit: number;
  offset: number;
  items: NewsItem[];
}

export interface NewsSearchResponse {
  query: string;
  count: number;
  results: NewsItem[];
}

/* -- Phase 4: Quarterly Analysis ------------------------------------------- */

export interface QuarterlyAnalysis {
  symbol: string;
  fiscal_year: string;
  quarter: number;
  quarterly_return: number | null;
  high: number | null;
  low: number | null;
  avg_volume: number | null;
  volatility: number | null;
  revenue: number | null;
  net_profit: number | null;
  eps: number | null;
  book_value_per_share: number | null;
  created_at: string | null;
}

export interface QuarterlyResponse {
  symbol: string;
  fiscal_year?: string;
  quarter?: number;
  history?: QuarterlyAnalysis[];
  quarters?: QuarterlyAnalysis[];
}

export interface QuarterlyPeriodsResponse {
  fiscal_years: string[];
  quarters: number[];
  note: string;
}

/* -- Phase 5: AI ------------------------------------------------------------ */

export interface AIStatus {
  configured: boolean;
  provider: string;
  model: string;
  rate_limit_per_minute: number;
  daily_limit: number;
  privacy_consent_required: boolean;
}

export interface AskRequest {
  question: string;
  symbols: string[];
  data_sources: string[];
  privacy_consent: boolean;
}

export interface AskResponse {
  answer: string;
  grounded: boolean;
  rate_limit_remaining: number;
}

export interface StreamChunk {
  chunk: string;
}
