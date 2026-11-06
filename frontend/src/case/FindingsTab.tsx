import { CheckArtifacts, RiskPanel } from './AnalysisPanels';
import { benchmarkSentence, asLines, MODULE_NAMES, words } from '../lib/format';
import type { AnalysisResponse, Explanation } from '../types';
import { KindTag, Limits, Lines, Loading, Section, Unknown } from '../ui/ui';

export default function FindingsTab({ report, explanation, loading }: {
  report: AnalysisResponse; explanation?: Explanation; loading: boolean;
}) {
  if (!explanation) {
    if (loading) return <Loading>Working out why this result came out this way</Loading>;
    return <Unknown title="The explanation didn't load">The rest of the report still holds each check's own evidence and limits.</Unknown>;
  }
  const ran = explanation.checks.filter(check => check.status !== 'not_applicable' && !check.legacy_alias);
  const uncertain = explanation.uncertainties.length ? explanation.uncertainties : report.uncertainties;
  return (
    <>
      {report.unified_risk && <RiskPanel risk={report.unified_risk} />}
      <Section title="Why it got this result" lead="What each check did and what it found, for this content.">
        <div className="reasons">
          {ran.map(check => (
            <article key={check.check_id}>
              <h3>{check.label}</h3>
              <p className="reason-result">{check.result}</p>
              <Lines items={asLines(check.reasoning)} />
              <CheckArtifacts check={check} />
              <p className="fineprint"><strong>How far to trust it: </strong>{benchmarkSentence(check.benchmark)}</p>
              <Limits items={check.limitations} />
            </article>
          ))}
        </div>
      </Section>

      <div className="findings-grid">
        <Section title="What was submitted" kind="observed">
          <Lines items={explanation.what_was_submitted} />
        </Section>
        <Section title="Overall result" kind="estimate">
          <Lines items={explanation.what_was_detected} />
        </Section>
        <Section title="Raises concern" kind="observed">
          {explanation.supports.length
            ? <Lines items={explanation.supports} className="lines lines-concern" />
            : <p>No check crossed its warning level. That doesn't show the content is genuine.</p>}
        </Section>
        {explanation.refutes.length > 0 && (
          <Section title="Found nothing" kind="observed"><Lines items={explanation.refutes} /></Section>
        )}
      </div>

      <Section title="What remains uncertain" kind="unknown">
        <Unknown><Lines items={uncertain.length ? uncertain : ['No extra uncertainty was recorded, which is not the same as certainty.']} /></Unknown>
      </Section>

      <div className="key" role="note">
        <span>How to read this report:</span>
        <span><KindTag kind="observed" /> a record in the data</span>
        <span><KindTag kind="estimate" /> a score from a model or rule</span>
        <span><KindTag kind="unknown" /> a check or fact that's missing</span>
      </div>

      {explanation.missing_checks.length > 0 && (
        <Section title="Not run for this case" kind="unknown">
          <Unknown>
            <ul className="lines">
              {explanation.missing_checks.map(item => (
                <li key={item.module}><strong>{MODULE_NAMES[item.module] || words(item.module)}: </strong>{item.reason}</li>
              ))}
            </ul>
          </Unknown>
        </Section>
      )}

      {report.recommended_actions.length > 0 && (
        <Section title="Next steps"><Lines items={report.recommended_actions} /></Section>
      )}
    </>
  );
}
