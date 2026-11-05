import React, { useMemo, useState } from 'react';
import { LoaderCircle, Pause, Play } from 'lucide-react';
import { safeHttpUrl } from './api.js';

const ROLE_COLORS = {
  origin_candidate: '#c2571a',
  amplifier: '#b3261e',
  participant: '#e08a2c',
  target: '#6a4fb3',
  background: '#9aa5a0',
};
const ROLE_NAMES = {
  origin_candidate: 'Earliest found',
  amplifier: 'Amplifier',
  participant: 'Participant',
  target: 'Target',
  background: 'Background',
};
const MATCH_WORDING = {
  link: 'Carries the submitted link',
  page_link: 'Links to a page where the image was found, and may be about something else on it',
  hashtag: 'Uses the hashtag, which shows a shared topic, not shared content',
  text: 'Contains the submitted text',
};
const MAX_NODES = 90;
const WIDTH = 760;
const HEIGHT = 440;

function hash(text) {
  let value = 7;
  for (const character of text) value = (value * 31 + character.charCodeAt(0)) % 1000003;
  return value;
}

/**
 * Place flagged groups together in the middle, their most connected members at the centre, and
 * everyone else in an outer ring. It is computed from the data alone, so the picture is stable.
 */
function layOut(nodes) {
  const positions = new Map();
  const groups = new Map();
  const outer = [];
  for (const node of nodes) {
    if (node.in_flagged_cluster) {
      if (!groups.has(node.cluster_id)) groups.set(node.cluster_id, []);
      groups.get(node.cluster_id).push(node);
    } else if (node.role !== 'target') outer.push(node);
  }
  const groupList = [...groups.values()];
  const targets = nodes.filter(node => node.role === 'target' && !node.in_flagged_cluster);
  groupList.forEach((members, index) => {
    const angle = (index / Math.max(groupList.length, 1)) * Math.PI * 2;
    const spread = groupList.length > 1 ? 150 : 0;
    const centre = { x: WIDTH / 2 + Math.cos(angle) * spread, y: HEIGHT / 2 + Math.sin(angle) * spread * 0.6 };
    const ordered = [...members].sort((a, b) => (b.role === 'origin_candidate') - (a.role === 'origin_candidate') || (b.weighted_degree || 0) - (a.weighted_degree || 0) || a.id.localeCompare(b.id));
    ordered.forEach((node, position) => {
      const radius = 15 * Math.sqrt(position);
      const turn = position * 2.39996;
      positions.set(node.id, { x: centre.x + Math.cos(turn) * radius, y: centre.y + Math.sin(turn) * radius });
    });
  });
  targets.forEach((node, index) => {
    positions.set(node.id, { x: WIDTH / 2 + 150, y: HEIGHT / 2 + (index - (targets.length - 1) / 2) * 34 });
  });
  const ordered = [...outer].sort((a, b) => hash(a.id) - hash(b.id));
  ordered.forEach((node, index) => {
    const angle = (index / Math.max(ordered.length, 1)) * Math.PI * 2;
    const band = groupList.length || targets.length ? 1 : 0.8;
    const wobble = 1 - (hash(node.id) % 12) / 100;
    positions.set(node.id, { x: WIDTH / 2 + Math.cos(angle) * (WIDTH / 2 - 22) * band * wobble, y: HEIGHT / 2 + Math.sin(angle) * (HEIGHT / 2 - 22) * band * wobble });
  });
  return positions;
}

function importance(node) {
  return (node.role === 'background' ? 0 : 1000) + (node.weighted_degree || 0);
}

