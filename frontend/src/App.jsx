import React, { useEffect, useMemo, useState } from 'react';
import {
  Activity, AlertTriangle, ArrowRight, ArrowUpRight,
  BadgeCheck, Bell, ChevronDown, CircleHelp, Clock3, Copy, Download,
  FileCheck2, FileImage, FileSearch, Filter, Fingerprint,
  Globe2, Layers3, Link2, LoaderCircle, Menu, MessageSquareText, Network, Plus,
  Radio, Search, Shield, Sparkles, Upload, X,
} from 'lucide-react';
import { recentCases, replayCase } from './fixtures.js';
import './manas.css';

const tabs = [
  { id: 'overview', label: 'Overview', icon: Layers3 },
  { id: 'investigate', label: 'Investigate', icon: FileSearch },
  { id: 'monitor', label: 'Live Monitor', icon: Activity },
  { id: 'network', label: 'Spread analysis', icon: Network },
  { id: 'history', label: 'Case history', icon: Clock3 },
];

function Brand() {
  return (
    <div className="brand">
      <span className="brand-mark"><Shield size={18} strokeWidth={2.4} /><i /></span>
      <span>trustfeed<span className="brand-period">.</span></span>
    </div>
  );
}

function RiskPill({ value, small = false }) {
  const cls = String(value || 'low').toLowerCase().replaceAll(' ', '-');
  return <span className={`risk-pill risk-${cls} ${small ? 'small' : ''}`}><i />{value}</span>;
}

function Header({ view, onView, replay, setReplay }) {
  const [menuOpen, setMenuOpen] = useState(false);
  return (
    <>
      <header className="topbar">
        <div className="top-left">
          <button className="icon-button mobile-menu" aria-label="Open navigation" onClick={() => setMenuOpen(!menuOpen)}>
            <Menu size={19} />
          </button>
          <Brand />
          <span className="top-divider" />
          <span className="workspace-name">Investigation workspace <ChevronDown size={14} /></span>
        </div>
        <div className="top-right">
          <span className={`connection ${replay ? 'offline' : ''}`}>
            <i />{replay ? 'Offline replay' : 'Workspace ready'}
          </span>
          <button className="icon-button notification" aria-label="Notifications">
            <Bell size={17} /><b />
          </button>
          <div className="avatar">AM</div>
        </div>
      </header>
      <aside className={`sidebar ${menuOpen ? 'open' : ''}`}>
        <div className="sidebar-label">WORKSPACE</div>
        <nav>
          {tabs.map(({ id, label, icon: Icon }) => (
            <button key={id} onClick={() => { onView(id); setMenuOpen(false); }} className={`nav-item ${view === id ? 'active' : ''}`}>
              <Icon size={17} />
              <span>{label}</span>
              {id === 'history' && <em>12</em>}
            </button>
          ))}
        </nav>
        <div className="sidebar-separator" />
        <div className="sidebar-label case-label">
          RECENT CASES <button aria-label="Search cases"><Search size={14} /></button>
        </div>
        <div className="sidebar-cases">
          {recentCases.map((item, i) => (
            <button className={`side-case ${i === 0 ? 'selected' : ''}`} key={item.id} onClick={() => onView('overview')}>
              <span className={`case-dot dot-${item.risk.toLowerCase()}`} />
              <span className="side-case-copy">
                <strong>{item.title}</strong>
                <small>{item.id} · {item.time}</small>
              </span>
            </button>
          ))}
        </div>
        <button className="new-case" onClick={() => onView('investigate')}>
          <Plus size={16} /> New investigation
        </button>
        <div className="sidebar-spacer" />
        <div className="sidebar-bottom">
          <button className="nav-item"><CircleHelp size={17} /><span>Help & documentation</span></button>
          <div className="profile-row">
            <div className="avatar profile-avatar">AM</div>
            <div><strong>Amogh M.</strong><small>Analyst workspace</small></div>
            <MoreDots />
          </div>
        </div>
      </aside>
    </>
  );
}

function MoreDots() {
  return <button className="dots-button" aria-label="More options"><span>•••</span></button>;
}

function PageHeading({ eyebrow, title, description, children }) {
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {children && <div className="heading-actions">{children}</div>}
    </div>
  );
}

