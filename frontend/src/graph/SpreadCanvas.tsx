import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { prefersReducedMotion } from '../lib/format';
import type { GraphView, PlacedEdge, PlacedNode } from '../lib/graph';

export const ROLE_COLOURS: Record<string, string> = {
  origin_candidate: '#eef25a',
  amplifier: '#ff4f8b',
  participant: '#ffc53d',
  target: '#6fe7ff',
  background: '#8f86c9',
};

const FLASH_MS = 900;

interface Props {
  view: GraphView;
  time: number;
  showWeak?: boolean;
  selectedId?: string | null;
  onSelect?: (node: PlacedNode | null) => void;
  interactive?: boolean;
  /** Where the middle of the graph sits, as a share of the width. The home page moves it right. */
  focusX?: number;
  label: string;
  /** When given, pointing at a link shows why its two accounts are connected. */
  edgeReason?: (edge: PlacedEdge) => string;
  nodeHint?: string;
}

interface Transform { k: number; x: number; y: number }

export default function SpreadCanvas({ view, time, showWeak = false, selectedId, onSelect, interactive = true, focusX = 0.5, label, edgeReason, nodeHint }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [hover, setHover] = useState<PlacedNode | null>(null);
  const [hoverEdge, setHoverEdge] = useState<PlacedEdge | null>(null);
  const zoomRef = useRef<Transform | null>(null);
  const firstSeen = useRef(new Map<string, number>());
  const frame = useRef(0);
  const reduced = useMemo(prefersReducedMotion, []);
  const drag = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const latest = useRef({ time, showWeak, selectedId, hover, hoverEdge });
  latest.current = { time, showWeak, selectedId, hover, hoverEdge };

  const seeded = useRef(false);
  useEffect(() => { firstSeen.current.clear(); seeded.current = false; zoomRef.current = null; }, [view]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const observer = new ResizeObserver(([entry]) => {
      setSize({ width: entry.contentRect.width, height: entry.contentRect.height });
      zoomRef.current = null;
    });
    observer.observe(canvas);
    return () => observer.disconnect();
  }, []);

  const fit = useCallback((): Transform => {
    const { minX, maxX, minY, maxY } = view.bounds;
    const pad = 46;
    const room = focusX === 0.5 ? size.width : size.width * Math.min(focusX, 1 - focusX) * 2;
    const k = Math.min(2.2, Math.max(0.2, Math.min(
      (room - pad * 2) / Math.max(maxX - minX, 1),
      (size.height - pad * 2) / Math.max(maxY - minY, 1),
    )));
    return {
      k,
      x: size.width * focusX - k * ((minX + maxX) / 2),
      y: size.height / 2 - k * ((minY + maxY) / 2),
    };
  }, [view, size, focusX]);

  const transform = useCallback(() => {
    if (!zoomRef.current) zoomRef.current = fit();
    return zoomRef.current;
  }, [fit]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext('2d');
    if (!canvas || !context || !size.width) return;
    const ratio = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(size.width * ratio)) canvas.width = Math.round(size.width * ratio);
    if (canvas.height !== Math.round(size.height * ratio)) canvas.height = Math.round(size.height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, size.width, size.height);

    const { time: now, showWeak: weak, selectedId: selected, hover: hovered, hoverEdge: hoveredEdge } = latest.current;
    const { k, x, y } = transform();
    const sx = (value: number) => value * k + x;
    const sy = (value: number) => value * k + y;
    const clock = performance.now();
    let animating = false;

    // Whatever is already showing on the first draw has already happened, so only later arrivals flash.
    if (!seeded.current) {
      seeded.current = true;
      for (const item of [...view.nodes, ...view.edges]) {
        if (item.at <= now) firstSeen.current.set(item.id, clock - FLASH_MS);
      }
    }

    const age = (id: string): number => {
      const seen = firstSeen.current;
      if (!seen.has(id)) seen.set(id, clock);
      if (reduced) return 0;
      const flash = 1 - (clock - (seen.get(id) as number)) / FLASH_MS;
      if (flash > 0) { animating = true; return flash; }
      return 0;
    };

    const focusId = selected || hovered?.id || null;
    const neighbours = new Set<string>();
    if (focusId) {
      neighbours.add(focusId);
      for (const edge of view.linked.get(focusId) || []) { neighbours.add(edge.a.id); neighbours.add(edge.b.id); }
    }

    for (const id of [...firstSeen.current.keys()]) {
      const item = view.byId.get(id);
      if (item && item.at > now) firstSeen.current.delete(id);
    }

    const edgeStyle = (edge: PlacedEdge): [string, number] => {
      if (edge.type === 'mention') return ['111,231,255', 0.22];
      if (edge.type === 'weak_co_share') return ['179,172,217', 0.1];
      return edge.a.in_flagged_cluster && edge.b.in_flagged_cluster ? ['255,79,139', 0.2] : ['179,172,217', 0.22];
    };

    context.globalCompositeOperation = 'lighter';
    for (const edge of view.edges) {
      if (edge.at > now || (!weak && edge.type === 'weak_co_share')) continue;
      const flash = age(edge.id);
      const [colour, base] = edgeStyle(edge);
      const touches = !focusId || edge.a.id === focusId || edge.b.id === focusId;
      const alpha = touches ? (focusId ? Math.max(base * 3, 0.55) : base) : base * 0.18;
      const pointedAt = hoveredEdge?.id === edge.id;
      context.strokeStyle = pointedAt ? 'rgba(111,231,255,0.95)' : `rgba(${colour},${Math.min(1, alpha + flash * 0.75)})`;
      context.lineWidth = (pointedAt ? 2.5 : edge.type === 'weak_co_share' ? 0.6 : 1) + flash * 1.6;
      context.setLineDash(edge.cross_platform ? [5, 4] : []);
      context.beginPath();
      context.moveTo(sx(edge.a.x), sy(edge.a.y));
      context.lineTo(sx(edge.b.x), sy(edge.b.y));
      context.stroke();
    }
    context.setLineDash([]);

    const scale = Math.max(0.75, Math.min(1.8, Math.sqrt(k)));
    for (const node of view.nodes) {
      if (node.at > now) continue;
      const flash = age(node.id);
      const px = sx(node.x);
      const py = sy(node.y);
      const radius = node.radius * scale;
      const colour = ROLE_COLOURS[node.role] || ROLE_COLOURS.background;
      const dimmed = focusId && !neighbours.has(node.id);
      context.globalCompositeOperation = 'lighter';
      if (node.role !== 'background' || flash > 0) {
        context.globalAlpha = dimmed ? 0.05 : 0.16 + flash * 0.5;
        context.fillStyle = colour;
        context.beginPath();
        context.arc(px, py, radius * 2.3 + flash * 16, 0, Math.PI * 2);
        context.fill();
      }
      context.globalCompositeOperation = 'source-over';
      context.globalAlpha = dimmed ? 0.22 : node.role === 'background' ? 0.8 : 1;
      context.fillStyle = colour;
      context.beginPath();
      if (node.role === 'target') {
        // A diamond, so the role doesn't rest on colour alone.
        context.moveTo(px, py - radius * 1.25);
        context.lineTo(px + radius * 1.25, py);
        context.lineTo(px, py + radius * 1.25);
        context.lineTo(px - radius * 1.25, py);
        context.closePath();
      } else {
        context.arc(px, py, radius, 0, Math.PI * 2);
      }
      context.fill();
      if (node.role === 'origin_candidate') {
        context.strokeStyle = colour;
        context.lineWidth = 1.5;
        context.beginPath();
        context.arc(px, py, radius + 5, 0, Math.PI * 2);
        context.stroke();
      }
      context.globalAlpha = 1;
      if (node.id === selected || node.id === hovered?.id) {
        context.strokeStyle = '#ffffff';
        context.lineWidth = 2;
        context.beginPath();
        context.arc(px, py, radius + 3, 0, Math.PI * 2);
        context.stroke();
      }
    }
    context.globalCompositeOperation = 'source-over';

    if (animating) frame.current = requestAnimationFrame(draw);
  }, [view, size, transform, reduced]);

  useEffect(() => {
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame.current);
  }, [draw, time, showWeak, selectedId, hover, hoverEdge]);

  const redraw = () => {
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(draw);
  };

  const nodeAt = (clientX: number, clientY: number): PlacedNode | null => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return null;
    const { k, x, y } = transform();
    const px = clientX - rect.left;
    const py = clientY - rect.top;
    let best: PlacedNode | null = null;
    let bestDistance = Infinity;
    for (const node of view.nodes) {
      if (node.at > time) continue;
      const distance = Math.hypot(node.x * k + x - px, node.y * k + y - py);
      if (distance < Math.max(9, node.radius * 2) && distance < bestDistance) { best = node; bestDistance = distance; }
    }
    return best;
  };

  const edgeAt = (clientX: number, clientY: number): PlacedEdge | null => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return null;
    const { k, x, y } = transform();
    const px = clientX - rect.left;
    const py = clientY - rect.top;
    let best: PlacedEdge | null = null;
    let bestDistance = 8;
    for (const edge of view.edges) {
      if (edge.at > time || (!showWeak && edge.type === 'weak_co_share')) continue;
      const x1 = edge.a.x * k + x;
      const y1 = edge.a.y * k + y;
      const dx = edge.b.x * k + x - x1;
      const dy = edge.b.y * k + y - y1;
      const length = dx * dx + dy * dy;
      if (length === 0) continue;
      const along = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / length));
      const distance = Math.hypot(px - (x1 + along * dx), py - (y1 + along * dy));
      if (distance < bestDistance) {
        bestDistance = distance;
        best = edge;
      }
    }
    return best;
  };

  const zoomBy = useCallback((factor: number, px = size.width / 2, py = size.height / 2) => {
    const current = transform();
    const k = Math.max(0.15, Math.min(8, current.k * factor));
    zoomRef.current = {
      k,
      x: px - ((px - current.x) / current.k) * k,
      y: py - ((py - current.y) / current.k) * k,
    };
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(draw);
  }, [draw, size, transform]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !interactive) return undefined;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = canvas.getBoundingClientRect();
      zoomBy(event.deltaY < 0 ? 1.15 : 0.87, event.clientX - rect.left, event.clientY - rect.top);
    };
    canvas.addEventListener('wheel', onWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', onWheel);
  }, [interactive, zoomBy]);

  const onPointerDown = (event: PointerEvent<HTMLCanvasElement>) => {
    drag.current = { x: event.clientX, y: event.clientY, moved: false };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onPointerMove = (event: PointerEvent<HTMLCanvasElement>) => {
    if (drag.current && (event.buttons || event.pointerType === 'touch')) {
      const dx = event.clientX - drag.current.x;
      const dy = event.clientY - drag.current.y;
      if (drag.current.moved || Math.hypot(dx, dy) > 4) {
        const current = transform();
        zoomRef.current = { ...current, x: current.x + dx, y: current.y + dy };
        drag.current = { x: event.clientX, y: event.clientY, moved: true };
        redraw();
      }
      return;
    }
    const found = nodeAt(event.clientX, event.clientY);
    if (found?.id !== hover?.id) setHover(found);
    if (edgeReason) {
      const foundEdge = found ? null : edgeAt(event.clientX, event.clientY);
      if (foundEdge?.id !== hoverEdge?.id) setHoverEdge(foundEdge);
    }
  };

  const onPointerUp = (event: PointerEvent<HTMLCanvasElement>) => {
    if (drag.current && !drag.current.moved) onSelect?.(nodeAt(event.clientX, event.clientY));
    drag.current = null;
  };

  // Arrow keys step through the visible accounts, most connected first. Enter or Space opens one.
  const onKeyDown = (event: KeyboardEvent<HTMLCanvasElement>) => {
    const visible = view.nodes.filter(node => node.at <= time);
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault();
      const step = event.key === 'ArrowRight' ? 1 : -1;
      const index = hover ? visible.findIndex(node => node.id === hover.id) : -1;
      setHover(visible[(index + step + visible.length) % visible.length] || null);
    } else if ((event.key === 'Enter' || event.key === ' ') && hover) {
      event.preventDefault();
      onSelect?.(hover);
    } else if (event.key === 'Escape') {
      setHover(null);
      setHoverEdge(null);
      onSelect?.(null);
    } else if (event.key === '+' || event.key === '=') {
      zoomBy(1.2);
    } else if (event.key === '-') {
      zoomBy(0.83);
    }
  };

  const reset = () => { zoomRef.current = null; redraw(); };
  const place = hover || hoverEdge ? transform() : null;

  return (
    <div className="spread-canvas">
      {interactive ? (
        <canvas
          ref={canvasRef}
          tabIndex={0}
          role="application"
          aria-label={`${label} Arrow keys step through accounts, Enter opens one, plus and minus zoom.`}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerLeave={() => { setHover(null); setHoverEdge(null); }}
          onKeyDown={onKeyDown}
          style={{ cursor: hover ? 'pointer' : hoverEdge ? 'help' : 'grab', touchAction: 'none' }}
        />
      ) : <canvas ref={canvasRef} role="img" aria-label={label} />}
      {hover && place && (
        <div className="node-tip" style={{ left: hover.x * place.k + place.x, top: hover.y * place.k + place.y }}>
          <strong>{hover.handle}</strong>
          <span>{hover.role_label}</span>
          {nodeHint && <span>{nodeHint}</span>}
        </div>
      )}
      {hoverEdge && !hover && place && edgeReason && (
        <div
          className="node-tip"
          style={{
            left: ((hoverEdge.a.x + hoverEdge.b.x) / 2) * place.k + place.x,
            top: ((hoverEdge.a.y + hoverEdge.b.y) / 2) * place.k + place.y,
          }}
        >
          <strong>Why these are linked</strong>
          <span>{edgeReason(hoverEdge)}</span>
        </div>
      )}
      {interactive && (
        <div className="zoom-controls">
          <button type="button" aria-label="Zoom in" onClick={() => zoomBy(1.25)}>+</button>
          <button type="button" aria-label="Zoom out" onClick={() => zoomBy(0.8)}>−</button>
          <button type="button" onClick={reset}>Fit</button>
        </div>
      )}
    </div>
  );
}
