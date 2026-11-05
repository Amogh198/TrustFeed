import {
  forceCollide, forceLink, forceManyBody, forceRadial, forceSimulation, forceX, forceY,
  type SimulationLinkDatum, type SimulationNodeDatum,
} from 'd3-force';
import type { GraphEdge, GraphNode, NetworkPayload } from '../types';

export interface PlacedNode extends GraphNode, SimulationNodeDatum {
  x: number;
  y: number;
  at: number;
  rank: number;
  radius: number;
}

export interface PlacedEdge extends GraphEdge {
  a: PlacedNode;
  b: PlacedNode;
  at: number;
}

export interface Bin {
  at: number;
  flagged: number;
  other: number;
}

export interface GraphView {
  nodes: PlacedNode[];
  edges: PlacedEdge[];
  byId: Map<string, PlacedNode>;
  linked: Map<string, PlacedEdge[]>;
  start: number;
  end: number;
  bins: Bin[];
  bursts: number[];
  leftOut: number;
  noActivity: number;
  synthetic: boolean;
  bounds: { minX: number; maxX: number; minY: number; maxY: number };
}

const MAX_NODES = 420;
const BIN_COUNT = 96;

function importance(node: GraphNode): number {
  return (node.role === 'background' ? 0 : 1000) + (node.weighted_degree || 0);
}

function nodeRadius(node: GraphNode): number {
  if (node.role === 'origin_candidate') return 8;
  if (node.role === 'target') return 6.5;
  if (node.role === 'background') return 2.6;
  return Math.min(7, 3.6 + (node.weighted_degree || 0) * 0.025);
}

function spreadHash(text: string): number {
  let value = 7;
  for (const character of text) value = (value * 31 + character.charCodeAt(0)) % 1000003;
  return value;
}

/** Runs the layout to rest. d3-force is deterministic, so a case always gets the same picture. */
function layOut(nodes: PlacedNode[], edges: PlacedEdge[]): void {
  const clusters = [...new Set(nodes.filter(node => node.in_flagged_cluster).map(node => node.cluster_id))];
  const size = Math.sqrt(nodes.length);
  const outer = 40 + size * 15;
  const centres = new Map(clusters.map((cluster, index) => {
    const angle = (index / Math.max(clusters.length, 1)) * Math.PI * 2;
    const spread = clusters.length > 1 ? outer * 0.42 : 0;
    return [cluster, { x: Math.cos(angle) * spread, y: Math.sin(angle) * spread }];
  }));
  const anchored = (node: PlacedNode) => node.in_flagged_cluster && centres.has(node.cluster_id);
  const links: (SimulationLinkDatum<PlacedNode> & { type: string })[] = edges
    .filter(edge => edge.type !== 'weak_co_share')
    .map(edge => ({ source: edge.a, target: edge.b, type: edge.type }));

  const simulation = forceSimulation<PlacedNode>(nodes)
    .force('link', forceLink<PlacedNode, (typeof links)[number]>(links)
      .distance(link => (link.type === 'co_share' ? 26 : 70))
      .strength(link => (link.type === 'co_share' ? 0.09 : 0.03)))
    .force('charge', forceManyBody<PlacedNode>().strength(node => (node.role === 'background' ? -6 : -34)))
    .force('collide', forceCollide<PlacedNode>(node => node.radius + 2.5))
    .force('x', forceX<PlacedNode>(node => (anchored(node) ? centres.get(node.cluster_id)!.x : 0))
      .strength(node => (anchored(node) ? 0.22 : 0.015)))
    .force('y', forceY<PlacedNode>(node => (anchored(node) ? centres.get(node.cluster_id)!.y : 0))
      .strength(node => (anchored(node) ? 0.22 : 0.015)))
    // Accounts outside a flagged group settle in a loose cloud around it, each at its own distance.
    .force('ring', forceRadial<PlacedNode>(node => outer * (0.62 + (spreadHash(node.id) % 70) / 100), 0, 0)
      .strength(node => (anchored(node) ? 0 : 0.12)))
    .stop();
  simulation.tick(280);
}