function StatCard({ label, value, note, icon: Icon, accent, trend }) {
  return (
    <article className="stat-card">
      <div className="stat-top">
        <span>{label}</span>
        <span className={`stat-icon ${accent}`}><Icon size={16} /></span>
      </div>
      <div className="stat-value">{value}</div>
      <div className="stat-note">{trend && <span className="trend"><ArrowUpRight size={13} />{trend}</span>}{note}</div>
    </article>
  );
}

function Overview({ onView, replay }) {
  return (
    <>
      <PageHeading eyebrow="THURSDAY, NOVEMBER 5, 2026" title="Good morning, Amogh" description="A clear view of the signals that need your attention.">
        <button className="button button-secondary" onClick={() => onView('history')}><Clock3 size={15} /> View all cases</button>
        <button className="button button-primary" onClick={() => onView('investigate')}><Plus size={16} /> New investigation</button>
      </PageHeading>
      <div className="replay-banner">
        <span className="replay-icon"><Radio size={16} /></span>
        <div>
          <strong>{replay ? 'Replay mode is active' : 'Replay mode available'}</strong>
          <span>{replay ? 'This workspace is showing deterministic sample data. No live feeds or models are connected.' : 'Explore a complete sample investigation without connecting live models.'}</span>
        </div>
        <button onClick={() => onView('investigate')}>Start investigation <ArrowRight size={14} /></button>
      </div>
      <section className="stats-grid">
        <StatCard label="Triage cases" value="12" note="4 require human review" icon={FileSearch} accent="violet" trend="+3" />
        <StatCard label="Media manipulation signals" value="18" note="Elevated diffusion indicators" icon={Fingerprint} accent="amber" />
        <StatCard label="Public-post traces" value="5" note="Mastodon, Lemmy, HN, Bluesky" icon={Globe2} accent="blue" />
        <StatCard label="Network coordination" value="78%" note="Cluster cohesion signal" icon={Network} accent="green" trend="+12%" />
      </section>
      <div className="overview-split">
        <section className="panel case-preview-panel">
          <div className="panel-heading">
            <div><h3>Active investigation</h3><p>Highest-priority case in the current queue</p></div>
            <RiskPill value={replayCase.risk} />
          </div>
          <div className="case-card-body">
            <span className="case-id-tag">{replayCase.id}</span>
            <h4>{replayCase.title}</h4>
            <p className="case-snippet">{replayCase.submitted}</p>
            <div className="signal-pills">
              {replayCase.modules.map(m => (
                <span key={m.key} className="signal-pill">
                  <BadgeCheck size={13} />{m.label}: <strong>{m.status}</strong>
                </span>
              ))}
            </div>
          </div>
          <div className="case-card-foot">
            <span>Source: <strong>{replayCase.source}</strong></span>
            <button className="button button-primary" onClick={() => onView('case')}>Open case file <ArrowRight size={14} /></button>
          </div>
        </section>
        <section className="panel actions-panel">
          <div className="panel-heading"><div><h3>Recommended actions</h3><p>Based on observed indicators</p></div></div>
          <ul className="action-list">
            <li><span className="action-bullet amber" /><div><strong>Review coordinated spread candidate</strong><p>18 accounts posted similar captions within 120 seconds.</p></div><button className="icon-button" onClick={() => onView('network')}><ArrowRight size={14} /></button></li>
            <li><span className="action-bullet blue" /><div><strong>Extract and atomize claim units</strong><p>Isolate verifiable factual statements from sentiment.</p></div><button className="icon-button" onClick={() => onView('investigate')}><ArrowRight size={14} /></button></li>
            <li><span className="action-bullet green" /><div><strong>Export evidence record for platform review</strong><p>Generate audit-ready JSON payload with provenance references.</p></div><button className="icon-button" onClick={() => onView('case')}><ArrowRight size={14} /></button></li>
          </ul>
        </section>
      </div>
    </>
  );
}

