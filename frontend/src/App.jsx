import React, { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle, ArrowLeft, CheckCircle2, ChevronRight, Clock3, Download, FileImage,
  FileSearch, Globe2, LoaderCircle, Network, Plus, Radio, Search, Shield,
  Sparkles, Upload, XCircle,
} from 'lucide-react';
import { api, readableUploadError, safeHttpUrl } from './api.js';
import { ExplanationPanel, HeatmapPanel } from './CaseExtras.jsx';
import MonitorPage from './MonitorPage.jsx';
import NetworkPanel from './NetworkPanel.jsx';
import './api-dashboard.css';
import './network.css';

const moduleLabels = { media: 'Media analysis', text: 'Text analysis', url: 'URL analysis', provenance: 'Source search', network: 'Public-post trace' };

function statusLabel(status) { return status?.replaceAll('_', ' ') || 'unavailable'; }
function score(value) { return value == null ? 'No score' : `${Math.round(value * 100)}%`; }
// Under this the detector's band is low or inconclusive, and it flags few fakes at these settings.
const MEDIA_ELEVATED = 0.75;
function isQuietMedia(result) { const media = result?.modules?.media; return media?.status === 'complete' && media.score != null && media.score < MEDIA_ELEVATED; }

function Labels({ report }) {
  return <span className="labels">{report?.is_replay && <b className="label replay">Replay</b>}{report?.replay_label && <b className="label replay">{report.replay_label}</b>}</span>;
}

function SafeLink({ href, children }) {
  const safe = safeHttpUrl(href);
  return safe ? <a href={safe} target="_blank" rel="noreferrer">{children}</a> : <span>{children}</span>;
}

function Empty({ title, copy, action }) {
  return <section className="empty panel"><FileSearch size={22} /><h2>{title}</h2><p>{copy}</p>{action}</section>;
}

function Loading({ children }) { return <div className="loading"><LoaderCircle className="spin" size={18} />{children}</div>; }

function Nav({ page, setPage, onDemo, onStory }) {
  return <aside className="api-sidebar"><div className="brand"><span className="brand-mark"><Shield size={18} /></span>trustfeed<span>.</span></div><nav>
    <button className={page === 'overview' ? 'active' : ''} onClick={() => setPage('overview')}><Radio size={16} /> Overview</button>
    <button className={page === 'investigate' ? 'active' : ''} onClick={() => setPage('investigate')}><Plus size={16} /> New investigation</button>
    <button className={page === 'history' ? 'active' : ''} onClick={() => setPage('history')}><Clock3 size={16} /> Case history</button>
    <button className={page === 'monitor' ? 'active' : ''} onClick={() => setPage('monitor')}><Globe2 size={16} /> Monitoring</button>
  </nav><div className="side-bottom"><button onClick={onDemo}><Sparkles size={15} /> Open demo-001</button><button onClick={onStory}><Network size={15} /> Open linked story</button><small>Evidence first, certainty earned.</small></div></aside>;
}

function Overview({ cases, total, loading, error, onOpen, onInvestigate, scenarios, scenarioError, onStartReplay }) {
  return <><header className="page-title"><div><span className="eyebrow">TRUSTTRACE AI</span><h1>Investigation workspace</h1><p>Review submitted content, supporting evidence, and the limits of each signal.</p></div><button className="button primary" onClick={onInvestigate}><Plus size={15} /> New investigation</button></header>
    <section className="api-banner"><Shield size={18} /><div><strong>Real API mode</strong><span>New submissions are saved through the API. Replay scenarios use recorded, labelled data and remain offline.</span></div></section>
    <section className="metric-row"><Metric label="Saved cases" value={loading ? '—' : total} /><Metric label="Risk levels" value="Signals" detail="Not factual verdicts" /><Metric label="Source search" value="Opt-in" detail="Off by default" /></section>
    <section className="panel table-panel"><div className="panel-title"><div><h2>Recent cases</h2><p>Saved by the local API</p></div></div>{loading ? <Loading>Loading case history…</Loading> : error ? <Empty title="Case history unavailable" copy={error} /> : cases.length ? <CaseTable cases={cases} onOpen={onOpen} /> : <Empty title="No saved cases" copy="Start an investigation or open demo-001 to inspect a report." action={<button className="button secondary" onClick={onInvestigate}>Start an investigation</button>} />}</section>
    <section className="panel replay-library"><div className="panel-title"><div><h2>Offline replay library</h2><p>Recorded scenarios run through the same API without internet access.</p></div></div>{scenarioError ? <p>{scenarioError}</p> : scenarios.length ? <div className="scenario-list">{scenarios.map(scenario => <article key={scenario.id}><div><strong>{scenario.title}</strong><p>{scenario.description}</p><span className="label replay">{scenario.label}</span></div><button className="button secondary" onClick={() => onStartReplay(scenario.id)}>Run replay</button></article>)}</div> : <Loading>Loading replay scenarios…</Loading>}</section></>;
}

