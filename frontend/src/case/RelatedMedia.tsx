import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { caseHref } from '../lib/route';
import { MATCH_WORDING, platformName, utc, words } from '../lib/format';
import type { RelatedMedia as RelatedMediaData, RelatedMediaEvent } from '../types';
import { Limits, SafeLink, Section, Tape, Unknown } from '../ui/ui';

const KIND_WORDING: Record<string, string> = {
  exact_copy: 'The same file',
  likely_same_image: 'Likely the same picture, in a different file',
  shares_visible_content: 'Shares visible content. It may be a crop of the same picture, or only share something like a logo',
};

const EVENT_WORDING: Record<string, string> = {
  submitted: 'Checked on this server',
  public_post: 'Public post',
  web_page: 'Web page',
};

function shortId(id: string) {
  return id.length > 12 ? `${id.slice(0, 8)}…` : id;
}

function how(event: RelatedMediaEvent) {
  if (!event.matched_on) return '';
  return MATCH_WORDING[event.matched_on] || words(event.matched_on);
}

/** Other cases holding the same picture, and everything those cases found, as one history. */
export default function RelatedMedia({ caseId }: { caseId: string }) {
  const [data, setData] = useState<RelatedMediaData | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    setData(null);
    setFailed(false);
    api.getRelatedMedia(caseId)
      .then((next: RelatedMediaData) => { if (live) setData(next); })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, [caseId]);

  if (failed) {
    return (
      <Section title="Related media" kind="unknown">
        <Unknown title="Related media didn't load">The rest of this report isn't affected.</Unknown>
      </Section>
    );
  }
  if (!data || data.status !== 'complete') return null;

  return (
    <Section
      title={`Related media (${data.cases.length})`}
      kind="observed"
      lead="Other cases on this account that may hold the same picture, even if it was resized, cropped, captioned, watermarked or recompressed."
    >
      {data.cases.length ? (
        <>
          <div className="table-scroll">
            <table className="table">
              <thead><tr><th>Case</th><th>How it matched</th><th>Checked</th></tr></thead>
              <tbody>
                {data.cases.map(item => (
                  <tr key={item.case_id}>
                    <td className="mono"><a href={caseHref(item.case_id)}>{shortId(item.case_id)}</a></td>
                    <td>
                      {KIND_WORDING[item.kind] || words(item.kind)}
                      {item.through_case_id ? <small>Matched case {shortId(item.through_case_id)}, not this one directly, so check that link</small> : null}
                      {item.agreeing_features ? <small>{item.agreeing_features} small patches of the pictures line up</small> : null}
                      {Object.keys(item.distances || {}).length ? <small>Fingerprint distances: {Object.entries(item.distances || {}).map(([kind, value]) => `${kind} ${value}`).join(', ')}</small> : null}
                    </td>
                    <td>{item.first_seen ? utc(item.first_seen) : 'Unknown'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h3>Combined history, in time order</h3>
          {data.history.some(event => event.synthetic) && <Tape>Includes replayed synthetic posts, not real activity</Tape>}
          <div className="table-scroll">
            <table className="table">
              <thead><tr><th>Time</th><th>What</th><th>Where</th><th>Why it's listed</th><th>Case</th></tr></thead>
              <tbody>
                {data.history.map((event, index) => (
                  <tr key={`${event.case_id}-${index}`} className={event.earliest_found ? 'is-earliest' : ''}>
                    <td>
                      {event.at ? utc(event.at) : 'No date found'}
                      {event.earliest_found ? <small>Earliest found, not shown to be the source</small> : null}
                    </td>
                    <td>{EVENT_WORDING[event.kind] || words(event.kind)}</td>
                    <td className="mono">
                      {event.platform ? `${platformName(event.platform)}: ` : ''}
                      {event.url ? <SafeLink href={event.url}>{event.label}</SafeLink> : event.label}
                    </td>
                    <td>{how(event)}</td>
                    <td className="mono"><a href={caseHref(event.case_id)}>{shortId(event.case_id)}</a></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <Unknown title="No related media found">
          Compared with {data.compared_cases} other {data.compared_cases === 1 ? 'case' : 'cases'} on this account. That doesn't show this picture hasn't been reposted elsewhere.
        </Unknown>
      )}
      <Limits items={data.limitations} />
    </Section>
  );
}
