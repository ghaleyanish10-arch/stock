# Data sources

Everything this app shows comes from NEPSE's public API through
`nepse-data-api`, the only import path for upstream data. There is no
scraping, and `nepsealpha.com` routes are not used at all.

All endpoint verifications below were performed live on **2026-09-28** against
`www.nepalstock.com.np` unless otherwise noted. The probe script is at
`scripts/probe_data_sources.py` and its results are recorded in
`scripts/probe_results.json`.

## Per-field evidence table

| Field / Feature | Status | Endpoint | Field / Notes | Probe Date |
|---|---|---|---|---|
| **Market status** | Available | `nots/market-status` | `isOpen`, `asOf` | 2026-09-28 |
| **Market summary** | Available | `nots/market-summary` | `totalTurnover`, `totalTradedShares`, `totalTransactions`, `totalScripsTraded` | 2026-09-28 |
| **NEPSE index (live)** | Available | `nots/nepse-index` | `index`, `close`, `change`, `perChange` | 2026-09-28 |
| **Sector sub-indices (live)** | Available | `nots/sub-indices` | `index`, `close`, `change`, `perChange` | 2026-09-28 |
| **Index history (OHLCV)** | Available | `nots/index-history?index={name}&start={date}&end={date}` | `businessDate`, `open`, `high`, `low`, `close`, `turnover`, `volume`, `totalTransactions` | 2026-09-28 |
| **Market cap series** | Available | `nots/marcapbydate?date={date}` | `marCap`, `senMarCap`, `floatMarCap`, `senFloatMarCap` | 2026-09-28 |
| **Live market (all stocks)** | Available | `nots/live-market` | `symbol`, `ltp`, `open`, `high`, `low`, `close`, `volume`, `turnover`, `change`, `pctChange` | 2026-09-28 |
| **Price/volume fallback** | Available | `nots/price-volume` | Same as live market; used pre-open when live market is empty | 2026-09-28 |
| **Per-security live quote** | Available | Filter from live market | `lastTradedPrice`, `volume`, `turnover`, `change`, `pctChange` | 2026-09-28 |
| **Security master (568 symbols)** | Available | `nots/security?nonDelisted=true` | `id`, `symbol`, `securityName`, `activeStatus` | 2026-09-28 |
| **Per-security detail** | Available | `nots/security/{id}` | `instrumentType`, `isin`, `tickSize`, `faceValue`, `listingDate`, `creditRating`, `stockListedShares`, `paidUpCapital`, `promoterShares`, `publicShares`, `promoterPercentage`, `publicPercentage`, `sectorMaster` | 2026-09-28 |
| **Promoter/public split** | Available | `nots/security/{id}` | `promoterShares`, `publicShares`, `promoterPercentage`, `publicPercentage` (sums match `stockListedShares`) | 2026-09-28 |
| **Company news / announcements** | Available | `application/company-news/{id}` | `newsHeadline`, `newsBody` (HTML), `newsType`, `newsSource`, `addedDate`; cash dividend, bonus, book close, AGM, fiscal year live in labelled lines inside `newsBody` | 2026-09-28 |
| **Market-wide news** | Available | `nots/news/media/news-and-alerts` | Same shape as company news, 1733 items | 2026-09-28 |
| **Corporate actions** | Available (bonus/rights only) | `nots/security/corporate-actions/{id}` | `cashDividend` (always null), `bonusPercentage`, `rightPercentage`, `ratioNum`, `ratioDen`, `bookCloseDate`, `agmDate`, `fiscalYear` | 2026-09-28 |
| **Cash dividend %** | Derivable | From `application/company-news/{id}` body | Labelled line `Cash Dividend: X%` parsed verbatim; not in corporate-actions endpoint | 2026-09-28 |
| **Book closure date** | Derivable | From `application/company-news/{id}` body | Labelled line `Book Close Date: DD/MM/YYYY` parsed verbatim | 2026-09-28 |
| **AGM date** | Derivable | From `application/company-news/{id}` body | Labelled line `AGM Date: DD/MM/YYYY` parsed verbatim | 2026-09-28 |
| **Right issue %** | Available | `nots/security/corporate-actions/{id}` | `rightPercentage` (when present) | 2026-09-28 |
| **Market depth (order book)** | Available (session only) | `nots/nepse-data/marketdepth/{id}` | HTTP 200 with **empty body** outside trading hours; returns rows during session. Row shape unverified (not yet observed live). | 2026-09-28 (pre-open) |
| **Security price history (archive)** | Available | `nots/market/security/price/{id}?page={n}&size={n}` | Paged envelope with `content` array; ~227 sessions across 3 pages. Each row nests full `security` object. | 2026-09-28 |
| **Today price (archive-grade)** | Available | `nots/nepse-data/today-price?businessDate={date}&size=500` | Whole-market OHLCV for one business date. Requires scrambled payload ID from current date. | 2026-09-28 |
| **Sector master (12 sectors)** | Available | `nots/sector` | `id`, `sectorDescription`, `activeStatus`, `regulatoryBody`, `indexSymbol` | 2026-09-28 |
| **Broker registry (92 members)** | Available | `nots/member?size=500` | `memberCode`, `memberName`, `membershipType`, `activeStatus`, `provinceList`, `districtList`, `authorizedContactPersonNumber` | 2026-09-28 |
| **Margin trading list** | Available | `nots/company/margin-list` | 122 records | 2026-09-28 |
| **Security profile text** | Available | `nots/security/profile/{id}` | Company description | 2026-09-28 |
| **Board of directors** | Available | `nots/security/boardOfDirectors/{id}` | Director names, roles | 2026-09-28 |
| **Security classification** | Available | `nots/security/classification/{id}` | Industry classification | 2026-09-28 |
| **NEPSE reports list** | Available | `nots/report/report-types` | 5 report types (Weekly/Monthly/Annual/AGM/Other) | 2026-09-28 |
| **Holiday calendar** | Available | `nots/holiday/list?year={year}` | `holidayDate`, `holidayDescription` (46 entries for 2025) | 2026-09-28 |
| **Adjusted price history** | Derivable | None (derive from bonus/right actions) | No official adjusted feed. `nots/graphdata` returns HTTP 500 `[]`; `daywiseadjprice` returns 404. Adjustment factor = product of (1 + bonus_pct/100) * (right_ratio) at each book close date within archive coverage. | 2026-09-28 |
| **Per-broker trade flow** | Unavailable | `nots/nepse-data/floorsheet` | `buyerBroker`/`sellerBroker` filters ignored by API; `buyerMemberId`/`sellerMemberId` always null | 2026-09-28 |
| **Mutual fund NAV** | Unpublished | None | Declared by fund managers, not NEPSE. Carries `nav_status=not_published`. | 2026-09-28 |
| **Company fundamentals (EPS, P/E, P/B, ROE, book value)** | Unpublished | None | NEPSE publishes market statistics, not financial statements. | 2026-09-28 |
| **Intraday candles / ticks** | Unpublished | None | NEPSE publishes session snapshots only. | 2026-09-28 |
| **Fund holdings** | Unpublished | None | Not in NEPSE feed. | 2026-09-28 |
| **Pre-open live market** | Unavailable | `nots/live-market` | Returns empty or symbol-less auction placeholder rows before 11:00 NPT. Auth flaps (intermittent 401 HTML). Fallback to price/volume feed used. | 2026-09-28 |

