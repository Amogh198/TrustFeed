import { useEffect, useState } from 'react';
import { NEUTRAL_TRUST, scoreText, trustScore } from '../lib/format';
import { uploadFor } from '../lib/session';
import type { AnalysisResponse, Explanation } from '../types';

function Thumbnail({ caseId }: { caseId: string }) {
  const [file] = useState(() => uploadFor(caseId));
  const [address, setAddress] = useState<string | null>(null);
  useEffect(() => {
    if (!file) return undefined;
    const next = URL.createObjectURL(file);
    setAddress(next);
    return () => URL.revokeObjectURL(next);
  }, [file]);
  if (!file || !address) return null;
  return file.type.startsWith('video/')
    ? <video className="trust-thumb" src={address} muted controls aria-label="The video you uploaded" />
    : <img className="trust-thumb" src={address} alt="The image you uploaded" />;
}

/** The number people look for first, with how it was worked out and why it can't be taken as proof. */
export default function TrustPanel({ report, explanation }: { report: AnalysisResponse; explanation?: Explanation }) {
  const trust = trustScore(report);
  const benchmark = explanation?.checks.find(check => check.module === 'media' && check.benchmark)?.benchmark;
  const usedMedia = trust.counted.some(item => item.name === 'Media');

  return (
    <section className="trust" aria-label="Trust score">
      <Thumbnail caseId={report.case_id} />
      {trust.score === null ? (
        <div className="trust-none">
          <b>No trust score</b>
          <p>
            {trust.mediaMissing
              ? "The media check didn't run on this server, so nothing measured this content. Open the Media tab for the fix."
              : "No check scored the content itself. Spread and source search say where content went, not whether it's true."}
          </p>
        </div>
      ) : (
        <>
          <div className="trust-number">
            <b>{trust.score}</b><span>/100</span>
            <p>Trust score</p>
          </div>
          <div className="trust-copy">
            <p className="trust-words">{trust.words}</p>
            <span className="meter-track" aria-hidden="true"><span style={{ width: `${trust.score}%` }} /></span>
            {trust.score > NEUTRAL_TRUST && <p>{report.unified_risk?.trust_note}</p>}
            <p>
              Warning signals checked: {trust.counted.map(item => `${item.name} ${scoreText(item.value)}`).join(', ')}.
              {trust.fromOverallRisk
                ? ' The overall result raised concern for another reason, so the score is lower. See Why it got this result.'
                : trust.capped
                  ? ` Finding no warning doesn't show content is genuine, so the score stops at ${NEUTRAL_TRUST}, which is a neutral midpoint, not a measurement.`
                  : ' The score is 100 minus the strongest signal.'}
            </p>
            {trust.mediaMissing && <p className="trust-warn">The media check didn't run, so this score covers the text and link only.</p>}
            <p className="fineprint">
              An estimate, not proof.
              {usedMedia && trust.capped && benchmark?.low_fake != null
                ? ` In testing, this detector scored ${benchmark.low_fake} of ${benchmark.n_fake} fakes as low, so a low score says very little.`
                : ''}
            </p>
          </div>
        </>
      )}
    </section>
  );
}
