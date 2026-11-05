import { useEffect, useMemo, useState } from 'react';
import { api } from '../api.js';
import { RISK_LEVELS, utc } from '../lib/format';
import { caseHref } from '../lib/route';
import type { CaseHistory, RiskLevel } from '../types';
import { Loading, Problem, Unknown } from '../ui/ui';

export default function Cases() {
  const [risk, setRisk] = useState<RiskLevel | ''>('');
  const [query, setQuery] = useState('');
  const [history, setHistory] = useState<CaseHistory | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    setHistory(null);
    setError('');
    api.getHistory(risk, 100)
      .then(data => { if (live) setHistory(data); })
      .catch(problem => { if (live) setError(problem.message); });
    return () => { live = false; };
  }, [risk]);

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const cases = history?.cases || [];
    return needle ? cases.filter(item => `${item.case_id} ${item.summary}`.toLowerCase().includes(needle)) : cases;
  }, [history, query]);

  return (
    <div className="page">
      <header className="page-head">
        <h1>Saved cases</h1>
        <p>Results saved by this server. Uploaded files aren't kept, only what was found in them.</p>
      </header>
      <div className="filters">
        <div className="chips" role="group" aria-label="Filter by risk">
          <button type="button" aria-pressed={risk === ''} onClick={() => setRisk('')}>All</button>
          {RISK_LEVELS.map(level => (
            <button key={level} type="button" className={`chip-${level}`} aria-pressed={risk === level} onClick={() => setRisk(level)}>{level}</button>
          ))}
        </div>
        <label className="field field-inline">Search
          <input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Case id or summary" />
        </label>
      </div>
      {error && <Problem>{error}</Problem>}
      {!history && !error && <Loading>Opening saved cases</Loading>}
      {history && (shown.length ? (
        <div className="table-scroll">
          <table className="table table-cases">
            <thead><tr><th>Risk</th><th>Summary</th><th>Saved</th><th>Data</th></tr></thead>
            <tbody>
              {shown.map(item => (
                <tr key={item.case_id}>
                  <td><span className={`risk risk-${item.overall_risk}`}>{item.overall_risk}</span></td>
                  <td><a href={caseHref(item.case_id)}>{item.summary}</a><small className="mono">{item.case_id}</small></td>
                  <td>{utc(item.created_at)}</td>
                  <td>{item.is_replay ? <span className="tag-replay" title={item.replay_label || undefined}>Replay, invented</span> : 'Submitted'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="fineprint">Showing {shown.length} of {history.total} saved {risk ? `${risk} ` : ''}cases.</p>
        </div>
      ) : <Unknown title="No cases match">Change the filter, or <a href="#/">check something new</a>.</Unknown>)}
    </div>
  );
}
