import React, { useMemo, useState } from 'react';
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
  { id: 'network', label: 'Spread analysis', icon: Network },
  { id: 'history', label: 'Case history', icon: Clock3 },
];

function Brand() {
  return <div className="brand"><span className="brand-mark"><Shield size={18} strokeWidth={2.4} /><i /></span><span>trustfeed<span className="brand-period">.</span></span></div>;
}

function RiskPill({ value, small = false }) {
  const cls = value.toLowerCase().replaceAll(' ', '-');
  return <span className={`risk-pill risk-${cls} ${small ? 'small' : ''}`}><i />{value}</span>;
}

function Header({ view, onView, replay, setReplay }) {
  const [menuOpen, setMenuOpen] = useState(false);
  return <>
    <header className="topbar">
      <div className="top-left"><button className="icon-button mobile-menu" aria-label="Open navigation" onClick={() => setMenuOpen(!menuOpen)}><Menu size={19} /></button><Brand /><span className="top-divider" /><span className="workspace-name">Investigation workspace <ChevronDown size={14} /></span></div>
      <div className="top-right"><span className={`connection ${replay ? 'offline' : ''}`}><i />{replay ? 'Offline replay' : 'Workspace ready'}</span><button className="icon-button notification" aria-label="Notifications"><Bell size={17} /><b /></button><div className="avatar">AM</div></div>
    </header>
    <aside className={`sidebar ${menuOpen ? 'open' : ''}`}>
      <div className="sidebar-label">WORKSPACE</div>
      <nav>{tabs.map(({ id, label, icon: Icon }) => <button key={id} onClick={() => { onView(id); setMenuOpen(false); }} className={`nav-item ${view === id ? 'active' : ''}`}><Icon size={17} /><span>{label}</span>{id === 'history' && <em>12</em>}</button>)}</nav>
      <div className="sidebar-separator" />
      <div className="sidebar-label case-label">RECENT CASES <button aria-label="Search cases"><Search size={14} /></button></div>
      <div className="sidebar-cases">{recentCases.map((item, i) => <button className={`side-case ${i === 0 ? 'selected' : ''}`} key={item.id} onClick={() => onView('overview')}><span className={`case-dot dot-${item.risk.toLowerCase()}`} /><span className="side-case-copy"><strong>{item.title}</strong><small>{item.id} · {item.time}</small></span></button>)}</div>
      <button className="new-case" onClick={() => onView('investigate')}><Plus size={16} /> New investigation</button>
      <div className="sidebar-spacer" />
      <div className="sidebar-bottom"><button className="nav-item"><CircleHelp size={17} /><span>Help & documentation</span></button><div className="profile-row"><div className="avatar profile-avatar">AM</div><div><strong>Amogh M.</strong><small>Analyst workspace</small></div><MoreDots /></div></div>
    </aside>
  </>;
}

function MoreDots() { return <button className="dots-button" aria-label="More options"><span>•••</span></button>; }

function PageHeading({ eyebrow, title, description, children }) {
  return <div className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{children && <div className="heading-actions">{children}</div>}</div>;
}

function StatCard({ label, value, note, icon: Icon, accent, trend }) {
  return <article className="stat-card"><div className="stat-top"><span>{label}</span><span className={`stat-icon ${accent}`}><Icon size={16} /></span></div><div className="stat-value">{value}</div><div className="stat-note">{trend && <span className="trend"><ArrowUpRight size={13} />{trend}</span>}{note}</div></article>;
}