function LiveMonitor({ onInvestigateCampaign }) {
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [lastUpdated, setLastUpdated] = useState(null);

  const fetchAlerts = async () => {
    try {
      const response = await fetch('http://localhost:8000/api/monitor/alerts');
      if (!response.ok) {
        throw new Error(`Failed to fetch alerts (${response.status})`);
      }
      const data = await response.json();
      setAlerts(data);
      setError('');
      setLastUpdated(new Date().toLocaleTimeString());
    } catch (err) {
      setError(err.message || 'Error fetching active campaign alerts');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAlerts();
    const interval = setInterval(fetchAlerts, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <>
      <PageHeading
        eyebrow="LIVE THREAT RADAR"
        title="Proactive Monitoring Feed"
        description="Continuous proactive monitoring of public platform chatter, coordinated spread, and synthetic media campaigns."
      >
        <button className="button button-secondary" onClick={fetchAlerts}>
          <Activity size={15} /> Refresh feed
        </button>
      </PageHeading>

      <div className="replay-banner">
        <span className="replay-icon"><Radio size={16} /></span>
        <div>
          <strong>Live Threat Radar Active</strong>
          <span>
            {lastUpdated ? `Last updated: ${lastUpdated} · ` : ''}
            Polling http://localhost:8000/api/monitor/alerts for active disinformation campaigns.
          </span>
        </div>
      </div>

      <section className="panel threat-radar-panel">
        <div className="panel-heading">
          <div>
            <h3>Active Disinformation Campaigns</h3>
            <p>Grouped by media hash & URL signatures to detect coordinated viral spread</p>
          </div>
          {loading && <span className="secure-note"><LoaderCircle className="spin" size={13} /> Updating radar...</span>}
        </div>

        {error && <div className="form-notice" role="alert"><AlertTriangle size={14} />{error}</div>}

        <div className="radar-alerts-list" style={{ display: 'flex', flexDirection: 'column', gap: '1rem', marginTop: '1rem' }}>
          {alerts.map((alert) => (
            <div
              key={alert.campaign_id}
              className="alert-card"
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '1.1rem 1.25rem',
                borderRadius: '8px',
                border: '1px solid rgba(255, 255, 255, 0.08)',
                background: 'rgba(255, 255, 255, 0.03)',
              }}
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', maxWidth: '75%' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <RiskPill value={alert.risk_level.toUpperCase()} small />
                  <strong style={{ fontSize: '0.95rem', fontFamily: 'monospace', color: '#f3f2ff' }}>
                    {alert.campaign_id.length > 55 ? `${alert.campaign_id.slice(0, 55)}...` : alert.campaign_id}
                  </strong>
                </div>
                <div style={{ fontSize: '0.84rem', color: '#9d98be' }}>
                  <span>Total Posts: <strong style={{ color: '#fff' }}>{alert.total_posts}</strong></span>
                  <span style={{ margin: '0 0.5rem' }}>·</span>
                  <span>
                    Platform Spread:{' '}
                    <strong style={{ color: '#eef25a' }}>
                      {Array.isArray(alert.platform_spread)
                        ? alert.platform_spread.join(', ')
                        : alert.platform_spread}
                    </strong>
                  </span>
                </div>
              </div>
              <button
                className="button button-primary"
                onClick={() => onInvestigateCampaign(alert.campaign_id)}
                style={{ whiteSpace: 'nowrap' }}
              >
                Investigate Campaign <ArrowRight size={14} />
              </button>
            </div>
          ))}
          {alerts.length === 0 && !loading && !error && (
            <div style={{ padding: '2rem', textAlign: 'center', color: '#8d89a5' }}>
              No active threat campaigns detected.
            </div>
          )}
        </div>
      </section>
    </>
  );
}

