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
  const uncertain = explanation.uncertainties.length ? explanation.uncertainties : report.uncertainties;
  return (
    <>
      <div className="key" role="note">
        <span>How to read this report:</span>
        <span><KindTag kind="observed" /> a record in the data</span>
        <span><KindTag kind="estimate" /> a score from a model or rule</span>
        <span><KindTag kind="unknown" /> a check or fact that's missing</span>
      </div>

      <div className="findings-grid">
        <Section title="What was submitted" kind="observed">
          <Lines items={explanation.what_was_submitted} />
        </Section>
        <Section title="What was detected" kind="estimate">
          <Lines items={explanation.what_was_detected} />
        </Section>
        <Section title="Raises concern" kind="observed">
          {explanation.supports.length
            ? <Lines items={explanation.supports} className="lines lines-concern" />
            : <Unknown>No check raised concern. That doesn't show the content is genuine.</Unknown>}
        </Section>
        <Section title="Found nothing" kind="observed">
          {explanation.refutes.length
            ? <Lines items={explanation.refutes} />
            : <Unknown>No check gave a clean result. A quiet media detector doesn't count here, because it isn't reassuring.</Unknown>}
        </Section>
      </div>

      <Section title="What remains uncertain" kind="unknown">
        <Unknown><Lines items={uncertain.length ? uncertain : ['No extra uncertainty was recorded, which is not the same as certainty.']} /></Unknown>
      </Section>

      <Section title="Each check, and how far to trust it" lead="Open a check to see its reasoning and its limits.">
        <div className="checks">
          {explanation.checks.map(check => (
            <details key={check.check_id} className="check-row">
              <summary>
                <span className="check-name">{check.label}</span>
                <span className="check-result">{check.result}</span>
              </summary>
              <div className="check-body">
                <Lines items={asLines(check.reasoning)} />
                <p><strong>How far to trust it: </strong>{benchmarkSentence(check.benchmark)}</p>
                <Limits items={check.limitations} open />
              </div>
            </details>
          ))}
        </div>
      </Section>

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