function SpreadGraph({ graph }) {
  const [showWeak, setShowWeak] = useState(false);
  const [selected, setSelected] = useState(null);
  const [position, setPosition] = useState(100);
  const [playing, setPlaying] = useState(false);

  const view = useMemo(() => {
    const placed = (graph?.nodes || []).filter(node => node.appears_at);
    const nodes = [...placed].sort((a, b) => importance(b) - importance(a)).slice(0, MAX_NODES);
    const ids = new Set(nodes.map(node => node.id));
    const edges = (graph?.edges || []).filter(edge => ids.has(edge.source) && ids.has(edge.target));
    const times = [...nodes.map(node => Date.parse(node.appears_at)), ...edges.map(edge => Date.parse(edge.first_seen_at))].filter(Number.isFinite);
    return {
      nodes,
      edges,
      positions: layOut(nodes),
      hidden: placed.length - nodes.length,
      noActivity: (graph?.nodes || []).length - placed.length,
      start: times.length ? Math.min(...times) : 0,
      end: times.length ? Math.max(...times) : 0,
    };
  }, [graph]);

  React.useEffect(() => {
    if (!playing) return undefined;
    const timer = window.setInterval(() => {
      setPosition(current => {
        if (current >= 100) { setPlaying(false); return 100; }
        return Math.min(100, current + 2);
      });
    }, 180);
    return () => window.clearInterval(timer);
  }, [playing]);

  if (!view.nodes.length) return <p>No accounts took part in the spread found for this case.</p>;

  const now = view.start + ((view.end - view.start) * position) / 100;
  const shown = time => Date.parse(time) <= now;
  const visibleEdges = view.edges.filter(edge => shown(edge.first_seen_at) && (showWeak || edge.type !== 'weak_co_share'));
  const visibleNodes = view.nodes.filter(node => shown(node.appears_at));
  const synthetic = view.nodes.some(node => node.synthetic);

  return <div className="spread-graph">
    {synthetic && <p className="graph-synthetic">Synthetic data: invented accounts and posts, not evidence of real activity.</p>}
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={`Spread graph showing ${visibleNodes.length} accounts and ${visibleEdges.length} links at the selected time`}>
      {visibleEdges.map(edge => {
        const a = view.positions.get(edge.source);
        const b = view.positions.get(edge.target);
        const weak = edge.type === 'weak_co_share';
        const mention = edge.type === 'mention';
        return <line key={edge.id} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={mention ? '#6a4fb3' : '#5b6b64'} strokeOpacity={weak ? 0.18 : mention ? 0.45 : 0.4} strokeWidth={weak ? 0.6 : Math.min(3, 0.8 + (edge.weight || 1) * 0.3)} strokeDasharray={edge.cross_platform ? '5 3' : undefined} />;
      })}
      {visibleNodes.map(node => {
        const place = view.positions.get(node.id);
        const radius = node.role === 'background' ? 4 : node.role === 'origin_candidate' ? 9 : Math.min(8, 5 + (node.weighted_degree || 0) * 0.02);
        const active = selected?.id === node.id;
        return <circle key={node.id} cx={place.x} cy={place.y} r={radius} fill={ROLE_COLORS[node.role] || ROLE_COLORS.background} stroke={active ? '#111' : '#fff'} strokeWidth={active ? 2.5 : 1} tabIndex="0" role="button" aria-label={`${ROLE_NAMES[node.role] || node.role}: ${node.handle}`} onClick={() => setSelected(node)} onKeyDown={event => { if (event.key === 'Enter') setSelected(node); }}><title>{node.handle}</title></circle>;
      })}
    </svg>
    <div className="graph-controls">
      <button type="button" className="button secondary" onClick={() => { if (position >= 100) setPosition(0); setPlaying(value => !value); }}>{playing ? <Pause size={14} /> : <Play size={14} />}{playing ? 'Pause' : 'Play spread'}</button>
      <label>Time<input type="range" min="0" max="100" value={position} onChange={event => { setPlaying(false); setPosition(Number(event.target.value)); }} /></label>
      <span className="graph-time">{view.end ? new Date(now).toLocaleString() : ''}</span>
      <label className="graph-toggle"><input type="checkbox" checked={showWeak} onChange={event => setShowWeak(event.target.checked)} />Show one-item links</label>
    </div>
    <div className="graph-legend">{Object.entries(ROLE_NAMES).map(([role, name]) => <span key={role}><i style={{ background: ROLE_COLORS[role] }} />{name}</span>)}<span><i className="dash" />Different platforms</span></div>
    <p className="graph-count">Showing {visibleNodes.length} of {view.nodes.length} accounts and {visibleEdges.length} links.{view.hidden > 0 ? ` ${view.hidden} lower-activity accounts are left out to keep this readable.` : ''}{view.noActivity > 0 ? ` ${view.noActivity} accounts had no part in the spread.` : ''}</p>
    {selected && <div className="graph-detail"><strong>{selected.handle}</strong><span>{selected.role_label}</span><span>{selected.platforms?.join(', ') || 'Platform unknown'} · first seen in this data {selected.appears_at}</span><span>{selected.post_count} posts · {selected.cluster_id ? `group ${selected.cluster_id}` : 'not in a group'}</span></div>}
  </div>;
}