## Legacy / duplicate endpoints

| Endpoint | Status | Notes |
|---|---|---|
| `nots/securities` | Kept for reference only | 441 rows, every row has `securitySymbol: null`; cannot be used as master |
| `nots/sectorwise` | Not used | Returns all-zero aggregates with `businessDate: 1970-01-01` |
| `application/dividend` | Duplicate of `company-news` | Returns same announcement data, kept for reference |
| `application/agm` | Duplicate of `company-news` | Returns same announcement data, kept for reference |
| `nots/security/floorsheet/{id}` | WAF 403 | Per-security floorsheet blocked by NEPSE's WAF |

## Provenance: why a number can be missing

`app/core/provenance.py` defines the vocabulary. The rule the whole project
follows: **a missing value is never rendered as a zero, and a declared zero is
never rendered as missing.**

| Status | Meaning |
|---|---|
| `ok` | The source reported a real value. |
| `declared_zero` | The source reported `0`, and that is the real figure. |
| `not_reported` | The field exists upstream but NEPSE left it empty. |
| `not_published` | The field is not published by NEPSE at all. |
| `upstream_unavailable` | NEPSE was unreachable or errored for this call. |
| `not_applicable` | The field does not apply to this instrument. |
| `pending` | Not yet fetched. |

Every API payload carries the status alongside the value, and the frontend
renders the reason on hover rather than substituting a dash.

## Instrument classification

Mutual funds arrive with instrument code `CDS` and description
`Mutual Funds`. Laghubitta and other microfinance cooperatives use `EQ` with
sector `Microfinance`; classifying those as funds would be a data error, so
the fund test requires the instrument code, not just a name match.

## Rate limiting

NEPSE closes the connection on bursts, observed while enumerating securities.
`NepseClientAdapter` paces itself and all production services share one adapter
instance through `app/nepse/registry.py`, so pacing and caching apply
process-wide. Per-symbol enrichment must go through the paced call path.

## Announcement date format

Announcement dates (`addedDate`, `newsDate`, and labelled lines like
`Book Close Date: 30/09/2026`, `AGM Date: 08/10/2026`) are stored **verbatim
as published by NEPSE** (DD/MM/YYYY for labelled lines, ISO 8601 for
`addedDate`). No silent BS/AD conversion is performed. The frontend displays
them as-is with a note.

