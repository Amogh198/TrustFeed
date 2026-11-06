import { Activity, ArrowRight, Eye } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import SpreadStage from '../graph/SpreadStage';
import { platformName, utc } from '../lib/format';
import { caseHref, go } from '../lib/route';
import type { NetworkPayload } from '../types';
import { Loading, Section, Tape, Unknown } from '../ui/ui';

// The demo dataset behind this page is the network of this replay case.
const DEMO_CASE = 'demo-001';

interface SpreadStep {
  platform: string;
  handle: string | null;
  first_seen_at: string;
  seconds_after_first: number;
}

interface AlertItem {
  campaign_id: string;
  platform_spread: string[];
  total_posts: number;
  risk_level: string;
  spread_steps?: SpreadStep[];
}

function after(seconds: number): string {
  return seconds < 90 ? `T+${Math.round(seconds)}s` : `T+${Math.round(seconds / 60)}m`;
}

export default function LiveMonitor() {
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [graph, setGraph] = useState<NetworkPayload | null>(null);
  const [loadingGraph, setLoadingGraph] = useState(true);
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
        setLastUpdated(new Date().toLocaleTimeString());
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

  useEffect(() => {
    let active = true;
    api.getNetwork(DEMO_CASE)
      .then((data) => {
        if (active) setGraph(data);
      })
      .catch(() => {
        if (active) setGraph(null);
      })
      .finally(() => {
        if (active) setLoadingGraph(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const openForensics = () => go(caseHref(DEMO_CASE, 'media'));
  const top = alerts[0];

  return (
    <div className="page page-watch">
      <header className="page-head">
        <span className="eyebrow"><Activity size={14} /> Threat radar replay</span>
        <h1>Monitoring feed</h1>
        <p>Groups posts that share a media hash or link across platforms, then replays how they spread. Everything here comes from the synthetic demo dataset.</p>
      </header>

      <Tape>DEMO DATA · NOT A LIVE FEED · SYNTHETIC POSTS</Tape>

      <p className="fineprint">
        Reads <code>/api/monitor/alerts</code> every 5 seconds.
        {lastUpdated && ` Last updated at ${lastUpdated}.`}
      </p>

      {error && <div className="problem" role="alert">{error}</div>}

      {top?.spread_steps && top.spread_steps.length > 0 && (
        <Section
          title="How the largest group spread"
          kind="observed"
          lead="The earliest post in this dataset on each platform. Earliest found doesn't mean the source, because earlier posts may exist outside this data."
        >
          <p className="fineprint mono">Group {top.campaign_id}</p>
          <ol className="spread-steps">
            {top.spread_steps.map((step, index) => (
              <li key={step.platform}>
                <strong>Step {index + 1}: {platformName(step.platform)} ({after(step.seconds_after_first)})</strong>
                <p>
                  Earliest found from <span className="mono">{step.handle || 'an unknown account'}</span> at {utc(step.first_seen_at)}.
                </p>
              </li>
            ))}
          </ol>
        </Section>
      )}

      <Section
        title="Spread replay"
        lead="Accounts appear in the order they posted. Point at a link to see why two accounts are connected, or select an account to open the demo case's media checks."
      >
        {loadingGraph ? (
          <Loading>Loading the spread graph…</Loading>
        ) : graph ? (
          <SpreadStage graph={graph} autoplay onNodeClick={openForensics} showLinkReasons />
        ) : (
          <Unknown title="Spread graph unavailable">The API did not return the demo network.</Unknown>
        )}
      </Section>

      <Section
        title="Demo review signals"
        lead={`${alerts.length} groups of posts to review. Each button opens the demo case that holds this dataset. A group is a signal to look closer, not proof of coordination.`}
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
                    <span>Platforms: {alert.platform_spread.map(platformName).join(', ') || 'Not reported'}</span>
                  </p>
                </div>
                <button type="button" className="button button-primary" onClick={openForensics}>
                  <Eye size={14} aria-hidden="true" /> Inspect forensics <ArrowRight size={14} aria-hidden="true" />
                </button>
              </article>
            ))}
          </div>
        )}
      </Section>
    </div>
  );
}