function Overview({ onView, replay }) {
  return <>
    <PageHeading eyebrow="THURSDAY, NOVEMBER 5, 2026" title="Good morning, Amogh" description="A clear view of the signals that need your attention."><button className="button button-secondary" onClick={() => onView('history')}><Clock3 size={15} /> View all cases</button><button className="button button-primary" onClick={() => onView('investigate')}><Plus size={16} /> New investigation</button></PageHeading>
    <div className="replay-banner"><span className="replay-icon"><Radio size={16} /></span><div><strong>{replay ? 'Replay mode is active' : 'Replay mode available'}</strong><span>{replay ? 'This workspace is showing deterministic sample data. No live feeds or models are connected.' : 'Explore a complete sample investigation without connecting live feeds or models.'}</span></div><button onClick={() => onView('investigate')}>{replay ? 'Open sample case' : 'Try replay'} <ArrowRight size={14} /></button></div>
    <section className="stats-grid"><StatCard label="Open investigations" value="12" note="Across all risk levels" icon={FileSearch} accent="mint" /><StatCard label="Need review" value="04" note="3 high · 1 moderate" icon={AlertTriangle} accent="peach" trend="+2" /><StatCard label="Signals this week" value="38" note="Across text, media & network" icon={Activity} accent="lavender" trend="+12%" /><StatCard label="Replay cases" value="06" note="Ready for offline demo" icon={Radio} accent="blue" /></section>
    <div className="section-heading"><div><h2>Recent investigations</h2><p>Latest cases across your workspace</p></div><button className="text-button" onClick={() => onView('history')}>View case history <ArrowRight size={14} /></button></div>
    <CaseTable compact />
    <div className="bottom-grid"><section className="panel attention-panel"><div className="panel-heading"><div><h3>Needs your attention</h3><p>Cases with unresolved evidence or elevated signals</p></div><span className="count-badge">4</span></div><div className="attention-item"><div className="attention-mark amber"><AlertTriangle size={16} /></div><div className="attention-copy"><strong>Emergency flood warning</strong><span>Unverified claim · high spread signal</span></div><RiskPill value="High" small /><button className="arrow-button" onClick={() => onView('investigate')}><ArrowUpRight size={16} /></button></div><div className="attention-item"><div className="attention-mark blue"><Link2 size={16} /></div><div className="attention-copy"><strong>Relief fund payment link</strong><span>Domain age unavailable · manual review</span></div><RiskPill value="Moderate" small /><button className="arrow-button" onClick={() => onView('history')}><ArrowUpRight size={16} /></button></div></section><section className="panel activity-panel"><div className="panel-heading"><div><h3>Workspace activity</h3><p>Recent analyst actions</p></div><button className="icon-button" aria-label="More activity"><MoreDots /></button></div><div className="activity-line"><span className="activity-dot green" /><div><strong>Replay case opened</strong><span>Emergency flood warning · by you</span></div><time>2m ago</time></div><div className="activity-line"><span className="activity-dot purple" /><div><strong>Evidence report exported</strong><span>Vintage wildfire image · PDF</span></div><time>28m ago</time></div><div className="activity-line"><span className="activity-dot blue" /><div><strong>Investigation created</strong><span>Relief fund payment link</span></div><time>1h ago</time></div></section></div>
  </>;
}

function CaseTable({ compact = false, onOpen }) {
  const items = compact ? recentCases : [...recentCases, { id: 'TF-2026-0408', title: 'School closure notice', time: 'Oct 30', risk: 'Low', type: 'Text' }, { id: 'TF-2026-0402', title: 'Celebrity endorsement clip', time: 'Oct 28', risk: 'Inconclusive', type: 'Video · Media' }];
  return <div className="table-wrap"><table><thead><tr><th>CASE</th><th>INPUT TYPE</th><th>RISK LEVEL</th><th>LAST UPDATED</th><th /></tr></thead><tbody>{items.map(item => <tr key={item.id} onClick={() => onOpen?.()}><td><span className="table-title">{item.title}</span><span className="table-id">{item.id}</span></td><td><span className="type-cell"><FileCheck2 size={14} />{item.type}</span></td><td><RiskPill value={item.risk} small /></td><td><span className="muted-cell">{item.time}</span></td><td><button className="arrow-button" aria-label={`Open ${item.title}`} onClick={onOpen}><ArrowUpRight size={16} /></button></td></tr>)}</tbody></table></div>;
}

