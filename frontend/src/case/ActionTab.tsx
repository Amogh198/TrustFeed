import { Check, Copy, Download } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { downloadFile } from '../lib/format';
import type { ActionPacket, AnalysisResponse } from '../types';
import { Caveat, Loading, Problem, Section, Tape } from '../ui/ui';

const AUDIENCES: [string, string][] = [
  ['reviewers', 'Internal reviewers'],
  ['platform trust and safety teams', 'Platform trust and safety'],
  ['the public', 'The public'],
];

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch { setCopied(false); }
  };
  return (
    <button type="button" className="button button-small" onClick={copy} aria-label={label}>
      {copied ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}{copied ? 'Copied' : 'Copy'}
    </button>
  );
}

/** A correction draft built only from this case's fields. A person confirms it before anyone sees it. */
function correctionCard(report: AnalysisResponse, packet: ActionPacket): string {
  const claims = report.claims.map(claim => `- "${claim.text}": ${claim.verdict}`);
  const counter = packet.sections.find(section => section.heading === 'Suggested countermeasures')?.items || [];
  return [
    'DRAFT: needs a person to confirm before use.',
    '',
    `Review status: ${report.overall_risk} risk signal. This isn't a factual verdict.`,
    report.summary,
    ...(claims.length ? ['', 'Claims under review:', ...claims] : []),
    ...(counter.length ? ['', 'What to do:', ...counter.map(item => `- ${item}`)] : []),
    ...(report.is_replay ? ['', report.replay_label || 'Replay data.'] : []),
  ].join('\n');
}

export default function ActionTab({ report }: { report: AnalysisResponse }) {
  const [audience, setAudience] = useState(AUDIENCES[0][0]);
  const [packet, setPacket] = useState<ActionPacket | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    setError('');
    api.actionPacket(report.case_id, audience)
      .then(value => { if (live) setPacket(value); })
      .catch(problem => { if (live) setError(problem.message); });
    return () => { live = false; };
  }, [report.case_id, audience]);

  if (error) return <Problem>{error}</Problem>;
  if (!packet) return <Loading>Drafting the action packet</Loading>;

  const counter = packet.sections.find(section => section.heading === 'Suggested countermeasures');
  const rest = packet.sections.filter(section => section !== counter);
  const card = correctionCard(report, packet);

  return (
    <>
      {report.is_replay && <Tape>{report.replay_label || 'Replay data'}</Tape>}
      <Caveat><strong>{packet.label}</strong><p>Check it before anyone acts on it or sends it.</p></Caveat>

      <div className="packet-tools no-print">
        <label className="select-field">Draft for
          <select value={audience} onChange={event => setAudience(event.target.value)}>
            {AUDIENCES.map(([value, name]) => <option key={value} value={value}>{name}</option>)}
          </select>
        </label>
        <button type="button" className="button" onClick={() => downloadFile(`truthtrace-${report.case_id}-action-packet.txt`, packet.draft, 'text/plain')}>
          <Download size={16} aria-hidden="true" />Download packet
        </button>
        <CopyButton text={packet.draft} label="Copy the whole packet" />
      </div>

      {counter && (
        <Section title="What to do now">
          <ol className="actions">
            {counter.items.map((item, index) => <li key={index}><p>{item}</p><CopyButton text={item} label={`Copy step ${index + 1}`} /></li>)}
          </ol>
        </Section>
      )}

      <Section title="Correction card draft" lead="Built from this case's record for a person to edit. Don't publish it until the findings are confirmed.">
        <div className="correction">
          <pre>{card}</pre>
          <CopyButton text={card} label="Copy the correction card" />
        </div>
      </Section>

      <div className="packet-parts">
        {rest.map(section => (
          <Section key={section.heading} title={section.heading}>
            <ul className="lines">{section.items.map((item, index) => <li key={index}>{item}</li>)}</ul>
          </Section>
        ))}
      </div>
    </>
  );
}