function Coverage({ coverage }) {
  const platforms = coverage.platforms || [];
  return <div className="coverage-table">
    {coverage.synthetic && <p className="graph-synthetic">Replayed synthetic posts on invented platforms. No real platform was searched.</p>}
    <h3>Platforms searched</h3>
    <ul className="plain-list">{platforms.map(item => <li key={item.platform}><strong>{item.label}</strong> <span className={`status-chip ${item.status}`}>{item.status.replaceAll('_', ' ')}</span> {item.matching_posts} matching posts{item.notes?.length ? <small>{item.notes.join(' ')}</small> : null}</li>)}</ul>
    {coverage.not_connected?.length ? <><h3>Not connected</h3><ul className="plain-list">{coverage.not_connected.map(item => <li key={item.platform}><strong>{item.platform}</strong><small>{item.reason}</small></li>)}</ul></> : null}
    {coverage.account_histories?.read ? <p className="graph-count">To check for repetition, recent public posts of {coverage.account_histories.read} accounts were also read.</p> : null}
  </div>;
}

function SpreadList({ spread, synthetic }) {
  if (!spread?.length) return <p>No matching posts were found. This does not show the content wasn't shared elsewhere.</p>;
  return <div className="table-wrap"><table className="spread-table"><thead><tr><th>#</th><th>Time</th><th>Platform</th><th>Account</th><th>Why it matched</th><th>Reposts</th></tr></thead><tbody>
    {spread.slice(0, 100).map(post => {
      const link = safeHttpUrl(post.permalink);
      return <tr key={`${post.platform}-${post.order}`}><td>{post.order}</td><td>{post.posted_at}{post.earliest_found ? <span className="label">Earliest found</span> : null}</td><td>{post.platform}</td><td>{link ? <a href={link} target="_blank" rel="noreferrer">{post.handle}</a> : post.handle}</td><td>{MATCH_WORDING[post.matched_on] || post.matched_on}</td><td title="Platforms do not say when reposts happened">{post.repost_count ?? '—'}</td></tr>;
    })}
  </tbody></table>{spread.length > 100 ? <p className="graph-count">Showing the first 100 of {spread.length} posts. The export has them all.</p> : null}{!synthetic ? <p className="graph-count">The earliest post found is only the earliest found. It is not shown to be the source.</p> : null}</div>;
}

export default function NetworkPanel({ graph, coverage, loading }) {
  if (loading) return <div className="loading"><LoaderCircle className="spin" size={18} />Loading spread graph and coverage…</div>;
  return <section className="panel detail-panel"><div className="panel-title"><div><h2>How it spread</h2><p>Accounts, links between them, and what was searched</p></div></div>
    <p className="graph-note">Posting the same items close together is a signal for review. It does not show coordination, automation, identity or intent.</p>
    {coverage === null || coverage === undefined ? <p className="graph-count">No public-post trace ran for this case, so there is no coverage result.</p> : <><Coverage coverage={coverage} /><h3>Matching posts in time order</h3><SpreadList spread={coverage.spread} synthetic={coverage.synthetic} /></>}
    {graph?.nodes?.length ? <><h3>Spread graph</h3><SpreadGraph graph={graph} /></> : null}
  </section>;
}
