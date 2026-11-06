import { Pause, Play, SkipForward } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { platformName, utc, utcClock, words } from '../lib/format';
import { buildView, revealedAt, type GraphView, type PlacedEdge, type PlacedNode } from '../lib/graph';
import type { NetworkPayload } from '../types';
import { Figure, Tape } from '../ui/ui';
import SpreadCanvas, { ROLE_COLOURS } from './SpreadCanvas';
import { useReplay } from './useReplay';

const LEGEND: [string, string][] = [
  ['origin_candidate', 'Earliest found'],
  ['amplifier', 'Amplifier'],
  ['participant', 'Participant'],
  ['target', 'Mentioned account'],
  ['background', 'No signal'],
];

function delay(seconds: number | null | undefined): string {
  if (seconds == null) return 'delay unknown';
  return seconds < 90 ? `${Math.round(seconds)} s apart` : `${Math.round(seconds / 60)} min apart`;
}

function linkReason(edge: PlacedEdge): string {
  if (edge.type === 'mention') return 'Mentioned';
  const parts = Object.entries(edge.signals || {})
    .filter(([, count]) => count > 0)
    .map(([signal, count]) => `${count} ${signal === 'url' ? 'link' : signal}`);
  return `Shared ${parts.join(', ') || 'items'}, ${delay(edge.median_delay_seconds)}`;
}

function Scrubber({ view, position, onSeek, label }: {
  view: GraphView; position: number; onSeek: (value: number) => void; label: string;
}) {
  const peak = Math.max(1, ...view.bins.map(bin => bin.flagged + bin.other));
  const height = 74;
  const width = 960;
  const bar = width / view.bins.length;
  return (
    <div className="scrubber">
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
        {view.bins.map((bin, index) => {
          const done = (index + 0.5) / view.bins.length <= position;
          const other = (bin.other / peak) * (height - 4);
          const flagged = (bin.flagged / peak) * (height - 4);
          return (
            <g key={index} opacity={done ? 1 : 0.32}>
              {bin.other > 0 && <rect x={index * bar + 1} y={height - other} width={bar - 2} height={Math.max(other, 4)} fill="#8f86c9" />}
              {bin.flagged > 0 && <rect x={index * bar + 1} y={height - other - flagged} width={bar - 2} height={Math.max(flagged, 4)} fill="#ff4f8b" />}
            </g>
          );
        })}
      </svg>
      <span className="scrubber-head" style={{ left: `${position * 100}%` }} aria-hidden="true" />
      <input
        type="range" min={0} max={1000} step={1}
        value={Math.round(position * 1000)}
        aria-label="Time in the spread"
        aria-valuetext={label}
        onChange={event => onSeek(Number(event.target.value) / 1000)}
      />
    </div>
  );
}

function AccountPanel({ node, view, onSelect, time }: {
  node: PlacedNode; view: GraphView; onSelect: (node: PlacedNode | null) => void; time: number;
}) {
  const links = (view.linked.get(node.id) || []).filter(edge => edge.type !== 'weak_co_share' && edge.at <= time);
  const strongest = [...links].sort((a, b) => (b.weight || 0) - (a.weight || 0)).slice(0, 6);
  return (
    <aside className="account" aria-live="polite">
      <header>
        <strong className="mono">{node.handle}</strong>
        <button type="button" className="text-button" onClick={() => onSelect(null)}>Close</button>
      </header>
      <p className="account-role" style={{ color: ROLE_COLOURS[node.role] }}>{node.role_label}</p>
      <dl>
        <div><dt>First seen in this data</dt><dd>{utc(node.appears_at)}</dd></div>
        <div><dt>Posts read</dt><dd>{node.post_count}</dd></div>
        <div><dt>Platforms</dt><dd>{node.platforms?.map(platformName).join(', ') || 'Unknown'}</dd></div>
        <div><dt>Group</dt><dd>{node.cluster_id ? `${words(node.cluster_id)}${node.in_flagged_cluster ? ', flagged for review' : ', not flagged'}` : 'Not in a group'}</dd></div>
      </dl>
      {strongest.length > 0 && <>
        <h3>Strongest links so far ({links.length})</h3>
        <ul className="account-links">
          {strongest.map(edge => {
            const other = edge.a.id === node.id ? edge.b : edge.a;
            return (
              <li key={edge.id}>
                <button type="button" className="text-button mono" onClick={() => onSelect(other)}>{other.handle}</button>
                <span>{linkReason(edge)}{edge.cross_platform ? ', across platforms' : ''}</span>
              </li>
            );
          })}
        </ul>
      </>}
      <p className="fineprint">Posting the same items close together doesn't show who controls an account, or why it posted.</p>
    </aside>
  );
}