function Investigate({ onOpenCase, initialInput = '', initialMode = 'text' }) {
  const [input, setInput] = useState(initialInput);
  const [mode, setMode] = useState(initialMode);
  const [file, setFile] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [notice, setNotice] = useState('');
  const [webSearchConsent, setWebSearchConsent] = useState(false);
  const [isPreparing, setIsPreparing] = useState(false);

  useEffect(() => {
    if (initialInput) {
      setInput(initialInput);
      setMode(initialInput.startsWith('http') ? 'url' : 'text');
    }
  }, [initialInput]);

  const openDemo = () => {
    setInput(replayCase.submitted);
    setNotice('Sample text loaded. Ready to run live analysis.');
  };

  const selectMedia = (e) => {
    const chosen = e?.target?.files?.[0] || e;
    if (chosen) {
      setFile(chosen);
      setNotice(`File selected: ${chosen.name} (${Math.round(chosen.size / 1024)} KB)`);
    }
  };

  const submit = async (event) => {
    event.preventDefault();
    if (isPreparing) return;
    if (mode !== 'media' && !input.trim()) {
      setNotice('Add text or a URL to prepare a case.');
      return;
    }
    if (mode === 'media' && !file) {
      setNotice('Choose an image or video before preparing a media case.');
      return;
    }

    setIsPreparing(true);
    setNotice('Connecting to backend API at http://localhost:8000...');

    try {
      let response;
      if (mode === 'media') {
        const formData = new FormData();
        formData.append('file', file);
        if (input.trim()) formData.append('text', input.trim());
        formData.append('search_web', String(webSearchConsent));
        response = await fetch('http://localhost:8000/api/cases/media', {
          method: 'POST',
          body: formData,
        });
      } else {
        const body = {
          text: mode === 'text' ? input.trim() : null,
          url: mode === 'url' ? input.trim() : null,
          search_web: webSearchConsent,
        };
        response = await fetch('http://localhost:8000/api/cases/analyze', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
      }

      if (!response.ok) {
        const errJson = await response.json().catch(() => null);
        const detail = errJson?.detail;
        const msg = typeof detail === 'string' ? detail : detail?.message || `API error (${response.status})`;
        throw new Error(msg);
      }

      const caseData = await response.json();
      setNotice('');
      onOpenCase(caseData);
    } catch (err) {
      setNotice(`Investigation failed: ${err.message}`);
    } finally {
      setIsPreparing(false);
    }
  };

  return (
    <>
      <PageHeading eyebrow="NEW CASE" title="Start an investigation" description="Inspect a claim, URL, or media item. Each result keeps evidence and uncertainty visible." />
      <div className="investigate-grid">
        <section className="panel intake-panel">
          <div className="panel-heading">
            <div>
              <h3>What would you like to check?</h3>
              <p>Choose an input type, then add the content for review.</p>
            </div>
            <span className="secure-note"><Shield size={13} /> Live API connected</span>
          </div>
          <div className="input-tabs">
            {[
              ['text', MessageSquareText, 'Text or claim'],
              ['url', Globe2, 'URL'],
              ['media', FileImage, 'Image or video'],
            ].map(([key, Icon, label]) => (
              <button
                type="button"
                className={mode === key ? 'selected' : ''}
                key={key}
                onClick={() => { setMode(key); setNotice(''); }}
              >
                <Icon size={15} />{label}
              </button>
            ))}
          </div>
          <form onSubmit={submit}>
            {mode === 'media' ? (
              <>
                <div
                  className={`dropzone ${dragging ? 'dragging' : ''}`}
                  onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(e) => { e.preventDefault(); setDragging(false); selectMedia(e.dataTransfer?.files?.[0]); }}
                >
                  <span className="upload-icon"><Upload size={20} /></span>
                  <strong>{file ? `Selected: ${file.name}` : 'Drop a file here, or browse'}</strong>
                  <span>JPG, PNG, WebP or MP4 · Up to 25 MB</span>
                  <label className="button button-secondary browse-button">
                    Browse files
                    <input type="file" accept="image/jpeg,image/png,image/webp,video/mp4" onChange={selectMedia} />
                  </label>
                </div>
                <label className="consent-card">
                  <input type="checkbox" checked={webSearchConsent} onChange={(e) => setWebSearchConsent(e.target.checked)} />
                  <span>
                    <strong>Allow public platform search</strong>
                    <small>Optional. Checks whether this content or URL appeared on connected public platforms.</small>
                  </span>
                </label>
              </>
            ) : (
              <label className="content-field">
                <span>{mode === 'url' ? 'URL to inspect' : 'Content to inspect'}</span>
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  aria-invalid={Boolean(notice && !input.trim())}
                  placeholder={mode === 'url' ? 'Paste a link to a post, article, or website…' : 'Paste a claim, forwarded message, social post, or caption…'}
                  rows={8}
                />
                <span className="field-foot">
                  <span>{input.length} characters</span>
                  <button type="button" className="inline-action" onClick={openDemo}><Sparkles size={13} /> Use sample</button>
                </span>
              </label>
            )}
            {notice && <div className="form-notice" aria-live="polite"><CircleHelp size={14} />{notice}</div>}
            <div className="form-bottom">
              <div className="privacy-copy"><Shield size={14} /> Real-time detection against fake media & scams.</div>
              <button className="button button-primary" type="submit" disabled={isPreparing}>
                {isPreparing ? <LoaderCircle className="spin" size={15} /> : <FileSearch size={15} />}
                {isPreparing ? 'Analyzing with API…' : 'Run Live Analysis'} {!isPreparing && <ArrowRight size={14} />}
              </button>
            </div>
          </form>
        </section>
        <aside className="panel scope-panel">
          <div className="panel-heading"><div><h3>What the analysis shows</h3><p>Signals are leads for review, not proof.</p></div></div>
          <div className="scope-list">
            <div><span className="scope-icon violet"><FileSearch size={15} /></span><div><strong>Claim & language signals</strong><p>Urgency, scam patterns, and claim context.</p></div></div>
            <div><span className="scope-icon green"><Fingerprint size={15} /></span><div><strong>Media indicators</strong><p>Metadata, manipulation signals, and provenance when available.</p></div></div>
            <div><span className="scope-icon amber"><Network size={15} /></span><div><strong>Spread patterns</strong><p>Timing and repeated content in the provided dataset.</p></div></div>
          </div>
          <div className="scope-foot">
            <span className="signal-legend"><i className="legend-evidence" /> Evidence</span>
            <span className="signal-legend"><i className="legend-estimate" /> Estimate</span>
            <span className="signal-legend"><i className="legend-unknown" /> Unknown</span>
          </div>
        </aside>
      </div>
      <section className="replay-cta">
        <div className="replay-cta-icon"><Radio size={18} /></div>
        <div>
          <strong>Need a reliable offline demo?</strong>
          <span>Open the deterministic sample case to explore the report, spread graph, and timeline offline.</span>
        </div>
        <button className="button button-secondary" onClick={() => onOpenCase(replayCase)}>
          Open replay case <ArrowRight size={14} />
        </button>
      </section>
    </>
  );
}

