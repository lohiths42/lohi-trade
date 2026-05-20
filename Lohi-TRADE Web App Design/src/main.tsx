import { lazy, Suspense } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import ErrorBoundary from './components/shared/ErrorBoundary';
import { ThemeProvider } from './lib/theme-provider';
import { useAuthStore } from './stores/auth-store';
import './index.css';
import './styles/design-tokens.css';
import './styles/research-theme.css';

// Lazy-loaded pages for code splitting — only active route code is loaded
const LoginPage = lazy(() => import('./pages/LoginPage'));
const TwoFactorPage = lazy(() => import('./pages/TwoFactorPage'));
const SetupWizardPage = lazy(() => import('./pages/SetupWizardPage'));
const OnboardingPage = lazy(() => import('./pages/OnboardingPage'));
const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const TradePage = lazy(() => import('./pages/TradePage'));
const PositionsPage = lazy(() => import('./pages/PositionsPage'));
const OrdersPage = lazy(() => import('./pages/OrdersPage'));
const StrategiesPage = lazy(() => import('./pages/StrategiesPage'));
const AlgoPerformancePage = lazy(() => import('./pages/AlgoPerformancePage'));
const HistoryPage = lazy(() => import('./pages/HistoryPage'));
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage'));
const CommanderPage = lazy(() => import('./pages/CommanderPage'));
const SoldierPage = lazy(() => import('./pages/SoldierPage'));
const BacktestPage = lazy(() => import('./pages/BacktestPage'));
const BacktestNewPage = lazy(() => import('./pages/BacktestNewPage'));
const BacktestResultPage = lazy(() => import('./pages/BacktestResultPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const RiskSettingsPage = lazy(() => import('./pages/RiskSettingsPage'));
const NotificationsPage = lazy(() => import('./pages/NotificationsPage'));
const ProfilePage = lazy(() => import('./pages/ProfilePage'));
const LogsPage = lazy(() => import('./pages/LogsPage'));
const MarketDataPage = lazy(() => import('./pages/MarketDataPage'));
const StatusPage = lazy(() => import('./pages/StatusPage'));
const HelpPage = lazy(() => import('./pages/HelpPage'));
const StockUniversePage = lazy(() => import('./pages/StockUniversePage'));
const ScreenerPage = lazy(() => import('./pages/ScreenerPage'));
const StockDetailPage = lazy(() => import('./pages/StockDetailPage'));
const VerificationPage = lazy(() => import('./pages/VerificationPage'));
const BankAccountPage = lazy(() => import('./pages/BankAccountPage'));
const FundTransactionsPage = lazy(() => import('./pages/FundTransactionsPage'));
const BrokerSettingsPage = lazy(() => import('./pages/BrokerSettingsPage'));
const WatchlistPage = lazy(() => import('./pages/WatchlistPage'));
const CreateAccountPage = lazy(() => import('./pages/CreateAccountPage'));
const LandingPage = lazy(() => import('./pages/LandingPage'));

// Lohi-Research pages — mounted under /research/* via the dedicated
// ResearchShell layout. The shell flips the surface tokens so the tree
// picks up the Quartr-inspired editorial palette from research-theme.css.
const ResearchShell = lazy(() => import('./components/research/ResearchShell'));
const ResearchDashboardPage = lazy(() => import('./pages/research/ResearchDashboardPage'));
const ResearchChatPage = lazy(() => import('./pages/research/ResearchChatPage'));
const ResearchSymbolPage = lazy(() => import('./pages/research/ResearchSymbolPage'));
const ResearchIdeasPage = lazy(() => import('./pages/research/ResearchIdeasPage'));
const ResearchThemesPage = lazy(() => import('./pages/research/ResearchThemesPage'));
const ResearchSectorsPage = lazy(() => import('./pages/research/ResearchSectorsPage'));
const ResearchCoveragePage = lazy(() => import('./pages/research/ResearchCoveragePage'));
const ResearchBriefsPage = lazy(() => import('./pages/research/ResearchBriefsPage'));
const ResearchFilingsPage = lazy(() => import('./pages/research/ResearchFilingsPage'));
const ResearchFilingsUploadPage = lazy(() => import('./pages/research/ResearchFilingsUploadPage'));
const ResearchPolicyPage = lazy(() => import('./pages/research/ResearchPolicyPage'));
const ResearchArchitecturePage = lazy(() => import('./pages/research/ResearchArchitecturePage'));
const ArchitecturePage = lazy(() => import('./pages/ArchitecturePage'));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
});

function PageLoader() {
  return (
    <div className="flex items-center justify-center h-64">
      <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
    </div>
  );
}