function Metric({ label, value, detail }) { return <article className="metric panel"><span>{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}</article>; }

function CaseTable({ cases, onOpen }) {
  return <div className="table-wrap"><table><thead><tr><th>Case</th><th>Risk</th><th>Saved</th><th>Data</th><th /></tr></thead><tbody>{cases.map(item => <tr key={item.case_id}><td><button className="case-link" onClick={() => onOpen(item.case_id)}>{item.case_id}<span>{item.summary}</span></button></td><td><Risk risk={item.overall_risk} /></td><td>{new Date(item.created_at).toLocaleString()}</td><td>{item.is_replay ? <span className="label replay">Replay</span> : <span className="label">Saved</span>}</td><td><button className="row-action" onClick={() => onOpen(item.case_id)} aria-label={`Open ${item.case_id}`}><ChevronRight size={16} /></button></td></tr>)}</tbody></table></div>;
}

function Risk({ risk }) { return <span className={`risk ${risk || 'inconclusive'}`}>{risk || 'inconclusive'}</span>; }

function Investigate({ onReport }) {
  const [mode, setMode] = useState('text');
  const [text, setText] = useState('');
  const [url, setUrl] = useState('');
  const [file, setFile] = useState(null);
  const [searchWeb, setSearchWeb] = useState(false);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState('');

  async function submit(event) {
    event.preventDefault();
    if (mode === 'media' && !file) return setMessage('Choose an image or video to continue.');
    if (mode !== 'media' && !text.trim() && !url.trim()) return setMessage('Add text, a URL, or both to continue.');
    setWorking(true);
    setMessage(searchWeb ? 'Searching sources and connected public platforms. This can take up to 2 minutes.' : 'Sending the case to the local API for analysis.');
    try {
      const result = mode === 'media'
        ? await api.analyzeMedia({ file, text: text.trim(), url: url.trim(), searchWeb })
        : await api.analyze({ text: text.trim(), url: url.trim(), searchWeb });
      await onReport(result, mode === 'media' ? file : null);
    } catch (error) { setMessage(mode === 'media' ? readableUploadError(error) : error.message); }
    finally { setWorking(false); }
  }

  return <><header className="page-title"><div><span className="eyebrow">NEW CASE</span><h1>Start an investigation</h1><p>Submit content to the local API and inspect each available signal.</p></div></header>
    <section className="intake-grid"><form className="panel intake" onSubmit={submit}><div className="tabs">{[['text', FileSearch, 'Text or URL'], ['media', FileImage, 'Image or video']].map(([key, Icon, label]) => <button type="button" key={key} className={mode === key ? 'active' : ''} onClick={() => { setMode(key); setMessage(''); }}><Icon size={15} />{label}</button>)}</div>
      {mode === 'media' && <label className="drop-field"><Upload size={20} /><strong>{file ? file.name : 'Choose an image or video'}</strong><span>JPEG, PNG, WebP, MP4, MOV, WebM or AVI</span><input type="file" accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm,video/x-msvideo" onChange={event => setFile(event.target.files?.[0] || null)} /></label>}
      <label>Text or claim<textarea value={text} onChange={event => setText(event.target.value)} maxLength="20000" placeholder="Paste a claim, caption, or context…" rows="5" /></label>
      <label>Link <input value={url} onChange={event => setUrl(event.target.value)} type="url" placeholder="https://example.org/post" /></label>
      <label className="consent"><input type="checkbox" checked={searchWeb} onChange={event => setSearchWeb(event.target.checked)} /><span><strong>Search the public web and platforms</strong><small>Optional. This sends an uploaded image to configured source-search services. It sends text and links to Mastodon, Lemmy, Hacker News and Bluesky search, and follows short links to their destination. Leave unticked to keep the request on this server.</small></span></label>
      {message && <div className="notice" aria-live="polite">{working && <LoaderCircle className="spin" size={15} />}{message}</div>}
      <button className="button primary" type="submit" disabled={working}>{working ? 'Analysing…' : 'Analyse case'} {!working && <ChevronRight size={15} />}</button>
    </form><aside className="panel expectation"><h2>What to expect</h2><p>Each module reports its own result, evidence, and limitations.</p><ul><li>Scores are signals, never proof.</li><li>Unavailable means the service or data was absent.</li><li>Source search and public-post tracing are separate from authenticity.</li><li>Search can take up to about 2 minutes when you opt in.</li></ul></aside></section>
  </>;
}

function ModuleCards({ modules, report }) {
  return <section className="module-grid">{Object.entries(modules || {}).map(([key, module]) => <article key={key} className={`module-card panel status-${module.status}`}><div><span className="eyebrow">{moduleLabels[key] || key}</span><strong>{statusLabel(module.status)}</strong></div><b>{key === 'network' && module.score != null ? `Review signal ${score(module.score)}` : score(module.score)}</b><p>{module.confidence == null ? 'Confidence not measured' : `Confidence ${score(module.confidence)}`}</p>{module.evidence?.length ? <details><summary>Evidence ({module.evidence.length})</summary><ul>{module.evidence.map((item, index) => <li key={index}>{item}</li>)}</ul></details> : <p>No evidence returned.</p>}{module.limitations?.length ? <details open><summary>Limitations</summary><ul>{module.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></details> : null}{key === 'media' && isQuietMedia(report) && <p className="warning">A low or inconclusive media signal does not show that the media is authentic. In its benchmark the detector flagged very few fakes.</p>}</article>)}</section>;
}

function Provenance({ data, loading }) {
  if (loading) return <Loading>Loading source-search report…</Loading>;
  if (!data) return <Empty title="Source search unavailable" copy="No saved source-search report was returned for this case." />;
  return <section className="panel detail-panel"><div className="panel-title"><div><h2>Source-search report</h2><p>Recorded appearances and provider limits</p></div><Labels report={{ is_replay: data.replay, replay_label: data.synthetic ? 'Synthetic' : null }} /></div><p className="status-copy">Status: <b>{statusLabel(data.status)}</b></p>{data.earliest_found && <div className="caveat"><AlertTriangle size={15} /><div><strong>Earliest found appearance</strong><p>{data.earliest_found.observed_at || 'No date found'} · {data.earliest_found.date_source || 'date source unavailable'}</p><p>{data.earliest_found.caveat}</p></div></div>}
    <div className="provider-list">{data.providers?.map(provider => <span key={provider.name}>{provider.name}: {provider.status}{provider.result_count != null ? ` (${provider.result_count})` : ''}{provider.limitation ? ` — ${provider.limitation}` : ''}</span>)}</div>
    {data.appearances?.length ? <div className="appearance-list">{data.appearances.map(item => <article key={item.id}><SafeLink href={item.page_url}>{item.page_title || item.page_url || 'Untitled page'}</SafeLink><p>{item.match_type || 'match type unavailable'} · {item.observed_at || 'date unavailable'} · {item.date_source || 'date source unavailable'}</p><small>{item.date_evidence || 'No date evidence provided.'}</small></article>)}</div> : <p>No appearance pages were saved.</p>}
    {data.limitations?.length ? <Limitations items={data.limitations} /> : null}</section>;
}

function Timeline({ data, loading }) {
  if (loading) return <Loading>Loading timeline…</Loading>;
  const events = data?.events || [];
  const dated = events.filter(event => event.at); const undated = events.filter(event => !event.at);
  return <section className="panel detail-panel"><div className="panel-title"><div><h2>Appearance timeline</h2><p>Dated observations appear first; undated items remain visible.</p></div></div>{events.length ? <><EventList events={dated} /><>{undated.length ? <><h3>Undated events</h3><EventList events={undated} /></> : null}</></> : <p>No timeline events were saved.</p>}</section>;
}

function EventList({ events }) { return <div className="event-list">{events.map((event, index) => <article key={`${event.ref}-${index}`}><time>{event.at ? new Date(event.at).toLocaleString() : 'No date'}</time><div><strong>{event.label}</strong><span>{event.module} · {event.date_source}{event.synthetic ? ' · synthetic' : ''}</span></div></article>)}</div>; }

function Limitations({ items }) { return <details open className="limitations"><summary>Limitations</summary><ul>{items.map((item, index) => <li key={index}>{item}</li>)}</ul></details>; }

function CaseReport({ report, details, loading, error, upload, onBack, onExport, onActionPacket }) {
  if (!report) return <Empty title="No case selected" copy="Open a case from history or submit new content." action={<button className="button secondary" onClick={onBack}>Back to workspace</button>} />;
  return <><button className="back" onClick={onBack}><ArrowLeft size={15} /> Back to workspace</button><header className="report-head"><div><span className="eyebrow">CASE {report.case_id}</span><h1>Analysis report</h1><p>{report.summary}</p><Labels report={report} /></div><div><button className="button secondary" onClick={onExport}><Download size={15} /> Export JSON</button><button className="button secondary" onClick={onActionPacket}><Sparkles size={15} /> Action packet</button></div></header>
    {report.is_replay && <div className="api-banner"><Radio size={17} /><div><strong>Offline replay data</strong><span>{report.replay_label || 'This report uses a labelled replay fixture.'}</span></div></div>}
    <section className="assessment panel"><div><span className="eyebrow">OVERALL ASSESSMENT</span><h2>{report.overall_risk}</h2></div><Risk risk={report.overall_risk} /><p>{report.summary}</p><p className="warning">This risk is a triage signal. It is not a factual verdict.</p></section>
    <ModuleCards modules={report.modules} report={report} />
    {report.claims?.length ? <section className="panel detail-panel"><h2>Claims</h2>{report.claims.map(claim => <article className="claim" key={claim.id}><strong>{claim.verdict}</strong><p>{claim.text}</p><small>{claim.rationale}</small></article>)}</section> : null}
    {report.uncertainties?.length ? <section className="panel detail-panel"><h2>Uncertainties</h2><Limitations items={report.uncertainties} /></section> : null}
    {error && <div className="notice"><XCircle size={15} /> Some detail requests failed: {error}</div>}
    <ExplanationPanel data={details.explanation} loading={loading} /><HeatmapPanel file={upload} />
    <Provenance data={details.provenance} loading={loading} /><Timeline data={details.timeline} loading={loading} /><NetworkPanel graph={details.network} coverage={details.coverage} loading={loading} />
    {details.packet && <section className="panel detail-panel"><h2>Action packet</h2><p>{details.packet.label}</p><pre className="packet">{details.packet.draft}</pre></section>}
  </>;
}

function History({ cases, loading, error, risk, setRisk, onOpen }) {
  return <><header className="page-title"><div><span className="eyebrow">SAVED CASES</span><h1>Case history</h1><p>Local results stored by the API.</p></div></header><section className="panel table-panel"><div className="history-controls"><label>Risk filter<select value={risk} onChange={event => setRisk(event.target.value)}><option value="">All risk levels</option><option value="low">Low</option><option value="moderate">Moderate</option><option value="high">High</option><option value="critical">Critical</option><option value="inconclusive">Inconclusive</option></select></label></div>{loading ? <Loading>Loading saved cases…</Loading> : error ? <Empty title="History unavailable" copy={error} /> : cases.length ? <CaseTable cases={cases} onOpen={onOpen} /> : <Empty title="No matching cases" copy="No saved case matches this filter." />}</section></>;
}

export default function App() {
  const [page, setPage] = useState('overview');
  const [cases, setCases] = useState([]); const [savedTotal, setSavedTotal] = useState(0); const [historyLoading, setHistoryLoading] = useState(true); const [historyError, setHistoryError] = useState(''); const [risk, setRisk] = useState('');
  const [report, setReport] = useState(null); const [details, setDetails] = useState({}); const [detailsLoading, setDetailsLoading] = useState(false); const [detailsError, setDetailsError] = useState('');
  const [uploads, setUploads] = useState({}); const [scenarios, setScenarios] = useState([]); const [scenarioError, setScenarioError] = useState('');

  async function loadHistory(filter = risk) { setHistoryLoading(true); try { const data = await api.getHistory(filter); setCases(data.cases || []); if (!filter) setSavedTotal(data.total ?? (data.cases || []).length); setHistoryError(''); } catch (error) { setHistoryError(error.message); } finally { setHistoryLoading(false); } }
  useEffect(() => { loadHistory(''); }, []);
  useEffect(() => { if (page === 'history') loadHistory(risk); if (page === 'overview') loadHistory(''); }, [risk, page]);
  useEffect(() => { api.getReplayScenarios().then(data => setScenarios(data.scenarios || [])).catch(error => setScenarioError(error.message)); }, []);

  async function loadCase(caseId, supplied = null) {
    setPage('case'); setDetails({}); setDetailsError(''); setDetailsLoading(true);
    try {
      const base = supplied || await api.getCase(caseId); setReport(base);
      const entries = await Promise.allSettled([api.getProvenance(base.case_id), api.getTimeline(base.case_id), api.getNetwork(base.case_id), api.getCoverage(base.case_id), api.getExplanation(base.case_id)]);
      const names = ['provenance', 'timeline', 'network', 'coverage', 'explanation']; const next = {}; const failures = [];
      entries.forEach((entry, index) => { if (entry.status === 'fulfilled') next[names[index]] = entry.value; else failures.push(entry.reason.message); });
      setDetails(next); setDetailsError(failures.join(' ')); loadHistory('');
    } catch (error) { setDetailsError(error.message); } finally { setDetailsLoading(false); }
  }
  async function openReport(result, file = null) { if (file) setUploads(current => ({ ...current, [result.case_id]: file })); await loadCase(result.case_id, result); }
  async function openDemo() { await loadCase('demo-001'); }
  async function openStory() { await loadCase('demo-story-001'); }
  async function startReplay(scenarioId) { try { await openReport(await api.startReplay(scenarioId)); } catch (error) { setScenarioError(error.message); } }
  async function exportCase() { try { const value = await api.getExport(report.case_id); const blob = new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = `${report.case_id}.json`; link.click(); URL.revokeObjectURL(link.href); } catch (error) { setDetailsError(error.message); } }
  async function actionPacket() { try { const packet = await api.actionPacket(report.case_id); setDetails(current => ({ ...current, packet })); } catch (error) { setDetailsError(error.message); } }

  const current = useMemo(() => page === 'overview' ? <Overview cases={cases} total={savedTotal} loading={historyLoading} error={historyError} onOpen={loadCase} onInvestigate={() => setPage('investigate')} scenarios={scenarios} scenarioError={scenarioError} onStartReplay={startReplay} /> : page === 'investigate' ? <Investigate onReport={openReport} /> : page === 'monitor' ? <MonitorPage /> : page === 'history' ? <History cases={cases} loading={historyLoading} error={historyError} risk={risk} setRisk={setRisk} onOpen={loadCase} /> : <CaseReport report={report} details={details} loading={detailsLoading} error={detailsError} upload={report ? uploads[report.case_id] : null} onBack={() => setPage('overview')} onExport={exportCase} onActionPacket={actionPacket} />, [page, uploads, cases, historyLoading, historyError, risk, report, details, detailsLoading, detailsError, scenarios, scenarioError]);
  return <div className="api-app"><Nav page={page} setPage={setPage} onDemo={openDemo} onStory={openStory} /><main className="api-main">{current}</main></div>;
}
