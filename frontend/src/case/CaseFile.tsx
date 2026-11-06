import { Download, FileText, Printer } from 'lucide-react';
import { useCallback, useEffect, useState, type KeyboardEvent } from 'react';
import { api } from '../api.js';
import { downloadFile, MODULE_NAMES, MODULE_ORDER, STATUS_WORDS, utc } from '../lib/format';
import { caseHref, go } from '../lib/route';
import { freshResult } from '../lib/session';
import type { AnalysisResponse, Coverage, Explanation, NetworkPayload, ProvenanceReport, TimelineEvent } from '../types';
import { Loading, Meter, Problem, Tape, Unknown } from '../ui/ui';
import ActionTab from './ActionTab';
import ReportTab from './ReportTab';
import { CoordinationTests } from './AnalysisPanels';
import FindingsTab from './FindingsTab';
import MediaTab from './MediaTab';
import SourceTab from './SourceTab';
import SpreadTab from './SpreadTab';
import TextLinkTab from './TextLinkTab';
import TimelineTab from './TimelineTab';
import TrustPanel from './TrustPanel';

export interface CaseDetails {
  explanation?: Explanation;
  provenance?: ProvenanceReport;
  timeline?: { events: TimelineEvent[] };
  network?: NetworkPayload;
  coverage?: Coverage | null;
}

const TABS: [string, string][] = [
  ['findings', 'Findings'],
  ['media', 'Media'],
  ['text', 'Text and link'],
  ['source', 'Source search'],
  ['spread', 'Spread'],
  ['timeline', 'Timeline'],
  ['report', 'Full report'],
  ['action', 'Action packet'],
];

const MODULE_TABS: Record<string, string> = { media: 'media', text: 'text', url: 'text', provenance: 'source', network: 'spread' };

function SignalStrip({ report }: { report: AnalysisResponse }) {
  return (
    <ol className="signals">
      {MODULE_ORDER.map(key => {
        const module = report.modules?.[key];
        return (
          <li key={key} className={`signal signal-${module?.status || 'unavailable'}`}>
            <a href={caseHref(report.case_id, MODULE_TABS[key])}>
              <span className="signal-name">{MODULE_NAMES[key]}</span>
              <span className="signal-status">{STATUS_WORDS[module?.status] || "Didn't run"}</span>
              <Meter value={module?.score} label={key === 'network' ? 'Review signal' : undefined} />
            </a>
          </li>
        );
      })}
    </ol>
  );
}