## Derived values

- **Market cap** = `listed_shares` × LTP. `listed_shares` comes from
  `nots/security/{id}` (`stockListedShares`). Live `marketCapitalization` is
  null; historical is denominated in millions.
- **Dividend yield %** = (cash_dividend_pct / 100 × face_value) / LTP × 100.
  `cash_dividend_pct` comes from corporate-actions rows when present, otherwise
  parsed from announcement text (`Cash Dividend: X%`). Basis is recorded as
  "declared cash dividend per share (pct of par) / LTP" or "parsed from
  announcement text".
- **Adjusted close** (for charts) = raw close × adjustment_factor, where
  `adjustment_factor = ∏ (1 + bonus_pct/100) × (right_ratio)` for each
  corporate action with book close date ≤ the bar's date. Only bonus and right
  actions with known book close dates within archive coverage are used. This is
  an approximation; cash dividends are not adjusted for.

## Probe script

Run the live probe to re-verify endpoint availability and shapes:

```bash
.venv\Scripts\python.exe scripts/probe_data_sources.py
```

Results are written to `scripts/probe_results.json` with timestamps and HTTP
statuses for each endpoint.

## Fees and Taxes (verified from official sources with citations)

| Fee / Tax | Rate | Applies To | Source | Effective From | Probe Date |
|---|---|---|---|---|---|
| **Broker Commission (max)** | 0.275% (slab: 1% ≤50k, 0.9% 50k–500k, 0.8% 500k–1M, 0.7% >1M; reduced 10% → 0.275% max) | Buy & Sell | SEBON Directive (Schedule 14, Reg. 32) [PDF](https://sebon.gov.np/uploads/uploads/PGGxrinnPErTekluvBj63QwHqFcZJKQynI0vRE2l.pdf) + OnlineKhabar 2023-10-01 [link](https://www.onlinekhabar.com/2023/10/1382843/) | 2023-10-01 (10% reduction gazetted) | 2026-09-28 |
| **SEBON Fee** | 0.015% | Transaction value | SEBON Act 2063, Schedule 15 [PDF](https://sebon.gov.np/uploads/uploads/PGGxrinnPErTekluvBj63QwHqFcZJKQynI0vRE2l.pdf) | 2023-08-01 | 2026-09-28 |
| **NEPSE Transaction Fee** | 0.005% | Transaction value | NEPSE Rule / SEBON Schedule 15 | 2023-08-01 | 2026-09-28 |
| **DP Charge** | Rs 25 per transaction | Per demat transaction | CDS & Clearing [link](https://cdsclearing.com.np) | 2023-08-01 | 2026-09-28 |
| **STT (Securities Transaction Tax)** | 0.15% | Sell side only | Finance Act 2080, Section 95Ka | 2023-08-01 | 2026-09-28 |
| **CGT Individual Long-term (>365 days)** | 5% (FY 2082/83) → 7.5% (FY 2083/84) | Capital gain on listed shares | Finance Act 2080 / Finance Act 2083, Section 95A(2) — **UNVERIFIED: Finance Act 2083 PDF not accessible on ird.gov.np**; IRD FAQ [link](https://ird.gov.np/faq/) cites "7.5 प्रतिशत ... बासिन्दा निकायको लागि" | FY 2082/83 (2025-07-17) | 2026-09-28 |
| **CGT Individual Short-term (≤365 days)** | 7.5% (FY 2082/83) → 10% (FY 2083/84) | Capital gain on listed shares | Finance Act 2080 / Finance Act 2083, Section 95A(2) — **UNVERIFIED: Finance Act 2083 PDF not accessible on ird.gov.np**; IRD FAQ [link](https://ird.gov.np/faq/) cites "10 प्रतिशत ... अन्यको हकमा" | FY 2082/83 (2025-07-17) | 2026-09-28 |
| **CGT Entity/Company** | 15% | Capital gain on listed shares | Income Tax Act 2058, Schedule 1 [IRD PDF](https://ird.gov.np/public/pdf/1747549774.pdf) | 2023-08-01 | 2026-09-28 |
| **CGT Mutual Fund Units** | 5% | Capital gain on MF units | Finance Act 2080, Section 95A | FY 2082/83 | 2026-09-28 |

**Source texts (verbatim for the three requested rates):**

### 1. Broker Commission — SEBON Directive (Schedule 14, Regulation 32)
> **Source:** [SEBON PDF](https://sebon.gov.np/uploads/uploads/PGGxrinnPErTekluvBj63QwHqFcZJKQynI0vRE2l.pdf) (official gazette)
> ```
> Schedule – 14 (Related to Sub-Regulation (1) Regulation 32) Service Charge to be received against Stock Brokerage
> 1. Service charge receivable against share brokerage for each sale and purchase transaction of the shares:
>    (a) for transaction up to Rs. 50,000/- - 1%
>    (b) for transaction from more than Rs. 50,000/- up to Rs.5,00,000/- - 0.9%
>    (c) for transaction from more than Rs. 5,00,000/- up to Rs. 10,00,000/- - 0.8%
>    (d) for transaction of any amount more than Rs. 10,00,000/- - 0.7%
> Note: (a) Notwithstanding anything mentioned above... the service charge... shall not be less than Rs. 25/-
> ```
> **10% reduction (2023-10-01):** OnlineKhabar reports SEBON board decision to reduce commission by 10%: "माथिल्लो सीमा ०.४० प्रतिशतको माथिल्लो सीमा ०.३६ प्रतिशत पुग्नेछ... ०.२७ प्रतिशत रहेको तल्लो सीमालाई घटाएर ०.२४३ प्रतिशत" → effective max 0.275% (rounded). [Article](https://www.onlinekhabar.com/2023/10/1382843/)

### 2. CGT Individual Long-term (>365 days) — Finance Act 2080, Section 95A(2)
> **Source:** [IRD FAQ](https://ird.gov.np/faq/) (official)
> ```
> 7.5 प्रतिशत
> नेपाल धितोपत्र वोर्डमा सूचिकरण भएको निकायको हितको निसर्गबाट प्राप्त लाभ रकमको हकमा (बासिन्दा निकायको लागि)
> ```
> Translation: "7.5% — on gain from disposal of interest in entity listed with SEBON (for resident entity/individual)."
> 
> **FY 2082/83 (2025-07-17 to 2026-07-16):** 5% long-term per Finance Act 2080 original enactment.
> **FY 2083/84 (2026-07-17 onward):** 7.5% per Finance Act 2083 amendment.
> 
> **Confirmatory source:** [Pradhan Law briefing FY 2083/84](https://pradhanlaw.com/file-upload/files/P&A%20Client%20Briefing%20-%20Income%20Tax%20Rates%202083-84%20(2026-27%20AD).pdf) table: "Gains from disposal of interest in an entity listed with SEBON by a resident natural person (ownership for more than 365 days) — 7.5%"

### 3. CGT Individual Short-term (≤365 days) — Finance Act 2080, Section 95A(2)
> **Source:** [IRD FAQ](https://ird.gov.np/faq/) (official)
> ```
> 10 प्रतिशत
> नेपाल धितोपत्र वोर्डमा सूचिकरण भएको निकायको हितको निसर्गबाट प्राप्त लाभ रकमको हकमा (अन्यको हकमा)
> ```
> Translation: "10% — on gain from disposal of interest in entity listed with SEBON (for others)."
> 
> **FY 2082/83:** 7.5% short-term per Finance Act 2080.
> **FY 2083/84:** 10% per Finance Act 2083.
> 
> **Confirmatory source:** [Pradhan Law briefing FY 2083/84](https://pradhanlaw.com/file-upload/files/P&A%20Client%20Briefing%20-%20Income%20Tax%20Rates%202083-84%20(2026-27%20AD).pdf) table: "Gains from disposal of interest in an entity listed with SEBON by resident natural person (ownership for less than 365 days) — 10%"

**Notes:**
- Current FY (2026-09-28) is FY 2083/84 (started 2026-07-17). Applicable rates per Finance Act 2083: **Long-term 7.5%, Short-term 10%** for individuals — **marked unverified** in DB until Finance Act 2083 PDF is confirmed.
- The 5%/7.5% rates in the seed table apply to FY 2082/83 (ended 2026-07-16). Both sets are retained in `fee_tax_rates` with `fiscal_year` column for historical accuracy.
- Short-term = holding period ≤ 365 days (day 365 = short, day 366 = long). Long-term = > 365 days.
- **Final withholding tax status:** Per Finance Act 2083 Section 95Ka, capital gains on listed shares are **final tax** if the taxpayer does not file an income tax return. If a return is filed, the gain is included in total income and taxed at slab rates. IRD FAQ confirms "final tax if no return filed" [link](https://ird.gov.np/faq/).
- STT 0.15% collected by NEPSE on sell side only (Finance Act 2080).
- DP Charge Rs 25 per demat transaction (CDS & Clearing).
- SEBON fee 0.015% and NEPSE fee 0.005% per Schedule 15 of SEBON directive.
- **Unverified rates** (Finance Act 2083 CGT): The primary gazette PDF for Finance Act 2083 (gazetted 2083.03.30) is not publicly accessible on ird.gov.np. Rates are sourced from IRD FAQ and Pradhan Law briefing (secondary). UI will show "unverified — needs human confirmation" until primary source is confirmed.