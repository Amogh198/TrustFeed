import { MATCH_WORDING, platformName, utc, words } from '../lib/format';
import type { Coverage as CoverageData } from '../types';
import { SafeLink, Section, Tape, Unknown } from '../ui/ui';

export function CoverageTable({ coverage }: { coverage: CoverageData }) {
  return (
    <Section
      title="Where this looked"
      kind="observed"
      lead="Public search doesn't return every post. Finding nothing doesn't show the content wasn't shared."
    >
      {coverage.synthetic && <Tape>Replayed synthetic posts on invented platforms. No real platform was searched</Tape>}
      <div className="coverage">
        <table className="table">
          <thead><tr><th>Platform</th><th>Result</th><th>Matching posts</th></tr></thead>
          <tbody>
            {(coverage.platforms || []).map(item => (
              <tr key={item.platform}>
                <td>
                  {item.label || platformName(item.platform)}
                  {item.notes?.length ? <small>{item.notes.join(' ')}</small> : null}
                </td>
                <td>{words(item.status)}</td>
                <td>{item.matching_posts}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {coverage.not_connected?.length ? (
          <Unknown title="Not connected">
            <ul className="lines">
              {coverage.not_connected.map(item => <li key={item.platform}><strong>{words(item.platform)}: </strong>{item.reason}</li>)}
            </ul>
          </Unknown>
        ) : null}
      </div>
      {coverage.account_histories?.read ? (
        <p className="fineprint">To check for repetition, recent public posts of {coverage.account_histories.read} accounts were also read.</p>
      ) : null}
    </Section>
  );
}

export function PostList({ coverage }: { coverage: CoverageData }) {
  const posts = coverage.spread || [];
  return (
    <Section title={`Matching posts in time order (${posts.length})`} kind="observed">
      {posts.length ? (
        <div className="table-scroll">
          <table className="table">
            <thead><tr><th>Time</th><th>Platform</th><th>Account</th><th>Why it matched</th><th title="Platforms don't say when reposts happened">Reposts</th></tr></thead>
            <tbody>
              {posts.slice(0, 100).map(post => (
                <tr key={`${post.platform}-${post.order}`} className={post.earliest_found ? 'is-earliest' : ''}>
                  <td>{utc(post.posted_at)}{post.earliest_found ? <small>Earliest found, not shown to be the source</small> : null}</td>
                  <td>{platformName(post.platform)}</td>
                  <td className="mono"><SafeLink href={post.permalink}>{post.handle}</SafeLink></td>
                  <td>{MATCH_WORDING[post.matched_on] || words(post.matched_on)}</td>
                  <td>{post.repost_count ?? 'Unknown'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {posts.length > 100 && <p className="fineprint">Showing the first 100 of {posts.length} posts. The export has them all.</p>}
        </div>
      ) : <Unknown>No matching posts were found. That doesn't show the content wasn't shared elsewhere.</Unknown>}
    </Section>
  );
}
