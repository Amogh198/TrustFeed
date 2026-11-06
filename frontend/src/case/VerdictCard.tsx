import { useState, type ReactNode } from 'react';
import { api } from '../api.js';
import { caseHref } from '../lib/route';
import type { AnalysisResponse } from '../types';

type Tone = 'fake' | 'careful' | 'unknown' | 'real';
export type PlainVerdict = { label: string; tone: Tone; why: { good: boolean; text: string }[]; action: string };

const TONE_LABELS: Record<Tone, string> = { fake: 'Likely fake', careful: 'Be careful', unknown: "We can't tell", real: 'Likely real' };

function toneFor(report: AnalysisResponse): { tone: Tone; label: string } {
  const combined = report.unified_risk?.media_decision?.combined || '';
  if (combined.startsWith('Probably a real')) return { tone: 'real', label: 'Likely real' };
  if (combined.startsWith('Published widely') || combined.startsWith('No sign of AI')) return { tone: 'real', label: 'No sign of AI found' };
  if (combined.startsWith('Disputed')) return { tone: 'careful', label: 'Be careful: the evidence disagrees' };
  if (combined.startsWith('Likely')) return { tone: 'fake', label: 'Likely fake or AI-generated' };
  const risk = report.overall_risk;
  if (!report.unified_risk) return { tone: risk === 'low' ? 'real' : risk === 'inconclusive' ? 'unknown' : 'careful', label: risk === 'inconclusive' ? "We can't tell" : 'Needs a closer look' };
  if (risk === 'critical' || risk === 'high') return { tone: 'fake', label: report.link_analysis && !report.claims?.length ? 'Likely dangerous link' : report.modules?.media?.status === 'complete' ? 'Likely fake or AI-generated' : 'Likely scam or fake' };
  if (risk === 'moderate') return { tone: 'careful', label: 'Be careful' };
  if (risk === 'low') return { tone: 'real', label: 'No warning signs found' };
  return { tone: 'unknown', label: "We can't tell" };
}

/** Put what the checks really found into plain words. It adds no finding of its own. */
export function plainVerdict(report: AnalysisResponse): PlainVerdict {
  const { tone, label } = toneFor(report);
  const why: PlainVerdict['why'] = [];
  const decision = report.unified_risk?.media_decision;
  if (decision) {
    const flagged = !decision.detector_detail.startsWith('0 of');
    why.push({ good: !flagged, text: decision.detector_detail.replace('detectors flagged it', 'AI checks flagged it') });
    const found = decision.web_verdict === 'Same image found online';
    why.push({
      good: found,
      text: decision.web_detail.replace('This exact image', 'This same image').replace('earliest found', 'online since at least').replace(" Earliest found isn't necessarily the source.", ''),
    });
  }
  (report.scam_analysis?.signs || []).slice(0, 3).forEach(sign => why.push({ good: false, text: sign.why }));
  (report.link_analysis?.signs || []).slice(0, 3).forEach(sign => why.push({ good: false, text: sign.why }));
  const verdicts = (report.claims || []).map(claim => claim.verdict).filter(verdict => verdict && verdict !== 'unverified');
  const contradicted = verdicts.filter(verdict => verdict === 'contradicted').length;
  if (contradicted) why.push({ good: false, text: `Public sources contradict ${contradicted} statement(s).` });
  else if (verdicts.length) why.push({ good: true, text: `${verdicts.length} statement(s) were compared with public sources, and none was contradicted.` });
  else why.push({ good: false, text: "We haven't confirmed that any caption or claim is true." });

  const isLink = Boolean(report.link_analysis);
  const isScam = report.scam_analysis?.assessment === 'warning_signs_found';
  let action = 'Treat it as unverified, and look for the original source before sharing.';
  if (isScam) action = "Don't pay, share a code or password, or click links in this message.";
  else if (isLink && tone === 'fake') action = "Don't open this link or enter any details.";
  else if (tone === 'fake') action = "Don't share it until you've checked the original source.";
  else if (tone === 'careful') action = 'Check the original source before you share or rely on it.';
  else if (tone === 'real') action = 'You can look further, but still check any caption or claim before relying on it.';
  return { label, tone, why, action };
}

const MARKERS: Record<Tone, [number, number]> = { fake: [3, 30], careful: [30, 48], unknown: [40, 60], real: [65, 97] };

function markerPosition(tone: Tone, score: number | null | undefined): number {
  const [low, high] = MARKERS[tone];
  return Math.max(low, Math.min(high, score ?? (low + high) / 2));
}

export default function VerdictCard({ report }: { report: AnalysisResponse }) {
  const plain = plainVerdict(report);
  const score = report.unified_risk?.trust_score;
  return (
    <section className={`plain plain-${plain.tone}`} aria-label="Result">
      <div className="plain-head">
        <div>
          <p className="plain-kicker">{TONE_LABELS[plain.tone]}</p>
          <h2>{plain.label}</h2>
        </div>
        <div className="plain-tiles">
          <div className="plain-tile">
            <b>{score != null ? score.toFixed(1) : 'None'}</b>
            <span>Evidence score{score != null ? ' out of 100' : ''}</span>
          </div>
          <div className="plain-tile">
            <b className={`risk risk-${report.overall_risk}`}>{report.overall_risk}</b>
            <span>Risk level</span>
          </div>
        </div>
      </div>
      <div className="plain-meter" aria-hidden="true">
        <span className="plain-marker" style={{ left: `${markerPosition(plain.tone, report.unified_risk?.trust_score)}%` }} />
      </div>
      <div className="plain-scale" aria-hidden="true"><span>Likely fake</span><span>Unclear</span><span>Likely real</span></div>
      <h3>Why we think this</h3>
      <ul className="plain-why">
        {plain.why.map((item, index) => (
          <li key={index}><span aria-hidden="true">{item.good ? '✓' : '✗'}</span> {item.text}</li>
        ))}
      </ul>
      <p className="plain-action"><strong>What to do: </strong>{plain.action}</p>
      <div className="plain-buttons no-print">
        {report.modules?.provenance?.status === 'complete' && <a className="button" href={caseHref(report.case_id, 'source')}>See where this appeared</a>}
        <a className="button" href={api.reportPdfUrl(report.case_id)} download>Download report</a>
      </div>
      <p className="fineprint">A higher evidence score means less sign of a problem. It's a signal for a person to review, not proof or a measured accuracy.</p>
    </section>
  );
}

/** Keep the technical detail one click away. A chosen tab or printing opens it. */
export function EvidenceFold({ forceOpen, children }: { forceOpen: boolean; children: ReactNode }) {
  const [opened, setOpened] = useState(false);
  const open = forceOpen || opened;
  return (
    <div className="evidence-fold">
      <button type="button" className="button evidence-toggle no-print" aria-expanded={open} disabled={forceOpen} onClick={() => setOpened(!opened)}>
        {open ? 'Full evidence' : 'See full evidence'}
      </button>
      {open && children}
    </div>
  );
}
