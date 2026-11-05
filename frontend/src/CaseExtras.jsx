import React, { useEffect, useState } from 'react';
import { LoaderCircle, Sparkles } from 'lucide-react';
import { api } from './api.js';

function Lines({ items }) {
  return <ul>{items.map((item, index) => <li key={index}>{item}</li>)}</ul>;
}

function asLines(value) {
  if (Array.isArray(value)) return value;
  return value ? [value] : [];
}

function benchmarkText(benchmark) {
  if (!benchmark) return 'Not measured';
  const { flagged_fake: flaggedFake, n_fake: fakes, flagged_real: flaggedReal, n_real: reals, auc, applies_to: appliesTo } = benchmark;
  const parts = [];
  if (fakes) parts.push(`Flagged ${flaggedFake} of ${fakes} fakes`);
  if (reals) parts.push(`wrongly flagged ${flaggedReal} of ${reals} real images`);
  if (auc != null) parts.push(`AUC ${auc}`);
  const measured = parts.length ? `${parts.join(', ')}, on the benchmark's test set only.` : 'Measured; see the results file.';
  return appliesTo ? `${measured} ${appliesTo}` : measured;
}

export function ExplanationPanel({ data, loading }) {
  if (loading) return <div className="loading"><LoaderCircle className="spin" size={18} />Loading explanation…</div>;
  if (!data) return null;
  return <section className="panel detail-panel"><div className="panel-title"><div><h2>Why this result</h2><p>What each check did, what it found and how far to trust it</p></div></div>
    <div className="explain-grid">
      <div><h3>Submitted</h3><Lines items={data.what_was_submitted} /></div>
      <div><h3>Raises concern</h3>{data.supports.length ? <Lines items={data.supports} /> : <p>No check raised concern. That does not show the content is genuine.</p>}</div>
      {data.refutes.length ? <div><h3>Found nothing</h3><Lines items={data.refutes} /></div> : null}
    </div>
    <div className="check-list">{data.checks.map(check => <details key={check.check_id}><summary><strong>{check.label}</strong><span>{check.result}</span></summary>
      <div className="check-body">{asLines(check.reasoning).length ? <><h4>Why</h4><Lines items={asLines(check.reasoning)} /></> : null}<h4>How far to trust it</h4><p>{benchmarkText(check.benchmark)}</p>{check.limitations?.length ? <><h4>What it can't show</h4><Lines items={check.limitations} /></> : null}</div>
    </details>)}</div>
    {data.missing_checks.length ? <><h3>Not run for this case</h3><ul>{data.missing_checks.map(item => <li key={item.module}><strong>{item.module}</strong>: {item.reason}</li>)}</ul></> : null}
  </section>;
}

export function HeatmapPanel({ file }) {
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    if (!file) return undefined;
    const address = URL.createObjectURL(file);
    setPreview(address);
    return () => URL.revokeObjectURL(address);
  }, [file]);

  if (!file || !file.type.startsWith('image/')) return null;

  async function run() {
    setWorking(true);
    setMessage('Covering each part of the image in turn. This takes about 10 to 60 seconds.');
    try {
      const response = await api.heatmap(file);
      setResult(response);
      setMessage('');
    } catch (error) { setMessage(error.message); } finally { setWorking(false); }
  }

  return <section className="panel detail-panel"><div className="panel-title"><div><h2>Where the model's score changed</h2><p>This shows sensitivity, not proof of editing.</p></div>{!result && <button type="button" className="button secondary" disabled={working} onClick={run}>{working ? <LoaderCircle className="spin" size={15} /> : <Sparkles size={15} />}{working ? 'Working…' : 'Generate heatmap'}</button>}</div>
    {message && <p className="graph-count">{message}</p>}
    {result && <>{result.png_base64 && preview ? <div className="heatmap-stage"><img src={preview} alt="Your uploaded image" /><img className="overlay" src={`data:image/png;base64,${result.png_base64}`} alt="Colour grid showing where covering the image moved the model's score" /></div> : null}
      <p>{result.reasoning}</p>{result.png_base64 ? <p className="graph-count">Red areas were raising the score and blue areas were lowering it.</p> : null}{result.limitations?.length ? <ul>{result.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul> : null}</>}
  </section>;
}
