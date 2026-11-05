import { confidenceText, markPhrases, quotedPhrases, STATUS_WORDS } from '../lib/format';
import { CrossModalPanel, LinkPanel, ScamPanel } from './AnalysisPanels';
import type { AnalysisResponse, ModuleResult } from '../types';
import { Limits, Lines, Meter, Section, Unknown } from '../ui/ui';

function RuleResult({ title, module, none }: { title: string; module?: ModuleResult; none: string }) {
  if (!module || module.status !== 'complete') {
    return (
      <Section title={title} kind="unknown">
        <Unknown>{module?.limitations?.[0] || none}</Unknown>
      </Section>
    );
  }
  return (
    <Section title={title} kind="estimate">
      <p className="module-status">{STATUS_WORDS[module.status]}</p>
      <Meter value={module.score} label="Rule score" />
      <p className="fineprint">{confidenceText(module.confidence)}</p>
      {module.evidence.length
        ? <Lines items={module.evidence} className="lines lines-concern" />
        : <Unknown>The rules matched nothing. That doesn't show the content is safe.</Unknown>}
      <Limits items={module.limitations} />
    </Section>
  );
}

export default function TextLinkTab({ report }: { report: AnalysisResponse }) {
  const phrases = quotedPhrases(report.modules?.text?.evidence || []);
  return (
    <>
      <Section
        title="Claims found in the text"
        kind="unknown"
        lead={report.claim_analysis?.verification?.status === 'complete' ? 'The text is split into separate claims, each compared with public sources. Results are signals, not proof. Marked words set off a language rule.' : 'The text is split into separate claims. They were not compared with outside sources, so each stays unverified. Marked words set off a language rule.'}
      >
        {report.claims?.length ? (
          <ol className="claims">
            {report.claims.map(claim => (
              <li key={claim.id}>
                <p className="claim-text">
                  {markPhrases(claim.text, phrases).map((part, index) => (part.marked ? <mark key={index}>{part.text}</mark> : <span key={index}>{part.text}</span>))}
                </p>
                <p className="claim-verdict"><strong>{claim.verdict === 'unverified' ? 'Unverified' : claim.verdict}.</strong> {claim.rationale}</p>
              </li>
            ))}
          </ol>
        ) : <Unknown>No text was submitted, so there are no claims to list.</Unknown>}
      </Section>
      <ScamPanel report={report} />
      <LinkPanel report={report} />
      <CrossModalPanel report={report} />
      <div className="findings-grid">
        <RuleResult title="Language rules" module={report.modules?.text} none="No text was submitted." />
        <RuleResult title="Link rules" module={report.modules?.url} none="No link was submitted." />
      </div>
    </>
  );
}