export default function CaseFile({ caseId, tab }: { caseId: string; tab: string }) {
  const [report, setReport] = useState<AnalysisResponse | null>(() => freshResult(caseId) || null);
  const [details, setDetails] = useState<CaseDetails>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [partial, setPartial] = useState('');
  const [printing, setPrinting] = useState(false);

  useEffect(() => {
    let live = true;
    const known = freshResult(caseId);
    setReport(known || null);
    setDetails({});
    setError('');
    setPartial('');
    setLoading(true);
    (async () => {
      try {
        const base = known || await api.getCase(caseId);
        if (!live) return;
        setReport(base);
        const [explanation, provenance, timeline, network, coverage] = await Promise.allSettled([
          api.getExplanation(caseId), api.getProvenance(caseId), api.getTimeline(caseId),
          api.getNetwork(caseId), api.getCoverage(caseId),
        ]);
        if (!live) return;
        const value = <T,>(result: PromiseSettledResult<T>) => (result.status === 'fulfilled' ? result.value : undefined);
        setDetails({
          explanation: value(explanation), provenance: value(provenance), timeline: value(timeline),
          network: value(network), coverage: value(coverage),
        });
        const failed = [explanation, provenance, timeline, network, coverage].filter(result => result.status === 'rejected');
        if (failed.length) setPartial(`${failed.length} part${failed.length > 1 ? 's' : ''} of this report didn't load. Reload the page to try again.`);
      } catch (problem) {
        if (live) setError((problem as Error).message);
      } finally {
        if (live) setLoading(false);
      }
    })();
    return () => { live = false; };
  }, [caseId]);

  useEffect(() => {
    if (!printing) return undefined;
    const timer = window.setTimeout(() => { window.print(); setPrinting(false); }, 150);
    return () => window.clearTimeout(timer);
  }, [printing]);

  const exportCase = useCallback(async () => {
    try {
      const value = await api.getExport(caseId);
      downloadFile(`trustfeed-${caseId}.json`, JSON.stringify(value, null, 2), 'application/json');
    } catch (problem) { setPartial((problem as Error).message); }
  }, [caseId]);

  // Changing tab from far down a long section starts the new one at its top.
  useEffect(() => {
    const bar = document.querySelector<HTMLElement>('.tabs');
    const top = document.querySelector<HTMLElement>('.topbar');
    if (!bar || !top) return;
    const stuckAt = bar.offsetTop - top.offsetHeight;
    if (window.scrollY > stuckAt) window.scrollTo({ top: stuckAt });
  }, [tab]);

  if (error) {
    return (
      <div className="page">
        <Unknown title="This case couldn't be opened">
          <p>{error}</p>
          <p><a href="#/cases">Go to saved cases</a></p>
        </Unknown>
      </div>
    );
  }
  if (!report) return <div className="page"><Loading>Opening the case</Loading></div>;

  const current = TABS.some(([key]) => key === tab) ? tab : 'findings';
  const onTabKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = TABS.findIndex(([key]) => key === current);
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const next = TABS[(index + step + TABS.length) % TABS.length][0];
    go(caseHref(caseId, next));
    window.setTimeout(() => document.getElementById(`tab-${next}`)?.focus(), 0);
  };

  const panels: Record<string, JSX.Element> = {
    findings: <FindingsTab report={report} explanation={details.explanation} loading={loading} sourceProviders={details.provenance?.providers} />,
    media: <MediaTab report={report} explanation={details.explanation} />,
    text: <TextLinkTab report={report} />,
    source: <SourceTab report={report} data={details.provenance} loading={loading} />,
    spread: <><CoordinationTests caseId={caseId} /><SpreadTab report={report} graph={details.network} coverage={details.coverage} loading={loading} /></>,
    timeline: <TimelineTab events={details.timeline?.events} loading={loading} />,
    report: <ReportTab caseId={caseId} />,
    action: <ActionTab report={report} />,
  };

  return (
    <div className="case">
      {report.is_replay && <Tape>{report.replay_label || 'Replay data, not a live result'}</Tape>}
      <header className={`verdict verdict-${report.overall_risk}`}>
        <div className="verdict-word">
          <h1 aria-label={`Risk: ${report.overall_risk}`}>{report.overall_risk}</h1>
          <p>A triage signal for a person to review. Not a factual verdict.</p>
        </div>
        <div className="verdict-copy">
          <p className="verdict-summary">{report.summary}</p>
          <p className="verdict-meta">
            <span className="mono">{report.case_id}</span>
            <span>Saved {utc(report.created_at)}</span>
          </p>
          <div className="verdict-actions no-print">
            <a className="button button-primary" href={caseHref(caseId, 'action')}><FileText size={16} aria-hidden="true" />Draft action packet</a>
            <a className="button" href={api.reportPdfUrl(caseId)} download><FileText size={16} aria-hidden="true" />Report PDF</a>
            <button type="button" className="button" onClick={exportCase}><Download size={16} aria-hidden="true" />Export JSON</button>
            <button type="button" className="button" onClick={() => setPrinting(true)}><Printer size={16} aria-hidden="true" />Print report</button>
          </div>
        </div>
      </header>
      <TrustPanel report={report} explanation={details.explanation} />
      <SignalStrip report={report} />
      {partial && <div className="page-inner"><Problem>{partial}</Problem></div>}
      <div className="tabs no-print" role="tablist" aria-label="Report sections" onKeyDown={onTabKey}>
        {TABS.map(([key, name]) => (
          <a
            key={key} id={`tab-${key}`} role="tab" href={caseHref(caseId, key)}
            aria-selected={current === key} tabIndex={current === key ? 0 : -1}
            aria-controls="case-panel"
          >{name}</a>
        ))}
      </div>
      <div id="case-panel" className={current === 'spread' && !printing ? 'panel panel-wide' : 'panel'} role="tabpanel" aria-labelledby={`tab-${current}`}>
        {printing
          ? TABS.filter(([key]) => key !== 'action').map(([key, name]) => <div key={key} className="print-part"><h2 className="print-title">{name}</h2>{panels[key]}</div>)
          : panels[current]}
      </div>
    </div>
  );
}
