import { Activity, ArrowRight } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import { go } from '../lib/route';
import { Loading, Section, Tape, Unknown } from '../ui/ui';

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
  const inFlight = useRef(false);

  useEffect(() => {
    let active = true;
    const fetchAlerts = async () => {
      if (inFlight.current) return;
      inFlight.current = true;
      try {
        const data = await api.getMonitorAlerts();
        if (!active) return;
        setAlerts(data);
        setError('');
      } catch (err) {
        if (active) setError((err as Error).message || 'Could not load the demo review signals.');
      } finally {
        inFlight.current = false;
        if (active) setLoading(false);
      }
    };
    void fetchAlerts();
    const timer = window.setInterval(() => void fetchAlerts(), 5000);
    return () => {
      active = false;
      inFlight.current = false;
      window.clearInterval(timer);
    };
  }, []);

  const handleInvestigate = (campaignId: string) => {
    window.sessionStorage.setItem('trustfeed_investigate_input', campaignId);
    go('#/');
  };

  return (
    <div className="page page-watch">
      <header className="page-head">
        <span className="eyebrow"><Activity size={14} /> Replay monitor</span>
        <h1>Review signals</h1>
        <p>Groups of posts sharing a link or media hash, served from the synthetic demo dataset.</p>
      </header>

      <Tape>DEMO DATA · NOT A LIVE FEED · SYNTHETIC POSTS</Tape>

      {error && <div className="problem" role="alert">{error}</div>}

      <Section
        title="Demo review signals"
        lead="This endpoint reads the bundled demo dataset. It does not monitor live platform activity."
      >
        {loading && alerts.length === 0 ? (
          <Loading>Loading demo review signals from the API…</Loading>
        ) : alerts.length === 0 ? (
          <Unknown title="No review signals in this demo dataset">The API returned no groups to review.</Unknown>
        ) : (
          <div className="radar-feed-grid">
            {alerts.map((alert) => (
              <article key={alert.campaign_id} className="panel card radar-feed-card">
                <div className="radar-feed-details">
                  <div className="radar-feed-title">
                    <span className={`pill ${alert.risk_level === 'critical' || alert.risk_level === 'high' ? 'pill-high' : 'pill-slate'}`}>
                      Review signal · {alert.risk_level}
                    </span>
                    <strong className="radar-feed-id mono">{alert.campaign_id}</strong>
                  </div>
                  <p className="radar-feed-meta">
                    <span>{alert.total_posts} posts in this group</span>
                    <span>Platforms: {alert.platform_spread.join(', ') || 'Not reported'}</span>
                  </p>
                </div>
                <button
                  type="button"
                  className="button button-primary"
                  onClick={() => handleInvestigate(alert.campaign_id)}
                >
                  Investigate group <ArrowRight size={14} />
                </button>
              </article>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}
