import { utc, words } from '../lib/format';
import type { AnalysisResponse, ProvenanceReport } from '../types';
import { Caveat, Limits, Loading, SafeLink, Section, Tape, Unknown } from '../ui/ui';

export default function SourceTab({ report, data, loading }: {
  report: AnalysisResponse; data?: ProvenanceReport; loading: boolean;
}) {
  if (!data) {
    if (loading) return <Loading>Opening the source search report</Loading>;
    return <Unknown title="The source search report didn't load">Reload the page to try again.</Unknown>;
  }
  if (data.status !== 'complete') {
    const reason = report.modules?.provenance?.limitations?.[0] || data.limitations?.[0];
    return (
      <Unknown title={data.status === 'unavailable' ? "The source search couldn't run" : 'No source search ran'}>
        <p>{reason}</p>
        <p>A source search needs an uploaded image, the opt-in box ticked, and a provider key on the server.</p>
      </Unknown>
    );
  }
  const earliest = data.earliest_found;
  const sorted = [...data.appearances].sort((a, b) => {
    if (!a.observed_at) return 1;
    if (!b.observed_at) return -1;
    return a.observed_at.localeCompare(b.observed_at);
  });
  return (
    <>
      {data.synthetic && <Tape>Synthetic: these pages and dates are invented</Tape>}
      {data.replay && !data.synthetic && <Tape>Replay: recorded search results, not a live search</Tape>}
      <Caveat>
        <strong>{earliest ? `Earliest appearance found: ${utc(earliest.observed_at)}` : 'No dated appearance was found'}</strong>
        <p>{earliest?.caveat || 'Finding no date says nothing about when this image first appeared.'}</p>
      </Caveat>
      <Section title={`Pages it appeared on (${sorted.length})`} kind="observed" lead="A search result says where an image was found. It says nothing about whether the image is authentic.">
        {sorted.length ? (
          <ol className="appearances">
            {sorted.map(item => (
              <li key={item.id} className={item.id === earliest?.appearance_id ? 'is-earliest' : ''}>
                <time>{utc(item.observed_at)}</time>
                <div>
                  <SafeLink href={item.page_url}>{item.page_title || item.page_url || 'Untitled page'}</SafeLink>
                  <p className="fineprint">
                    {words(item.match_type)} match{item.phash_distance != null ? `, image distance ${item.phash_distance}` : ''}, {words(item.platform).toLowerCase()} page, from {words(item.provider)}{item.frame_timestamp_s != null ? `, found using the frame at ${item.frame_timestamp_s.toFixed(1)}s` : ''}
                  </p>
                  <p className="fineprint">{item.date_evidence ? `Date from: ${item.date_evidence}` : 'No evidence for a date.'}</p>
                </div>
              </li>
            ))}
          </ol>
        ) : <Unknown>No pages were found. Search services only cover what they've indexed.</Unknown>}
      </Section>
      <Section title="Services searched" kind="observed">
        <table className="table">
          <thead><tr><th>Service</th><th>Result</th><th>Pages</th><th>Limit</th></tr></thead>
          <tbody>
            {data.providers.map(provider => (
              <tr key={provider.name}>
                <td>{words(provider.name)}</td>
                <td>{words(provider.status)}</td>
                <td>{provider.result_count ?? 'None'}</td>
                <td>{provider.limitation || 'None given'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.phash && <p className="fineprint">Perceptual hash <span className="mono">{data.phash}</span>{data.searched_at ? `, searched ${utc(data.searched_at)}` : ''}</p>}
      </Section>
      <Limits items={data.limitations} open />
    </>
  );
}