/** Route guard — redirects to /welcome if not authenticated. */
function RequireAuth({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  if (!isAuthenticated) {
    return <Navigate to="/welcome" replace />;
  }
  return <>{children}</>;
}

/** Redirect authenticated users away from login. */
function GuestOnly({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}

createRoot(document.getElementById('root')!).render(
  <ThemeProvider>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Suspense fallback={<PageLoader />}>
          <Routes>
          <Route path="/welcome" element={<LandingPage />} />
          <Route path="/login" element={<GuestOnly><LoginPage /></GuestOnly>} />
          <Route path="/login/2fa" element={<GuestOnly><TwoFactorPage /></GuestOnly>} />
          <Route path="/setup" element={<SetupWizardPage />} />
          <Route path="/onboarding" element={<OnboardingPage />} />
          <Route path="/create-account" element={<GuestOnly><CreateAccountPage /></GuestOnly>} />
          <Route element={<RequireAuth><App /></RequireAuth>}>
            <Route index element={<ErrorBoundary><DashboardPage /></ErrorBoundary>} />
            <Route path="trade" element={<ErrorBoundary><TradePage /></ErrorBoundary>} />
            <Route path="positions" element={<ErrorBoundary><PositionsPage /></ErrorBoundary>} />
            <Route path="orders" element={<ErrorBoundary><OrdersPage /></ErrorBoundary>} />
            <Route path="strategies" element={<ErrorBoundary><StrategiesPage /></ErrorBoundary>} />
            <Route path="strategies/soldier/:id" element={<ErrorBoundary><SoldierPage /></ErrorBoundary>} />
            <Route path="strategies/commander/:id" element={<ErrorBoundary><CommanderPage /></ErrorBoundary>} />
            <Route path="algo-performance" element={<ErrorBoundary><AlgoPerformancePage /></ErrorBoundary>} />
            <Route path="history" element={<ErrorBoundary><HistoryPage /></ErrorBoundary>} />
            <Route path="analytics" element={<ErrorBoundary><AnalyticsPage /></ErrorBoundary>} />
            <Route path="audit" element={<ErrorBoundary><LogsPage /></ErrorBoundary>} />
            <Route path="commander" element={<ErrorBoundary><CommanderPage /></ErrorBoundary>} />
            <Route path="soldier" element={<ErrorBoundary><SoldierPage /></ErrorBoundary>} />
            <Route path="backtest" element={<ErrorBoundary><BacktestPage /></ErrorBoundary>} />
            <Route path="backtest/new" element={<ErrorBoundary><BacktestNewPage /></ErrorBoundary>} />
            <Route path="backtest/:run_id" element={<ErrorBoundary><BacktestResultPage /></ErrorBoundary>} />
            <Route path="settings" element={<ErrorBoundary><SettingsPage /></ErrorBoundary>} />
            <Route path="settings/risk" element={<ErrorBoundary><RiskSettingsPage /></ErrorBoundary>} />
            <Route path="settings/brokers" element={<ErrorBoundary><BrokerSettingsPage /></ErrorBoundary>} />
            <Route path="settings/notifications" element={<ErrorBoundary><NotificationsPage /></ErrorBoundary>} />
            <Route path="settings/profile" element={<ErrorBoundary><ProfilePage /></ErrorBoundary>} />
            <Route path="logs" element={<ErrorBoundary><LogsPage /></ErrorBoundary>} />
            <Route path="market-data" element={<ErrorBoundary><MarketDataPage /></ErrorBoundary>} />
            <Route path="status" element={<ErrorBoundary><StatusPage /></ErrorBoundary>} />
            <Route path="help" element={<ErrorBoundary><HelpPage /></ErrorBoundary>} />
            <Route path="universe" element={<ErrorBoundary><StockUniversePage /></ErrorBoundary>} />
            <Route path="screener" element={<ErrorBoundary><ScreenerPage /></ErrorBoundary>} />
            <Route path="stocks/:symbol" element={<ErrorBoundary><StockDetailPage /></ErrorBoundary>} />
            <Route path="verification" element={<ErrorBoundary><VerificationPage /></ErrorBoundary>} />
            <Route path="bank" element={<ErrorBoundary><BankAccountPage /></ErrorBoundary>} />
            <Route path="funds" element={<ErrorBoundary><FundTransactionsPage /></ErrorBoundary>} />
            <Route path="watchlist" element={<ErrorBoundary><WatchlistPage /></ErrorBoundary>} />
            <Route path="architecture" element={<ErrorBoundary><ArchitecturePage /></ErrorBoundary>} />
          </Route>
          {/* Lohi-Research — dedicated shell, distinct identity. Flips the
              <html data-surface> attribute via `mode-store` so the
              editorial Quartr-inspired tokens in research-theme.css take
              over for the whole tree. */}
          <Route element={<RequireAuth><ResearchShell /></RequireAuth>}>
            <Route path="research" element={<ErrorBoundary><ResearchDashboardPage /></ErrorBoundary>} />
            <Route path="research/ideas" element={<ErrorBoundary><ResearchIdeasPage /></ErrorBoundary>} />
            <Route path="research/themes" element={<ErrorBoundary><ResearchThemesPage /></ErrorBoundary>} />
            <Route path="research/sectors" element={<ErrorBoundary><ResearchSectorsPage /></ErrorBoundary>} />
            <Route path="research/coverage" element={<ErrorBoundary><ResearchCoveragePage /></ErrorBoundary>} />
            <Route path="research/briefs" element={<ErrorBoundary><ResearchBriefsPage /></ErrorBoundary>} />
            <Route path="research/filings" element={<ErrorBoundary><ResearchFilingsPage /></ErrorBoundary>} />
            <Route path="research/filings/upload" element={<ErrorBoundary><ResearchFilingsUploadPage /></ErrorBoundary>} />
            <Route path="research/policy" element={<ErrorBoundary><ResearchPolicyPage /></ErrorBoundary>} />
            <Route path="research/architecture" element={<ErrorBoundary><ResearchArchitecturePage /></ErrorBoundary>} />
            <Route path="research/chat" element={<ErrorBoundary><ResearchChatPage /></ErrorBoundary>} />
            <Route path="research/:symbol" element={<ErrorBoundary><ResearchSymbolPage /></ErrorBoundary>} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  </QueryClientProvider>
  </ThemeProvider>,
);
