import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { RISK_LEVELS, scoreText, utc } from '../lib/format';
import { caseHref } from '../lib/route';
import type { Overview as OverviewData } from '../types';
import { Figure, Loading, Problem, Section, Unknown } from '../ui/ui';

/** Counts come from saved results on this server. Replays are counted apart from real checks. */
export default function Overview() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    api.getOverview()
      .then(result => { if (live) setData(result); })
      .catch(problem => { if (live) setError(problem.message); });
    return () => { live = false; };
  }, []);

  if (error) return <div className="page"><Problem>{error}</Problem></div>;
  if (!data) return <div className="page"><Loading>Counting saved investigations</Loading></div>;
  const largest = Math.max(1, ...Object.values(data.risk_distribution));

  return (
    <div className="page">
      <header className="page-head">
        <h1>Overview</h1>
        <p>
          What this server has checked so far. These are counts of triage signals, not findings of fact.
          {data.replays > 0 && ` ${data.replays} invented replay${data.replays === 1 ? ' is' : 's are'} left out of every figure.`}
        </p>
      </header>
      {data.read_limit_reached && <p className="fineprint">Only the newest {data.investigations + data.replays} of {data.total_saved} saved cases were read.</p>}

      <div className="overview-figures">
        <Figure value={data.investigations} label="Investigations" />
        <Figure value={data.media_assessments.signals} label="Media with signals" small={`${data.media_assessments.no_strong_signal} no strong signal, ${data.media_assessments.unavailable} not assessed`} />
        <Figure value={data.suspicious_urls.length} label="Suspicious links" />
        <Figure value={data.claims_to_verify.length} label="Claims to verify" />
        <Figure value={data.flagged_campaigns.length} label="Flagged campaigns" />
      </div>

      <div className="findings-grid">
        <Section title="Risk distribution" kind="estimate">
          {data.investigations ? (
            <ul className="risk-bars">
              {[...RISK_LEVELS].map(level => (
                <li key={level}>
                  <a href="#/cases" className={`risk risk-${level}`}>{level}</a>
                  <span className="risk-bar"><span style={{ width: `${(data.risk_distribution[level] / largest) * 100}%` }} /></span>
                  <strong>{data.risk_distribution[level]}</strong>
                </li>
              ))}
            </ul>
          ) : <Unknown title="Nothing checked yet"><a href="#/">Check something</a> to see it here.</Unknown>}
        </Section>

        <Section title="Recent high-risk alerts" kind="estimate">
          {data.recent_high_risk.length ? (
            <ul className="overview-list">
              {data.recent_high_risk.map(item => (
                <li key={item.case_id}>
                  <span className={`risk risk-${item.level}`}>{item.level}</span>
                  <a href={caseHref(item.case_id)}>{item.summary}</a>
                  <small>{utc(item.created_at)}</small>
                </li>
              ))}
            </ul>
          ) : <p>No saved case reached high or critical. That doesn't show the others are safe.</p>}
        </Section>

        <Section title="Suspicious links" kind="observed">
          {data.suspicious_urls.length ? (
            <ul className="overview-list">
              {data.suspicious_urls.map(item => (
                <li key={`${item.case_id}-${item.host}`}>
                  <a className="mono" href={caseHref(item.case_id, 'text')}>{item.host}</a>
                  <small>{item.signs} warning sign{item.signs === 1 ? '' : 's'}</small>
                </li>
              ))}
            </ul>
          ) : <p>No saved link showed a warning sign. No threat list has been consulted.</p>}
        </Section>

        <Section title="Claims to verify" kind="unknown">
          {data.claims_to_verify.length ? (
            <ul className="overview-list">
              {data.claims_to_verify.map((item, index) => (
                <li key={`${item.case_id}-${index}`}>
                  <a href={caseHref(item.case_id, 'text')}>{item.text}</a>
                  <small>{item.verdict.replace('_', ' ')}</small>
                </li>
              ))}
            </ul>
          ) : <p>No saved claim is waiting to be checked.</p>}
        </Section>

        <Section title="Flagged campaigns" kind="estimate" lead="Groups of accounts whose timing was more than chance in the posts read. This doesn't show that they're coordinating.">
          {data.flagged_campaigns.length ? (
            <ul className="overview-list">
              {data.flagged_campaigns.map(item => (
                <li key={item.case_id}>
                  <a href={caseHref(item.case_id, 'spread')}>Case {item.case_id.slice(0, 8)}</a>
                  <small>Score {scoreText(item.score)} out of 100</small>
                </li>
              ))}
            </ul>
          ) : <p>No saved trace flagged a group of accounts.</p>}
        </Section>
      </div>
    </div>
  );
}