function Investigate({ onOpenCase }) {
  const [input, setInput] = useState('');
  const [mode, setMode] = useState('text');
  const [dragging, setDragging] = useState(false);
  const [notice, setNotice] = useState('');
  const [mediaSelected, setMediaSelected] = useState(false);
  const [webSearchConsent, setWebSearchConsent] = useState(false);
  const [isPreparing, setIsPreparing] = useState(false);
  const openDemo = () => { setInput(replayCase.submitted); setNotice('Sample text loaded. This is synthetic replay data.'); };
  const selectMedia = () => { setMediaSelected(true); setNotice('File selected for local preview. Upload and media analysis are not connected to a backend yet.'); };
  const submit = (event) => {
    event.preventDefault();
    if (isPreparing) return;
    if (mode !== 'media' && !input.trim()) { setNotice('Add text or a URL to prepare a case.'); return; }
    if (mode === 'media' && !mediaSelected) { setNotice('Choose an image or video before preparing a media case.'); return; }
    setIsPreparing(true);
    setNotice('Preparing a deterministic replay report. No live model, feed, or web search is being used.');
    window.setTimeout(() => onOpenCase({
      ...replayCase,
      submitted: mode === 'media' ? 'Local media preview selected' : input.trim(),
      title: 'New replay analysis',
      id: 'TF-NEW-001',
      source: mode === 'media' ? 'Local file preview · not uploaded' : mode === 'url' ? 'URL input · not fetched' : 'Session text input · not transmitted',
      summary: 'This local preview uses a deterministic sample response. No live model, backend request, or web search was made.',
      provenance: {
        status: mode === 'media' ? 'Local preview only' : 'No media attached',
        detail: mode === 'media' ? 'The selected file stays in this browser preview. Its origin has not been searched or verified.' : 'Provenance needs a media item and an approved source-search service.',
        consent: webSearchConsent ? 'Consent recorded, but no search service is connected in replay.' : 'No external search consent recorded.',
      },
    }), 500);
  };
  return <>
    <PageHeading eyebrow="NEW CASE" title="Start an investigation" description="Inspect a claim, URL, or media item. Each result keeps evidence and uncertainty visible." />
    <div className="investigate-grid"><section className="panel intake-panel"><div className="panel-heading"><div><h3>What would you like to check?</h3><p>Choose an input type, then add the content for review.</p></div><span className="secure-note"><Shield size={13} /> Local preview</span></div><div className="input-tabs">{[['text', MessageSquareText, 'Text or claim'], ['url', Globe2, 'URL'], ['media', FileImage, 'Image or video']].map(([key, Icon, label]) => <button type="button" className={mode === key ? 'selected' : ''} key={key} onClick={() => { setMode(key); setNotice(''); }}><Icon size={15} />{label}</button>)}</div><form onSubmit={submit}>
      {mode === 'media' ? <><div className={`dropzone ${dragging ? 'dragging' : ''}`} onDragOver={e => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={e => { e.preventDefault(); setDragging(false); selectMedia(); }}><span className="upload-icon"><Upload size={20} /></span><strong>{mediaSelected ? 'Media selected for local preview' : 'Drop a file here, or browse'}</strong><span>JPG, PNG, WebP or MP4 · Up to 25 MB</span><label className="button button-secondary browse-button">Browse files<input type="file" accept="image/jpeg,image/png,image/webp,video/mp4" onChange={selectMedia} /></label></div><label className="consent-card"><input type="checkbox" checked={webSearchConsent} onChange={e => setWebSearchConsent(e.target.checked)} /><span><strong>Allow a future source search</strong><small>Optional. A live source search could send the image to a third party. This replay build has no search service connected.</small></span></label></> : <label className="content-field"><span>{mode === 'url' ? 'URL to inspect' : 'Content to inspect'}</span><textarea value={input} onChange={e => setInput(e.target.value)} aria-invalid={Boolean(notice && !input.trim())} placeholder={mode === 'url' ? 'Paste a link to a post, article, or website…' : 'Paste a claim, forwarded message, social post, or caption…'} rows={8} /><span className="field-foot"><span>{input.length} characters</span><button type="button" className="inline-action" onClick={openDemo}><Sparkles size={13} /> Use sample</button></span></label>}
      {notice && <div className="form-notice" aria-live="polite"><CircleHelp size={14} />{notice}</div>}
      <div className="form-bottom"><div className="privacy-copy"><Shield size={14} /> Content stays in this browser preview.</div><button className="button button-primary" type="submit" disabled={isPreparing}>{isPreparing ? <LoaderCircle className="spin" size={15} /> : <FileSearch size={15} />}{isPreparing ? 'Preparing replay…' : 'Prepare analysis'} {!isPreparing && <ArrowRight size={14} />}</button></div>
    </form></section><aside className="panel scope-panel"><div className="panel-heading"><div><h3>What the analysis shows</h3><p>Signals are leads for review, not proof.</p></div></div><div className="scope-list"><div><span className="scope-icon violet"><FileSearch size={15} /></span><div><strong>Claim & language signals</strong><p>Urgency, scam patterns, and claim context.</p></div></div><div><span className="scope-icon green"><Fingerprint size={15} /></span><div><strong>Media indicators</strong><p>Metadata, manipulation signals, and provenance when available.</p></div></div><div><span className="scope-icon amber"><Network size={15} /></span><div><strong>Spread patterns</strong><p>Timing and repeated content in the provided dataset.</p></div></div></div><div className="scope-foot"><span className="signal-legend"><i className="legend-evidence" /> Evidence</span><span className="signal-legend"><i className="legend-estimate" /> Estimate</span><span className="signal-legend"><i className="legend-unknown" /> Unknown</span></div></aside></div>
    <section className="replay-cta"><div className="replay-cta-icon"><Radio size={18} /></div><div><strong>Need a reliable demo without a live service?</strong><span>Open the deterministic sample case to explore the report, spread graph, and timeline offline.</span></div><button className="button button-secondary" onClick={() => onOpenCase(replayCase)}>Open replay case <ArrowRight size={14} /></button></section>
  </>;
}

function EvidenceItem({ item }) { return <article className="evidence-item"><div className={`evidence-icon ${item.tone}`}>{item.type === 'Network signal' ? <Network size={15} /> : item.type === 'Claim check' ? <BadgeCheck size={15} /> : <MessageSquareText size={15} />}</div><div className="evidence-main"><span className="evidence-type">{item.type}</span><strong>{item.title}</strong><p>{item.detail}</p><span className={`evidence-tag tag-${item.tone}`}>{item.tag}</span></div><button className="icon-button evidence-more" aria-label="Evidence details"><MoreDots /></button></article>; }

function NetworkGraph({ selected, onSelect }) {
  const nodeMap = useMemo(() => Object.fromEntries(replayCase.nodes.map(node => [node.id, node])), []);
  return <div className="graph-wrap"><svg viewBox="0 0 720 290" role="img" aria-label="Synthetic replay graph of account sharing"><defs><pattern id="dots" width="16" height="16" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="#dce3dc" /></pattern></defs><rect width="720" height="290" fill="url(#dots)" />{replayCase.links.map(([from, to]) => { const a = nodeMap[from], b = nodeMap[to]; return <line key={`${from}-${to}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="graph-edge" />; })}{replayCase.nodes.map(node => <g key={node.id} className={`graph-node ${selected === node.id ? 'chosen' : ''}`} onClick={() => onSelect(node.id)} tabIndex="0" role="button" aria-label={`${node.label}, ${node.role}`} onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && onSelect(node.id)}><circle cx={node.x} cy={node.y} r={node.id === 'origin' ? 17 : node.role === 'Amplifier' ? 13 : 9} className={node.id === 'origin' ? 'origin-node' : node.role === 'Amplifier' ? 'amplifier-node' : 'participant-node'} /><circle cx={node.x} cy={node.y} r="3" className="node-center" /><text x={node.x} y={node.y + 29} textAnchor="middle">{node.label}</text></g>)}</svg><div className="graph-legend"><span><i className="legend-origin" /> Origin candidate</span><span><i className="legend-amplifier" /> Amplifier</span><span><i className="legend-participant" /> Participant</span></div></div>;
}

function Timeline({ progress, setProgress }) {
  return <div className="timeline"><div className="timeline-track"><div className="timeline-fill" style={{ width: `${progress}%` }} />{replayCase.timeline.map((point, i) => <button key={point.time} className={`timeline-marker ${i < progress / 25 ? 'passed' : ''}`} style={{ left: `${i * 33.333}%` }} onClick={() => setProgress(i * 33.333)} aria-label={`Show events at ${point.time}`} />)}</div><div className="timeline-labels"><span>09:40</span><span>09:41</span><span>09:42</span><span>09:43 UTC</span></div></div>;
}

function CaseDetail({ data, onBack }) {
  const [selectedNode, setSelectedNode] = useState('origin');
  const [progress, setProgress] = useState(100);
  const [copied, setCopied] = useState(false);
  const selected = replayCase.nodes.find(n => n.id === selectedNode) || replayCase.nodes[0];
  const copySummary = async () => { try { await navigator.clipboard.writeText(data.summary); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { setCopied(false); } };
  return <>
    <div className="breadcrumb"><button onClick={onBack}>Investigations</button><span>/</span><span>{data.id}</span><span className="replay-chip"><Radio size={12} /> REPLAY</span></div>
    <div className="case-title-row"><div><div className="case-kicker">CASE {data.id} <span>·</span> {data.time}</div><h1>{data.title}</h1><p className="case-source"><MessageSquareText size={14} /> {data.source}</p></div><div className="case-actions"><button className="button button-secondary" onClick={copySummary}><Copy size={14} />{copied ? 'Copied' : 'Copy summary'}</button><button className="button button-secondary"><Download size={14} /> Export report</button><MoreDots /></div></div>
    <div className="replay-note"><Radio size={15} /><span><strong>Deterministic replay fixture</strong> · Signals below come from synthetic sample data. No live feed, source verification service, or model was queried.</span><span className="fixture-badge">DEMO DATA</span></div>
    <section className="case-summary-grid"><article className="risk-summary panel"><div className="risk-summary-head"><div><span className="eyebrow">OVERALL ASSESSMENT</span><h2>Review recommended</h2></div><RiskPill value={data.risk} /></div><div className="risk-meter"><div className="risk-meter-track"><span style={{ width: `${data.riskScore}%` }} /></div><div className="risk-meter-meta"><span>Signal index <strong>{data.riskScore} / 100</strong></span><span>Heuristic indicator <CircleHelp size={12} /></span></div></div><p className="summary-text">{data.summary}</p><div className="assessment-caveat"><AlertTriangle size={14} /><span>Risk describes observed indicators in this fixture. It is not a factual verdict.</span></div></article><article className="module-summary panel"><div className="panel-heading"><div><h3>Module status</h3><p>Availability is shown separately from findings</p></div></div><div className="module-list">{data.modules.map(m => <div className="module-row" key={m.key}><span className={`module-status-icon ${m.status === 'Unavailable' ? 'unknown' : m.status === 'Inconclusive' ? 'neutral' : 'signal'}`}>{m.status === 'Unavailable' ? <X size={13} /> : m.status === 'Inconclusive' ? <CircleHelp size={13} /> : <Activity size={13} />}</span><div className="module-copy"><strong>{m.label}</strong><span>{m.note}</span></div><span className={`module-result ${m.status === 'Unavailable' ? 'unknown-text' : ''}`}>{m.score === null ? '—' : `${Math.round(m.score * 100)}%`}</span></div>)}</div></article></section>
    <section className="panel provenance-panel"><div className="panel-heading"><div><h3>Provenance & origin trail</h3><p>What is known about where the media or claim first appeared</p></div><span className="provenance-status"><Fingerprint size={13} /> {data.provenance?.status || 'Not available'}</span></div><div className="provenance-body"><div><span className="signal-legend"><i className="legend-unknown" /> Verification state</span><strong>{data.provenance?.detail || 'No media or origin record is available in this case.'}</strong></div><div><span className="signal-legend"><i className="legend-estimate" /> Search permission</span><strong>{data.provenance?.consent || 'No external search consent recorded.'}</strong></div></div><p className="provenance-caveat"><CircleHelp size={13} /> An origin candidate is a lead, not proof of creation, ownership, or intent.</p></section>
    <section className="panel evidence-panel"><div className="panel-heading evidence-heading"><div><h3>Evidence & signals</h3><p>Review supporting details, limitations, and source type</p></div><button className="button button-tertiary"><Filter size={14} /> All signals <ChevronDown size={13} /></button></div><div className="evidence-list">{data.evidence.map((item, i) => <EvidenceItem item={item} key={i} />)}</div><div className="evidence-footer"><span><i className="legend-evidence" /> Observed evidence</span><span><i className="legend-estimate" /> Heuristic estimate</span><span><i className="legend-unknown" /> Unavailable or unknown</span><a>How to read this report <ArrowRight size={13} /></a></div></section>
    <div className="spread-section-head"><div><div className="eyebrow">DISSEMINATION</div><h2>How this claim spread</h2><p>Accounts and timing in the supplied sample dataset</p></div><button className="text-button">View full analysis <ArrowRight size={14} /></button></div>
    <section className="spread-grid"><article className="panel graph-panel"><div className="panel-heading"><div><h3>Sharing network</h3><p>10 of 18 sample accounts shown</p></div><button className="button button-tertiary"><Filter size={13} /> Filter</button></div><NetworkGraph selected={selectedNode} onSelect={setSelectedNode} /><div className="graph-disclaimer">Connections indicate observed co-sharing in synthetic data; they do not establish coordination or intent.</div></article><article className="panel node-panel"><div className="panel-heading"><div><h3>Selected account</h3><p>Click a node to inspect its sample record</p></div></div><div className="node-profile"><div className={`node-avatar ${selected.role === 'Origin candidate' ? 'origin-avatar' : ''}`}><span>{selected.label.slice(0, 1).toUpperCase()}</span></div><div><strong>@{selected.label}</strong><span className="node-role">{selected.role}</span></div></div><div className="node-fields"><div><span>First seen</span><strong>{selected.time} UTC</strong></div><div><span>Posts in sample</span><strong>{selected.id === 'origin' ? '1' : selected.role === 'Amplifier' ? '3' : '1'}</strong></div><div><span>Account identity</span><strong className="unknown-text">Not verified</strong></div></div><div className="node-warning"><CircleHelp size={14} /><span>Role label is an analytical hint from this replay fixture, not an attribution.</span></div></article></section>
    <section className="panel timeline-panel"><div className="panel-heading"><div><h3>Propagation timeline</h3><p>Scrub the sample window to review observed events</p></div><button className="button button-tertiary" onClick={() => setProgress(progress >= 100 ? 0 : Math.min(100, progress + 33.333))}><Activity size={14} /> {progress >= 100 ? 'Replay again' : 'Continue replay'}</button></div><Timeline progress={progress} setProgress={setProgress} /><div className="event-list">{replayCase.timeline.filter((_, i) => i <= Math.floor(progress / 33.333)).map(point => <div className="event-row" key={point.time}><time>{point.time}</time><span className={`event-dot ${point.kind}`} /><strong>{point.event}</strong><span className="event-who">{point.who}</span></div>)}</div></section>
    <section className="action-packet"><div className="packet-icon"><Sparkles size={17} /></div><div><span className="eyebrow">NEXT STEP</span><strong>Prepare an evidence-linked action packet</strong><p>Draft a clear, reviewable summary for a platform or communications team.</p><small>AI-generated draft · Requires analyst review before use</small></div><button className="button button-primary">Draft action packet <ArrowRight size={14} /></button></section>
  </>;
}

function History({ onOpen }) {
  const [filter, setFilter] = useState('All risk levels');
  return <><PageHeading eyebrow="WORKSPACE" title="Case history" description="Review and filter past investigations. Export reports for follow-up."><button className="button button-secondary"><Download size={15} /> Export list</button><button className="button button-primary" onClick={() => onOpen('investigate')}><Plus size={15} /> New investigation</button></PageHeading><section className="panel history-panel"><div className="history-toolbar"><div className="search-field"><Search size={15} /><input placeholder="Search cases" aria-label="Search cases" /></div><button className="button button-secondary"><Filter size={14} /> {filter} <ChevronDown size={13} /></button><button className="button button-secondary"><Clock3 size={14} /> Any date <ChevronDown size={13} /></button></div><CaseTable onOpen={() => onOpen('case')} /><div className="pagination"><span>Showing 1–5 of 12 investigations</span><div><button disabled>Previous</button><button className="page-current">1</button><button>2</button><button>3</button><button>Next</button></div></div></section></>;
}

function NetworkPage({ onOpenCase }) {
  const [selected, setSelected] = useState('origin');
  return <><PageHeading eyebrow="INVESTIGATION TOOLS" title="Spread analysis" description="Explore how content moves through a supplied account and post dataset."><button className="button button-secondary"><Download size={14} /> Export graph</button></PageHeading><div className="replay-banner"><span className="replay-icon"><Radio size={16} /></span><div><strong>Synthetic replay dataset</strong><span>10 nodes shown from a deterministic sample. The graph represents co-sharing, not proven coordination.</span></div><button onClick={() => onOpenCase(replayCase)}>Open case report <ArrowRight size={14} /></button></div><section className="panel network-page-panel"><div className="panel-heading"><div><h3>Account sharing graph</h3><p>Sample case: {replayCase.title}</p></div><button className="button button-tertiary"><Filter size={13} /> Filter</button></div><NetworkGraph selected={selected} onSelect={setSelected} /><div className="network-page-foot"><div className="node-fields"><div><span>Selected</span><strong>@{replayCase.nodes.find(n => n.id === selected)?.label}</strong></div><div><span>Sample window</span><strong>09:40–09:43 UTC</strong></div><div><span>Shown</span><strong>10 of 18 accounts</strong></div></div><p className="graph-disclaimer">Node labels and roles are fixture metadata. Do not infer identity, intent, or automation from this visualization.</p></div></section><section className="panel timeline-panel"><div className="panel-heading"><div><h3>Spread timeline</h3><p>Key events from the deterministic sample</p></div></div><Timeline progress={100} setProgress={() => {}} /><div className="event-list">{replayCase.timeline.map(point => <div className="event-row" key={point.time}><time>{point.time}</time><span className={`event-dot ${point.kind}`} /><strong>{point.event}</strong><span className="event-who">{point.who}</span></div>)}</div></section></>;
}

export default function App() {
  const [view, setView] = useState('overview');
  const [caseData, setCaseData] = useState(replayCase);
  const [replay, setReplay] = useState(true);
  const openCase = (data) => { setCaseData(data); setReplay(true); setView('case'); };
  const go = (id) => { if (id === 'case') { setView('case'); return; } setView(id); };
  return <div className="app-shell"><Header view={view} onView={go} replay={replay} setReplay={setReplay} /><main className="main-area"><div className="page-content">{view === 'overview' && <Overview onView={go} replay={replay} />}{view === 'investigate' && <Investigate onOpenCase={openCase} />}{view === 'case' && <CaseDetail data={caseData} onBack={() => setView('overview')} />}{view === 'network' && <NetworkPage onOpenCase={openCase} />}{view === 'history' && <History onOpen={go} />}</div><footer className="app-footer"><span><Shield size={13} /> TrustFeed · Evidence first, certainty earned.</span><span>Local workspace <i /> Replay fixtures enabled</span></footer></main></div>;
}