function CaseDetail({ data, onBack }) {
  const [selectedNode, setSelectedNode] = useState('origin');
  const [progress, setProgress] = useState(100);
  const [copied, setCopied] = useState(false);
  const selected = replayCase.nodes.find(n => n.id === selectedNode) || replayCase.nodes[0];
  const copySummary = async () => {
    try {
      await navigator.clipboard.writeText(data.summary);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  return (
    <>
      <div className="breadcrumb">
        <button onClick={onBack}>Investigations</button>
        <span>/</span>
        <span>{data.id}</span>
        <span className="replay-chip"><Radio size={12} /> {data.is_replay ? 'REPLAY' : 'LIVE CASE'}</span>
      </div>
      <div className="case-title-row">
        <div>
          <div className="case-kicker">CASE {data.id} <span>·</span> {data.time}</div>
          <h1>{data.title}</h1>
          <p className="case-source"><MessageSquareText size={14} /> {data.source}</p>
        </div>
        <div className="case-actions">
          <button className="button button-secondary" onClick={copySummary}><Copy size={14} />{copied ? 'Copied' : 'Copy summary'}</button>
          <button className="button button-secondary"><Download size={14} /> Export report</button>
          <MoreDots />
        </div>
      </div>
      <div className="replay-note">
        <Radio size={15} />
        <span>
          <strong>{data.is_replay ? 'Deterministic replay fixture' : 'Live Analysis Completed'}</strong> · Signals reflect observed indicators from the automated detection pipeline.
        </span>
        <span className="fixture-badge">{data.is_replay ? 'DEMO DATA' : 'EVIDENCE DESK'}</span>
      </div>
      <section className="case-summary-grid">
        <article className="risk-summary panel">
          <div className="risk-summary-head">
            <div><span className="eyebrow">OVERALL ASSESSMENT</span><h2>Review recommended</h2></div>
            <RiskPill value={data.risk} />
          </div>
          <div className="risk-meter">
            <div className="risk-meter-track"><span style={{ width: `${data.riskScore}%` }} /></div>
            <div className="risk-meter-meta"><span>Signal index <strong>{data.riskScore} / 100</strong></span><span>Heuristic indicator <CircleHelp size={12} /></span></div>
          </div>
          <p className="summary-text">{data.summary}</p>
          <div className="assessment-caveat"><AlertTriangle size={14} /><span>Risk describes observed indicators. It is not an absolute factual verdict.</span></div>
        </article>
        <article className="module-summary panel">
          <div className="panel-heading"><div><h3>Module status</h3><p>Availability is shown separately from findings</p></div></div>
          <div className="module-list">
            {data.modules.map((m) => (
              <div className="module-row" key={m.key}>
                <span className={`module-status-icon ${m.status.toLowerCase().includes('unavailable') ? 'unknown' : m.status.toLowerCase().includes('inconclusive') ? 'neutral' : 'signal'}`}>
                  {m.status.toLowerCase().includes('unavailable') ? <X size={13} /> : m.status.toLowerCase().includes('inconclusive') ? <CircleHelp size={13} /> : <Activity size={13} />}
                </span>
                <div className="module-copy"><strong>{m.label}</strong><span>{m.note}</span></div>
                <span className={`module-result ${m.status.toLowerCase().includes('unavailable') ? 'unknown-text' : ''}`}>{m.score === null ? '—' : `${Math.round(m.score * 100)}%`}</span>
              </div>
            ))}
          </div>
        </article>
      </section>
      <section className="panel provenance-panel">
        <div className="panel-heading">
          <div><h3>Provenance & origin trail</h3><p>What is known about where the media or claim first appeared</p></div>
          <span className="provenance-status"><Fingerprint size={13} /> {data.provenance?.status || 'Not available'}</span>
        </div>
        <div className="provenance-body">
          <div><span className="signal-legend"><i className="legend-unknown" /> Verification state</span><strong>{data.provenance?.detail || 'No origin record found.'}</strong></div>
          <div><span className="signal-legend"><i className="legend-estimate" /> Search permission</span><strong>{data.provenance?.consent || 'Recorded.'}</strong></div>
        </div>
      </section>
      <section className="panel evidence-panel">
        <div className="panel-heading evidence-heading">
          <div><h3>Evidence & signals</h3><p>Review supporting details, limitations, and source type</p></div>
          <button className="button button-tertiary"><Filter size={14} /> All signals <ChevronDown size={13} /></button>
        </div>
        <div className="evidence-list">
          {data.evidence.map((item, i) => (
            <div key={i} className="evidence-item">
              <span className={`evidence-indicator tone-${item.tone || 'slate'}`} />
              <div className="evidence-body">
                <div className="evidence-top">
                  <span className="evidence-type">{item.type}</span>
                  <span className="evidence-tag">{item.tag}</span>
                </div>
                <strong>{item.title}</strong>
                <p>{item.detail}</p>
              </div>
            </div>
          ))}
        </div>
      </section>
      <div className="spread-section-head">
        <div><div className="eyebrow">DISSEMINATION</div><h2>How this claim spread</h2><p>Accounts and timing</p></div>
      </div>
      <section className="panel network-panel">
        <div className="panel-heading"><div><h3>Account sharing network</h3><p>Co-sharing activity detected across platforms</p></div></div>
        <NetworkGraph selected={selectedNode} onSelect={setSelectedNode} />
      </section>
      <section className="action-packet">
        <div className="packet-icon"><Sparkles size={17} /></div>
        <div>
          <span className="eyebrow">ACTIONABLE COUNTERMEASURES</span>
          <strong>Evidence-linked Countermeasure Action Packet</strong>
          <p>Takedown notices, counter-narrative messaging, and containment actions generated from case evidence.</p>
        </div>
        <button className="button button-primary">Generated Action Packet <ArrowRight size={14} /></button>
      </section>
    </>
  );
}

function NetworkGraph({ selected, onSelect }) {
  return (
    <div className="network-graph-stage">
      <svg viewBox="0 0 760 320" className="network-svg">
        <line x1="150" y1="136" x2="308" y2="81" stroke="#373168" strokeWidth="2" />
        <line x1="150" y1="136" x2="319" y2="192" stroke="#373168" strokeWidth="2" />
        <line x1="308" y1="81" x2="477" y2="54" stroke="#373168" strokeWidth="2" />
        <line x1="308" y1="81" x2="480" y2="114" stroke="#373168" strokeWidth="2" />
        <line x1="319" y1="192" x2="482" y2="174" stroke="#373168" strokeWidth="2" />
        <line x1="319" y1="192" x2="485" y2="234" stroke="#373168" strokeWidth="2" />
        {replayCase.nodes.map(n => (
          <g key={n.id} className={`node-group ${selected === n.id ? 'active' : ''}`} onClick={() => onSelect(n.id)}>
            <circle cx={n.x} cy={n.y} r={n.id === 'origin' ? 14 : n.role === 'Amplifier' ? 12 : 9} fill={n.id === 'origin' ? '#ff4f8b' : n.role === 'Amplifier' ? '#eef25a' : '#575195'} />
            <text x={n.x} y={n.y + 24} textAnchor="middle" fill="#aba7d0" fontSize="11">{n.label}</text>
          </g>
        ))}
      </svg>
    </div>
  );
}

function History({ onOpen }) {
  const [filter, setFilter] = useState('All risk levels');
  return (
    <>
      <PageHeading eyebrow="WORKSPACE" title="Case history" description="Review and filter past investigations. Export reports for follow-up.">
        <button className="button button-secondary"><Download size={15} /> Export list</button>
        <button className="button button-primary" onClick={() => onOpen('investigate')}><Plus size={15} /> New investigation</button>
      </PageHeading>
      <section className="panel history-panel">
        <div className="history-toolbar">
          <div className="search-field"><Search size={15} /><input placeholder="Search cases" aria-label="Search cases" /></div>
          <button className="button button-secondary"><Filter size={14} /> {filter} <ChevronDown size={13} /></button>
          <button className="button button-secondary"><Clock3 size={14} /> Any date <ChevronDown size={13} /></button>
        </div>
        <div className="case-table-wrap">
          <table className="case-table">
            <thead>
              <tr>
                <th>Case ID</th>
                <th>Title</th>
                <th>Risk</th>
                <th>Created</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {recentCases.map((c) => (
                <tr key={c.id}>
                  <td><code>{c.id}</code></td>
                  <td><strong>{c.title}</strong></td>
                  <td><RiskPill value={c.risk} small /></td>
                  <td>{c.time}</td>
                  <td><button className="text-button" onClick={() => onOpen('case')}>View case</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function NetworkPage({ onOpenCase }) {
  const [selected, setSelected] = useState('origin');
  return (
    <>
      <PageHeading eyebrow="INVESTIGATION TOOLS" title="Spread analysis" description="Explore how content moves through a supplied account and post dataset.">
        <button className="button button-secondary"><Download size={14} /> Export graph</button>
      </PageHeading>
      <div className="replay-banner">
        <span className="replay-icon"><Radio size={16} /></span>
        <div>
          <strong>Synthetic replay dataset</strong>
          <span>10 nodes shown from a sample. Represents co-sharing, not proven coordination.</span>
        </div>
        <button onClick={() => onOpenCase(replayCase)}>Open case report <ArrowRight size={14} /></button>
      </div>
      <section className="panel network-page-panel">
        <div className="panel-heading">
          <div><h3>Account sharing graph</h3><p>Sample case: {replayCase.title}</p></div>
        </div>
        <NetworkGraph selected={selected} onSelect={setSelected} />
      </section>
    </>
  );
}

function normalizeCase(raw) {
  if (!raw) return replayCase;
  if (raw.nodes && raw.modules && Array.isArray(raw.modules)) {
    return raw;
  }
  const id = raw.case_id || raw.id || 'TF-NEW';
  const risk = raw.overall_risk?.value || raw.overall_risk || raw.risk || 'Inconclusive';
  const capRisk = typeof risk === 'string' ? risk.charAt(0).toUpperCase() + risk.slice(1).toLowerCase() : 'Inconclusive';
  const scoreMap = { critical: 95, high: 75, moderate: 50, low: 20, inconclusive: 10 };
  const riskScore = scoreMap[String(risk).toLowerCase()] ?? 50;

  let modulesList = [];
  if (raw.modules && typeof raw.modules === 'object' && !Array.isArray(raw.modules)) {
    modulesList = Object.entries(raw.modules).map(([k, m]) => ({
      key: k,
      label: k === 'media' ? 'Media forensics' : k === 'text' ? 'Claim & text rules' : k === 'network' ? 'Spread pattern' : `${k} analysis`,
      status: (m?.status || 'Unavailable').replaceAll('_', ' '),
      score: m?.score ?? null,
      note: m?.limitations?.[0] || m?.evidence?.[0] || 'Analysis completed',
    }));
  } else if (Array.isArray(raw.modules)) {
    modulesList = raw.modules;
  }

  let evidenceList = [];
  if (raw.modules && typeof raw.modules === 'object') {
    for (const [k, m] of Object.entries(raw.modules)) {
      if (Array.isArray(m?.evidence)) {
        for (const item of m.evidence) {
          evidenceList.push({
            type: `${k.toUpperCase()} signal`,
            title: item,
            detail: item,
            tag: 'API evidence',
            tone: 'amber',
          });
        }
      }
    }
  }
  if (evidenceList.length === 0 && Array.isArray(raw.evidence)) {
    evidenceList = raw.evidence;
  }
  if (evidenceList.length === 0) {
    evidenceList = [{ type: 'Signal', title: 'Case analysis recorded', detail: raw.summary || 'Summary completed', tag: 'Assessment', tone: 'slate' }];
  }

  return {
    ...replayCase,
    ...raw,
    id,
    title: raw.title || `Analysis ${id.slice(0, 8)}`,
    submitted: raw.submitted || raw.summary || 'Direct API Analysis',
    source: raw.source || 'FastAPI Backend',
    time: raw.created_at ? new Date(raw.created_at).toLocaleTimeString() : 'Just now',
    risk: capRisk,
    riskScore,
    summary: raw.summary || 'Triage analysis completed.',
    modules: modulesList.length ? modulesList : replayCase.modules,
    evidence: evidenceList,
    provenance: raw.provenance || {
      status: raw.modules?.provenance?.status || 'Completed',
      detail: raw.modules?.provenance?.limitations?.[0] || 'Provenance trace completed.',
      consent: 'Recorded',
    },
    nodes: replayCase.nodes,
    timeline: replayCase.timeline,
  };
}

export default function App() {
  const [view, setView] = useState('overview');
  const [caseData, setCaseData] = useState(replayCase);
  const [replay, setReplay] = useState(true);
  const [investigateInput, setInvestigateInput] = useState('');

  const openCase = (data) => {
    setCaseData(normalizeCase(data));
    setReplay(Boolean(data?.is_replay));
    setView('case');
  };

  const handleInvestigateCampaign = (campaignId) => {
    setInvestigateInput(campaignId);
    setView('investigate');
  };

  const go = (id) => {
    if (id === 'case') { setView('case'); return; }
    setView(id);
  };

  return (
    <div className="app-shell">
      <Header view={view} onView={go} replay={replay} setReplay={setReplay} />
      <main className="main-area">
        <div className="page-content">
          {view === 'overview' && <Overview onView={go} replay={replay} />}
          {view === 'investigate' && (
            <Investigate
              onOpenCase={openCase}
              initialInput={investigateInput}
            />
          )}
          {view === 'monitor' && (
            <LiveMonitor onInvestigateCampaign={handleInvestigateCampaign} />
          )}
          {view === 'case' && <CaseDetail data={caseData} onBack={() => setView('overview')} />}
          {view === 'network' && <NetworkPage onOpenCase={openCase} />}
          {view === 'history' && <History onOpen={go} />}
        </div>
        <footer className="app-footer">
          <span><Shield size={13} /> TrustFeed · Evidence first, certainty earned.</span>
          <span>Local workspace <i /> Live API & Replay fixtures enabled</span>
        </footer>
      </main>
    </div>
  );
}

