/* App root: providers, router and page routing.
 *
 * react-query owns all server state here. The older hand-rolled
 * `usePolling`/`useFetch` hooks are superseded: they had no cache, no
 * deduplication and no way to invalidate a query after a mutation (the backfill
 * button needs exactly that).
 */

import { BrowserRouter, Navigate, Route, Routes, useSearchParams } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect } from "react";
import { AppShell } from "./components/AppShell";
import { AuthProvider, useAuth } from "./auth";
import { MarketPage } from "./pages/MarketPage";
import { MoversPage, StocksPage } from "./pages/StocksPage";
import { ArchivePage } from "./pages/ArchivePage";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { SecuritiesPage } from "./pages/SecuritiesPage";
import { BrokersPage } from "./pages/BrokersPage";
import { FundsPage } from "./pages/FundsPage";
import { SignInPage } from "./pages/SignInPage";
import { MarketMapPage } from "./pages/MarketMapPage";
import { ScreenerPage } from "./pages/ScreenerPage";
import { CompanyPage } from "./pages/CompanyPage";
import { DividendAnalysisPage } from "./pages/DividendAnalysisPage";
import { CorporateActionsPage } from "./pages/CorporateActionsPage";
import { PortfolioPage } from "./pages/PortfolioPage";
import { WatchlistPage } from "./pages/WatchlistPage";
import { AlertsPage } from "./pages/AlertsPage";
import { CalculatorPage } from "./pages/CalculatorPage";
import { NewsPage } from "./pages/NewsPage";
import { QuarterlyPage } from "./pages/QuarterlyPage";
import { AIPage } from "./pages/AIPage";
import { useTheme } from "./theme";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // NEPSE is polled, not pushed, and the backend caches briefly, so a
      // short stale time avoids hammering it without making the UI feel stale.
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <ThemeSync />
          <AppShell>
            <Routes>
              <Route path="/" element={<MarketPage />} />
              <Route path="/movers" element={<MoversPage />} />
              <Route path="/stocks" element={<StocksPage />} />
              <Route path="/archive" element={<ArchivePage />} />
              <Route path="/map" element={<MarketMapPage />} />
              <Route path="/screener" element={<ScreenerPage />} />
              {/* `/chart/:symbol` is the company + technical page (STEP 2c). */}
              <Route path="/chart/:symbol" element={<CompanyPage />} />
              <Route path="/analytics" element={<AnalyticsWithSymbol />} />
              <Route path="/dividends" element={<DividendAnalysisPage />} />
              <Route path="/corporate-actions" element={<CorporateActionsPage />} />
              <Route path="/securities" element={<SecuritiesPage />} />
              <Route path="/brokers" element={<BrokersPage />} />
              <Route path="/funds" element={<FundsPage />} />
              <Route path="/signin" element={<SignInPage />} />
              {/* Phase 4: Personal Tools */}
              <Route path="/portfolio" element={<PortfolioPage />} />
              <Route path="/watchlist" element={<WatchlistPage />} />
              <Route path="/alerts" element={<AlertsPage />} />
              <Route path="/calculator" element={<CalculatorPage />} />
              <Route path="/news" element={<NewsPage />} />
              <Route path="/quarterly" element={<QuarterlyPage />} />
              {/* Phase 5: AI */}
              <Route path="/ai" element={<AIPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </AppShell>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

/** Keep the theme attribute in sync and persist the choice to the profile. */
function ThemeSync() {
  const { preference, setPreference } = useTheme();
  const { user, saveTheme } = useAuth();

  useEffect(() => {
    if (user) void saveTheme(preference);
  }, [user, preference, saveTheme]);

  // Adopt the profile's stored theme once, on first load after sign-in.
  useEffect(() => {
    if (user?.theme && user.theme !== preference) setPreference(user.theme as typeof preference);
    // Intentionally runs only when the user identity changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id, user?.theme]);

  return null;
}

/** Let `/analytics?symbol=NABIL` deep-link from the movers and stock tables. */
function AnalyticsWithSymbol() {
  const [params] = useSearchParams();
  const symbol = params.get("symbol");
  return <AnalyticsPage initialSymbol={symbol ?? undefined} />;
}
