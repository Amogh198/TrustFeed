import { Activity, AlertTriangle, ArrowRight } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { go } from '../lib/route';
import { Caveat, Loading, Section } from '../ui/ui';

interface AlertItem {
  campaign_id: string;
  platform_spread: string[];
  total_posts: number;
  risk_level: string;
}

export default function LiveMonitor() {
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  const fetchAlerts = async () => {
    try {
      const data = await api.getMonitorAlerts();
      setAlerts(data);
      setError('');
      setLastUpdated(new Date().toLocaleTimeString());
    } catch (err) {
      setError((err as Error).message || 'Failed to fetch active alerts');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAlerts();
    const timer = window.setInterval(fetchAlerts, 5000);
    return () => window.clearInterval(timer);
  }, []);

  const handleInvestigate = (campaignId: string) => {
    // Navigate to check page with campaign ID
    go('#/');
    window.sessionStorage.setItem('trustfeed_investigate_input', campaignId);
  };

  return (
    <div className="page page-watch">
      <header className="page-head">
        <span className="eyebrow"><Activity size={14} /> Threat Radar</span>
        <h1>Proactive Monitoring Feed</h1>
        <p>Continuous monitoring feed grouping social chatter into active disinformation campaigns by media hash and URL signatures.</p>
      </header>

      <Caveat>
        <strong>Simulated live feed from public platform trace dataset.</strong> Polling <code>/api/monitor/alerts</code> every 5 seconds.
        {lastUpdated && ` Last updated at ${lastUpdated}.`}
      </Caveat>

      {error && <div className="problem" role="alert"><AlertTriangle size={16} /> {error}</div>}

      <Section
        title="Active Campaigns"
        lead={`${alerts.length} campaigns detected across platform feeds.`}
      >
        {loading && alerts.length === 0 ? (
          <Loading>Checking active campaign alerts...</Loading>
        ) : (
          <div className="radar-feed-grid" style={{ display: 'grid', gap: '1rem' }}>
            {alerts.map((alert) => (
              <div
                key={alert.campaign_id}
                className="panel card"
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '1.25rem',
                  border: '1px solid var(--border)',
                  background: 'var(--panel)',
                }}
              >
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
                    <span className={`pill ${alert.risk_level === 'critical' || alert.risk_level === 'high' ? 'pill-high' : 'pill-slate'}`}>
                      {alert.risk_level.toUpperCase()}
                    </span>
                    <strong style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: '0.95rem' }}>
                      {alert.campaign_id}
                    </strong>
                  </div>
                  <div style={{ fontSize: '0.85rem', color: 'var(--muted)' }}>
                    <span>Total Posts: <strong>{alert.total_posts}</strong></span>
                    <span style={{ margin: '0 0.5rem' }}>•</span>
                    <span>Platforms: <strong>{alert.platform_spread.join(', ')}</strong></span>
                  </div>
                </div>
                <button
                  type="button"
                  className="button button-primary"
                  onClick={() => handleInvestigate(alert.campaign_id)}
                >
                  Investigate Campaign <ArrowRight size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}