function makeBins(payload: NetworkPayload, nodes: PlacedNode[], start: number, end: number): Bin[] {
  const width = (end - start) / BIN_COUNT;
  const bins: Bin[] = Array.from({ length: BIN_COUNT }, (_, index) => ({ at: start + index * width, flagged: 0, other: 0 }));
  const place = (time: number) => bins[Math.min(BIN_COUNT - 1, Math.max(0, Math.floor((time - start) / width)))];
  const frames = payload.timeline || [];
  if (frames.length) {
    for (const frame of frames) {
      const time = Date.parse(frame.start);
      if (!Number.isFinite(time)) continue;
      const bin = place(time);
      bin.flagged += frame.cluster_member_post_count;
      bin.other += Math.max(0, frame.post_count - frame.cluster_member_post_count);
    }
  } else {
    for (const node of nodes) {
      const bin = place(node.at);
      if (node.in_flagged_cluster) bin.flagged += 1; else bin.other += 1;
    }
  }
  return bins;
}

/** The time each run of flagged activity ends, as stops for the "next burst" control. */
function findBursts(bins: Bin[], end: number): number[] {
  const stops: number[] = [];
  bins.forEach((bin, index) => {
    if (bin.flagged > 0 && !(bins[index + 1]?.flagged > 0)) stops.push(bins[index + 1]?.at ?? end);
  });
  return stops;
}

export function buildView(payload: NetworkPayload | null | undefined): GraphView | null {
  const all = payload?.nodes || [];
  const placed = all.filter(node => node.appears_at && Number.isFinite(Date.parse(node.appears_at)));
  if (!placed.length) return null;

  const chosen = [...placed]
    .sort((a, b) => importance(b) - importance(a) || a.id.localeCompare(b.id))
    .slice(0, MAX_NODES);
  const nodes: PlacedNode[] = chosen.map((node, rank) => ({
    ...node, x: 0, y: 0, rank, radius: nodeRadius(node), at: Date.parse(node.appears_at as string),
  }));
  const byId = new Map(nodes.map(node => [node.id, node]));

  const edges: PlacedEdge[] = [];
  const linked = new Map<string, PlacedEdge[]>(nodes.map(node => [node.id, []]));
  for (const edge of payload?.edges || []) {
    const a = byId.get(edge.source);
    const b = byId.get(edge.target);
    if (!a || !b) continue;
    const first = edge.first_seen_at ? Date.parse(edge.first_seen_at) : NaN;
    const placedEdge = { ...edge, a, b, at: Number.isFinite(first) ? first : Math.max(a.at, b.at) };
    edges.push(placedEdge);
    linked.get(a.id)!.push(placedEdge);
    linked.get(b.id)!.push(placedEdge);
  }

  layOut(nodes, edges);

  const times = [...nodes.map(node => node.at), ...edges.map(edge => edge.at)];
  for (const frame of payload?.timeline || []) {
    const time = Date.parse(frame.start);
    if (Number.isFinite(time)) times.push(time);
  }
  const start = Math.min(...times);
  const end = Math.max(Math.max(...times), start + 60_000);
  const bins = makeBins(payload as NetworkPayload, nodes, start, end);
  const xs = nodes.map(node => node.x);
  const ys = nodes.map(node => node.y);

  return {
    nodes,
    edges,
    byId,
    linked,
    start,
    end,
    bins,
    bursts: findBursts(bins, end),
    leftOut: placed.length - nodes.length,
    noActivity: all.length - placed.length,
    synthetic: all.some(node => node.synthetic),
    bounds: { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) },
  };
}

export interface Reveal {
  accounts: number;
  flagged: number;
  links: number;
}

export function revealedAt(view: GraphView, time: number, showWeak: boolean): Reveal {
  return {
    accounts: view.nodes.filter(node => node.at <= time).length,
    flagged: view.nodes.filter(node => node.at <= time && node.in_flagged_cluster).length,
    links: view.edges.filter(edge => edge.at <= time && (showWeak || edge.type !== 'weak_co_share')).length,
  };
}
