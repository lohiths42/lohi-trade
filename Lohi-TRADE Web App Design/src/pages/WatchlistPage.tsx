import { Eye } from 'lucide-react';
import PageHeader from '../components/shared/PageHeader';
import { BentoCard } from '../components/shared/BentoCard';
import WatchlistSection from '../components/settings/WatchlistSection';
import AlertsSection from '../components/settings/AlertsSection';

export default function WatchlistPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        icon={<Eye size={16} />}
        title="Watchlist & Alerts"
        subtitle="Track symbols and manage P&L alert rules"
      />
      <BentoCard reveal>
        <div style={{ padding: 24 }}>
          <WatchlistSection />
        </div>
      </BentoCard>
      <BentoCard reveal>
        <div style={{ padding: 24 }}>
          <AlertsSection />
        </div>
      </BentoCard>
    </div>
  );
}