export default function SpreadStage({ graph, autoScroll = false, autoplay = false, onNodeClick, showLinkReasons = false }: {
  graph: NetworkPayload | null | undefined;
  autoScroll?: boolean;
  autoplay?: boolean;
  onNodeClick?: (node: PlacedNode) => void;
  showLinkReasons?: boolean;
}) {
  const view = useMemo(() => buildView(graph), [graph]);
  const [showWeak, setShowWeak] = useState(false);
  const [selected, setSelected] = useState<PlacedNode | null>(null);
  const { position, playing, toggle, seek } = useReplay(16_000, autoplay, view);

  useEffect(() => setSelected(null), [view]);

  // Open with the graph, its controls and the time bar all on screen, ready to present.
  const stageRef = useRef<HTMLDivElement>(null);
  const scrollIntoPlace = Boolean(view) && autoScroll;
  useEffect(() => {
    if (!scrollIntoPlace || !stageRef.current) return;
    const bars = [...document.querySelectorAll<HTMLElement>('.topbar, .tabs')].reduce((sum, bar) => sum + bar.offsetHeight, 0);
    window.scrollTo({ top: stageRef.current.getBoundingClientRect().top + window.scrollY - bars });
  }, [scrollIntoPlace]);

  if (!view) return null;

  const time = view.start + (view.end - view.start) * position;
  const counts = revealedAt(view, time, showWeak);
  const nextBurst = view.bursts.find(stop => stop > time + 1000) ?? view.bursts[0];
  const earliest = view.nodes.find(node => node.role === 'origin_candidate');
  const clock = utc(new Date(time).toISOString());
  const description = `Spread graph at ${clock}: ${counts.accounts} accounts and ${counts.links} links are showing.`;

  return (
    <div className="stage" ref={stageRef}>
      {view.synthetic && <Tape>Synthetic data: invented accounts and posts, not evidence of real activity</Tape>}
      <div className="stage-body">
        <div className="stage-canvas">
          <SpreadCanvas
            view={view}
            time={time}
            showWeak={showWeak}
            selectedId={selected?.id}
            onSelect={node => (node && onNodeClick ? onNodeClick(node) : setSelected(node))}
            label={description}
            edgeReason={showLinkReasons ? linkReason : undefined}
            nodeHint={onNodeClick ? 'Select to open the media checks' : undefined}
          />
          <div className="stage-readout" aria-live="off">
            <Figure value={counts.accounts} label={`of ${view.nodes.length} accounts`} />
            <Figure value={counts.flagged} label="in a flagged group" />
            <Figure value={counts.links} label="links" />
          </div>
          {selected && <AccountPanel node={selected} view={view} time={time} onSelect={setSelected} />}
        </div>
        <div className="stage-controls">
          <button type="button" className="button button-primary" onClick={toggle}>
            {playing ? <Pause size={16} aria-hidden="true" /> : <Play size={16} aria-hidden="true" />}
            {playing ? 'Pause' : position >= 1 ? 'Replay the spread' : 'Play the spread'}
          </button>
          <button
            type="button" className="button"
            disabled={nextBurst === undefined}
            onClick={() => nextBurst !== undefined && seek((nextBurst - view.start) / (view.end - view.start))}
          >
            <SkipForward size={16} aria-hidden="true" />Next burst
          </button>
          <output className="stage-clock"><b>{utcClock(time)}</b><span>{utc(new Date(time).toISOString()).split(',')[0]}</span></output>
          <label className="check"><input type="checkbox" checked={showWeak} onChange={event => setShowWeak(event.target.checked)} />Show one-item links</label>
          {earliest && (
            <button type="button" className="text-button" onClick={() => setSelected(earliest)}>Find the earliest account</button>
          )}
        </div>
        <Scrubber view={view} position={position} onSeek={seek} label={clock} />
        <div className="stage-foot">
          <ul className="legend">
            {LEGEND.map(([role, name]) => (
              <li key={role}><i className={role === 'target' ? 'diamond' : ''} style={{ background: ROLE_COLOURS[role] }} />{name}</li>
            ))}
            <li><i className="dashed" />Across platforms</li>
            <li><i className="bar-flagged" />Posts from a flagged group</li>
            <li><i className="bar-other" />Other posts</li>
          </ul>
          {(view.leftOut > 0 || view.noActivity > 0) && (
            <p className="fineprint">
              {view.leftOut > 0 ? `${view.leftOut} lower-activity accounts are left out to keep this readable. ` : ''}
              {view.noActivity > 0 ? `${view.noActivity} accounts took no part in this spread and aren't drawn.` : ''}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
