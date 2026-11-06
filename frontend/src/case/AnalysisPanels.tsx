import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { scoreText } from '../lib/format';
import type { AnalysisResponse, ExplanationCheck, LinkPart, NetworkTests, UnifiedRisk } from '../types';
import { Limits, Lines, Section, Unknown } from '../ui/ui';

const PART_WORDS: Record<string, string> = { complete: 'Checked', unavailable: 'Not checked', not_applicable: 'Does not apply' };

function PartRow({ label, part, result }: { label: string; part: LinkPart; result?: string | null }) {
  return (
    <tr>
      <th scope="row">{label}</th>
      <td>{PART_WORDS[part.status] || part.status}</td>
      <td>{part.status === 'complete' ? result || 'Nothing to note.' : part.reason || 'No reason was given.'}</td>
    </tr>
  );
}

/** Page titles and hosts come from outside sites, and React shows them as plain text. */
export function LinkPanel({ report }: { report: AnalysisResponse }) {
  const link = report.link_analysis;
  if (!link) return null;
  const { lookalike, redirects, domain, page, official, threat_lists: threats } = link;
  const asks = [page.asks_for_login && 'a password', page.asks_for_payment && 'card or account details', page.asks_for_code && 'a code'].filter(Boolean);
  const pageResult = [page.title && `Title: ${page.title}`, asks.length ? `Asks for ${asks.join(', ')}.` : 'No sign-in or payment fields seen.', page.form_posts_to.length ? `Form sends to ${page.form_posts_to.join(', ')}.` : ''].filter(Boolean).join(' ');
  return (
    <Section title={`Link check: ${link.requested_host}`} kind="observed" lead="A warning sign is a reason to look closer, not proof. A part that wasn't checked hasn't found anything either way.">
      {link.signs.length
        ? <Lines items={link.signs.map(sign => `${sign.strength === 'strong' ? 'Strong' : 'Weak'} sign: ${sign.why}`)} className="lines lines-concern" />
        : <p>No warning signs found. That doesn't make the link safe.</p>}
      <div className="table-scroll">
        <table className="table">
          <thead><tr><th>Part</th><th>State</th><th>Result</th></tr></thead>
          <tbody>
            <PartRow
              label="Lookalike domain"
              part={lookalike}
              result={lookalike.brand ? `${lookalike.host} ${lookalike.how} ${lookalike.brand}.` : lookalike.owned_by ? `Belongs to ${lookalike.owned_by}.` : 'No imitation of a listed name.'}
            />
            <PartRow label="Redirects" part={redirects} result={redirects.hops.map(hop => hop.host).join(' → ') || null} />
            <PartRow label="Domain age" part={domain} result={domain.age_days != null ? `${domain.domain}, registered ${domain.registered_on}, ${domain.age_days} days ago.` : null} />
            <PartRow label="Page" part={page} result={pageResult} />
            <PartRow
              label="Official site"
              part={official}
              result={official.official_domain ? `Compared with ${official.official_domain}: title overlap ${official.title_similarity}, text overlap ${official.text_similarity}.` : null}
            />
            <PartRow label="Threat lists" part={threats} />
          </tbody>
        </table>
      </div>
      <Limits items={link.limitations} />
    </Section>
  );
}

export function ScamPanel({ report }: { report: AnalysisResponse }) {
  const scam = report.scam_analysis;
  if (!scam) return null;
  return (
    <Section title="Scam warning signs" kind="observed">
      {scam.signs.length
        ? <Lines items={scam.signs.map(sign => `${sign.strength === 'strong' ? 'Strong' : 'Weak'} (${sign.category.replace('_', ' ')}): ${sign.why} Found: “${sign.quote}”`)} className="lines lines-concern" />
        : <p>No warning sign found. Scammers change their wording, so this doesn't show it's safe.</p>}
      <Limits items={scam.limitations} />
    </Section>
  );
}

export function CrossModalPanel({ report }: { report: AnalysisResponse }) {
  const cross = report.cross_modal;
  if (!cross) return null;
  return (
    <Section title="Caption, on-screen text and speech" kind="observed">
      {cross.status !== 'complete' && <Unknown>{cross.reason}</Unknown>}
      {cross.status === 'complete' && (cross.conflicts.length
        ? <Lines items={cross.conflicts.map(item => `${item.severity === 'conflict' ? 'Conflict' : 'Difference'}: ${item.explanation}`)} className="lines lines-concern" />
        : <p>Compared {cross.channels.join(', ')} and found no difference in dates, places, figures or negation.</p>)}
      <p className="fineprint"><strong>Image and caption match: </strong>{cross.image_caption.reason}</p>
      <Limits items={cross.limitations} />
    </Section>
  );
}

/** Pictures and notes a check attaches, such as suspicious frames and regions. Only inline images are shown. */
export function CheckArtifacts({ check }: { check: ExplanationCheck }) {
  const items = (check.artifacts || []) as Record<string, string>[];
  if (!items.length) return null;
  return (
    <ul className="check-artifacts">
      {items.map((item, index) => (
        <li key={index}>
          {item.data_url?.startsWith('data:image/') && <img src={item.data_url} alt={item.label || item.type || 'Attached by this check'} />}
          <small>{[item.type?.replace('_', ' '), item.label].filter(Boolean).join(': ')}</small>
          {item.text && <p>{item.start_s ? `${item.start_s}s: ` : ''}{item.text}</p>}
        </li>
      ))}
    </ul>
  );
}

export function CoordinationTests({ caseId }: { caseId: string }) {
  const [tests, setTests] = useState<NetworkTests | null>(null);
  useEffect(() => {
    let live = true;
    api.getNetworkTests(caseId).then(result => { if (live) setTests(result); }).catch(() => { if (live) setTests(null); });
    return () => { live = false; };
  }, [caseId]);
  if (!tests) return null;
  const { null_test: chance, bursts, repeated_media: media, activity_baseline: baseline } = tests;
  return (
    <Section
      title={tests.synthetic ? 'Is this more than chance? (synthetic demo data)' : 'Is this more than chance?'}
      kind="estimate"
      lead="These describe patterns in the posts read. None of them shows that accounts are coordinating."
    >
      <p><strong>Shuffled timing: </strong>{chance.reason}{chance.p_value != null && ` (p = ${chance.p_value}, ${chance.permutations} shuffles)`}</p>
      <p><strong>Sudden bursts: </strong>{bursts.status === 'complete' ? `${bursts.bursts.length} found. Real news also causes bursts.` : bursts.reason}</p>
      <p><strong>Repeated media: </strong>{media.status === 'complete' ? `${media.groups.length} image(s) reused by several accounts.` : media.reason}</p>
      {baseline && <p><strong>Post counts: </strong>{baseline.reason}</p>}
    </Section>
  );
}

/** The detectors and the web search each give their own answer, side by side. */
export function MediaDecisionPanel({ report }: { report: AnalysisResponse }) {
  const decision = report.unified_risk?.media_decision;
  if (!decision) return null;
  return (
    <Section title="Two independent checks on this media" kind="estimate" lead={decision.combined}>
      <div className="findings-grid">
        <article>
          <h3>AI detectors say</h3>
          <p className="reason-result">{decision.detector_verdict}</p>
          <p>{decision.detector_detail}</p>
        </article>
        <article>
          <h3>Web search says</h3>
          <p className="reason-result">{decision.web_verdict}</p>
          <p>{decision.web_detail}</p>
        </article>
      </div>
    </Section>
  );
}

/** Say plainly what really ran for this case, so nothing looks like more than it was. */
export function WhatRan({ report, sourceProviders }: { report: AnalysisResponse; sourceProviders?: { name: string; status: string; result_count: number | null; limitation?: string | null }[] }) {
  const claims = report.claim_analysis;
  const verification = claims?.verification;
  const media = report.modules?.media;
  const rows: [string, string, string][] = [];
  if (claims) {
    rows.push(['Local model', 'Named people and places (dslim/bert-base-NER)', claims.entity_model_status === 'complete' ? 'Ran' : 'Did not run']);
    rows.push(['Fixed rules', 'Language, scam signs and link address. Their round scores are set weights, not model output', 'Ran']);
    if (verification?.status === 'complete') {
      (verification.providers || []).forEach(item => rows.push(['Live search', item.name, item.status === 'complete' ? `Ran, ${item.result_count} result(s)` : item.reason || 'Did not run']));
      rows.push(['Local model', 'Compared claims with the sources found', verification.comparison_status === 'complete' ? 'Ran' : verification.comparison_reason || 'Did not run']);
    } else {
      rows.push(['Live search', 'Claim sources', verification?.reason || 'Did not run. Tick the search box to compare claims with sources.']);
    }
  }
  if (report.link_analysis) rows.push(['Local model', 'Link model, reads the host name', report.link_analysis.model_score != null ? `Ran, ${scoreText(report.link_analysis.model_score)} out of 100` : 'Did not run']);
  if (media && media.status !== 'not_applicable') rows.push(['Local model', 'Image detector', media.status === 'complete' ? `Ran, raw score ${media.score == null ? 'none' : `${scoreText(media.score)} out of 100`}` : media.limitations?.[0] || 'Did not run']);
  (sourceProviders || []).forEach(item => rows.push(['Source search', item.name, item.status === 'complete' ? `Ran, ${item.result_count} result(s)` : item.limitation || 'Did not run']));
  if (!rows.length) return null;
  return (
    <Section title="What actually ran" kind="observed">
      <div className="table-scroll">
        <table className="table">
          <thead><tr><th>Kind</th><th>What</th><th>Result</th></tr></thead>
          <tbody>{rows.map(([kind, what, result], index) => <tr key={index}><td>{kind}</td><th scope="row">{what}</th><td>{result}</td></tr>)}</tbody>
        </table>
      </div>
    </Section>
  );
}

export function RiskPanel({ risk }: { risk: UnifiedRisk }) {
  return (
    <Section title="What makes up this risk level" kind="estimate" lead="Only checks measured on labelled data are scored. The rest are shown, and can stop a result reading Low.">
      <div className="table-scroll">
        <table className="table">
          <thead><tr><th>Component</th><th>Scored</th><th>Value</th><th>Evidence</th></tr></thead>
          <tbody>
            {risk.components.filter(item => item.status !== 'not_applicable' || item.evidence.length).map(item => (
              <tr key={item.name}>
                <th scope="row">{item.label}</th>
                <td>{item.counted ? `Yes, weight ${item.weight}` : 'No'}</td>
                <td>{item.score != null ? scoreText(item.score) : 'None'}</td>
                <td>
                  {item.evidence.length ? <Lines items={item.evidence.slice(0, 5)} /> : <span>Nothing raised.</span>}
                  {item.note && <small className="fineprint">{item.note}</small>}
                  {item.results_file && <small className="fineprint mono">Measured in {item.results_file}</small>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}
