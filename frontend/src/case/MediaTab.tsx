import { Flame, ImagePlus } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { benchmarkSentence, confidenceText, isQuietMedia, STATUS_WORDS, uploadProblem } from '../lib/format';
import { setUploadFor, uploadFor } from '../lib/session';
import type { AnalysisResponse, Benchmark, Explanation, Heatmap } from '../types';
import { Caveat, Limits, Lines, Meter, Problem, Section, Unknown } from '../ui/ui';

function useObjectUrl(file: File | null | undefined): string | null {
  const [address, setAddress] = useState<string | null>(null);
  useEffect(() => {
    if (!file) { setAddress(null); return undefined; }
    const next = URL.createObjectURL(file);
    setAddress(next);
    return () => URL.revokeObjectURL(next);
  }, [file]);
  return address;
}

/** One dot per test image, so the detector's record can be seen at a glance. */
function BenchmarkDots({ benchmark }: { benchmark: Benchmark }) {
  const rows: [string, number, number, string][] = [
    ['Fake images in the test', benchmark.n_fake ?? 0, benchmark.flagged_fake ?? 0, 'flagged'],
    ['Real images in the test', benchmark.n_real ?? 0, benchmark.flagged_real ?? 0, 'wrongly flagged'],
  ];
  return (
    <div className="dots">
      {rows.map(([name, total, lit, word]) => (
        <div key={name}>
          <p><strong>{lit} of {total}</strong> {word}. {name}.</p>
          <div className="dot-grid" aria-hidden="true">
            {Array.from({ length: total }, (_, index) => <i key={index} className={index < lit ? 'lit' : ''} />)}
          </div>
        </div>
      ))}
    </div>
  );
}

function HeatmapPanel({ caseId, file, onFile }: { caseId: string; file: File | null; onFile: (file: File) => void }) {
  const preview = useObjectUrl(file);
  const [result, setResult] = useState<Heatmap | null>(null);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState('');
  const [strength, setStrength] = useState(70);

  useEffect(() => { setResult(null); setMessage(''); }, [file, caseId]);

  const run = async () => {
    if (!file) return;
    setWorking(true);
    setMessage('');
    try { setResult(await api.heatmap(file)); }
    catch (problem) { setMessage((problem as Error).message); }
    finally { setWorking(false); }
  };

  const choose = (chosen: File | undefined) => {
    if (!chosen) return;
    const problem = uploadProblem(chosen);
    if (problem || !chosen.type.startsWith('image/')) { setMessage(problem || 'The heatmap works on images only.'); return; }
    setUploadFor(caseId, chosen);
    onFile(chosen);
  };

  return (
    <Section
      title="Where the model's score changed"
      kind="estimate"
      lead="Each part of the image is covered in turn to see how the score moves. This shows sensitivity, not proof of editing."
    >
      {!file && (
        <Unknown title="The image isn't kept after analysis">
          <p>To make a heatmap, choose the same image again. It's checked and then deleted, and no new case is made.</p>
          <label className="button file-button"><ImagePlus size={16} aria-hidden="true" />Choose the image
            <input type="file" accept="image/jpeg,image/png,image/webp" onChange={event => choose(event.target.files?.[0])} />
          </label>
        </Unknown>
      )}
      {preview && file?.type.startsWith('image/') && (
        <div className="heatmap">
          <div className={working ? 'heatmap-stage scanning' : 'heatmap-stage'}>
            <img src={preview} alt="The image you uploaded" />
            {result?.png_base64 && (
              <img className="heatmap-layer" style={{ opacity: strength / 100 }} src={`data:image/png;base64,${result.png_base64}`} alt="Colour grid showing where covering the image moved the score" />
            )}
          </div>
          <div className="heatmap-side">
            {!result && (
              <button type="button" className="button button-primary" disabled={working} onClick={run}>
                <Flame size={16} aria-hidden="true" />{working ? 'Covering each area, up to a minute' : 'Make heatmap'}
              </button>
            )}
            {message && <Problem>{message}</Problem>}
            {result && <>
              <p>{result.reasoning}</p>
              {result.png_base64 && <>
                <label className="range-field">Overlay strength
                  <input type="range" min={0} max={100} value={strength} onChange={event => setStrength(Number(event.target.value))} />
                </label>
                <p className="heat-key"><i className="heat-up" />Raised the score <i className="heat-down" />Lowered the score</p>
              </>}
              <Limits items={result.limitations} open />
            </>}
          </div>
        </div>
      )}
      {file && !file.type.startsWith('image/') && <Unknown>The heatmap works on images only.</Unknown>}
      {file === null && message && <Problem>{message}</Problem>}
    </Section>
  );
}

export default function MediaTab({ report, explanation }: { report: AnalysisResponse; explanation?: Explanation }) {
  const media = report.modules?.media;
  const [file, setFile] = useState<File | null>(() => uploadFor(report.case_id) || null);
  const preview = useObjectUrl(file?.type.startsWith('video/') ? file : null);
  const checks = (explanation?.checks || []).filter(check => check.module === 'media');
  const classifier = checks.find(check => check.benchmark);

  useEffect(() => setFile(uploadFor(report.case_id) || null), [report.case_id]);

  if (!media || media.status === 'not_applicable') {
    return <Unknown title="No media was checked">{media?.limitations?.[0] || 'This case has no image or video.'} A missing check says nothing about the content.</Unknown>;
  }

  return (
    <>
      <div className="module-head">
        <div>
          <p className="module-status">{STATUS_WORDS[media.status]}</p>
          <Meter value={media.score} label={media.score != null ? 'Model signal' : undefined} />
          <p className="fineprint">{confidenceText(media.confidence)}. The score is uncalibrated, so it isn't a probability.</p>
        </div>
        {isQuietMedia(report) && (
          <Caveat>
            <strong>A low or inconclusive result doesn't show the media is authentic.</strong>
            <p>At its current settings this detector flags very few fakes.</p>
          </Caveat>
        )}
      </div>

      {preview && <video className="video-preview" src={preview} controls muted />}

      <Section title="Evidence from this file" kind="observed">
        {media.evidence.length ? <Lines items={media.evidence} /> : <Unknown>No evidence came back.</Unknown>}
      </Section>

      {checks.length > 0 && (
        <Section title="What ran">
          <div className="media-checks">
            {checks.map(check => (
              <article key={check.check_id}>
                <h3>{check.label}</h3>
                <p className="check-result">{check.result}</p>
                <p className="fineprint">{benchmarkSentence(check.benchmark)}</p>
              </article>
            ))}
          </div>
        </Section>
      )}

      {classifier?.benchmark && (
        <Section title="How this detector did when tested" kind="observed" lead={classifier.benchmark.applies_to}>
          <BenchmarkDots benchmark={classifier.benchmark} />
          <p className="fineprint">
            {benchmarkSentence(classifier.benchmark)} {classifier.benchmark.measured_at ? `Measured ${classifier.benchmark.measured_at}.` : ''} It wasn't tested on face swaps.
          </p>
        </Section>
      )}

      <HeatmapPanel caseId={report.case_id} file={file} onFile={setFile} />
      <Limits items={media.limitations} open />
    </>
  );
}
