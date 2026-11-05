import { useEffect, useMemo, useState } from 'react';
import { api } from '../api.js';
import { RISK_LEVELS, utc } from '../lib/format';
import { caseHref } from '../lib/route';
import type { CaseHistory, RiskLevel } from '../types';
import { Loading, Problem, Unknown } from '../ui/ui';

const KINDS: [string, string][] = [['', 'Any'], ['media', 'Media'], ['link', 'Links'], ['text', 'Text'], ['scam', 'Scam signs'], ['campaign', 'Campaigns']];

export default function Cases() {
  const [risk, setRisk] = useState<RiskLevel | ''>('');
  const [query, setQuery] = useState('');
  const [searched, setSearched] = useState('');
  const [kind, setKind] = useState('');
  const [history, setHistory] = useState<CaseHistory | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    setHistory(null);
    setError('');
    api.getHistory(risk, 100, searched, kind)
      .then(data => { if (live) setHistory(data); })
      .catch(problem => { if (live) setError(problem.message); });
    return () => { live = false; };
  }, [risk, searched, kind]);

  // The server searches whole reports, so wait for a pause in typing.
  useEffect(() => {
    const timer = window.setTimeout(() => setSearched(query.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [query]);

  const shown = useMemo(() => history?.cases || [], [history]);

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
          <input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Words in a report" />
        </label>
        <div className="chips" role="group" aria-label="Filter by what was found">
          {KINDS.map(([value, name]) => (
            <button key={value} type="button" aria-pressed={kind === value} onClick={() => setKind(value)}>{name}</button>
          ))}
        </div>
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
