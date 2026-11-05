import { useCallback, useEffect, useRef, useState } from 'react';
import { prefersReducedMotion } from '../lib/format';

/** Plays a position from 0 to 1 and stops at the end. With reduced motion it starts at the end. */
export function useReplay(durationMs: number, autoplay: boolean, resetKey: unknown) {
  const animate = useRef(autoplay && !prefersReducedMotion()).current;
  const [position, setPosition] = useState(animate ? 0 : 1);
  const [playing, setPlaying] = useState(animate);
  // The animation reads this each frame. A state updater may run too late to say when to stop.
  const current = useRef(position);

  const place = useCallback((next: number) => {
    current.current = next;
    setPosition(next);
  }, []);

  useEffect(() => {
    place(animate ? 0 : 1);
    setPlaying(animate);
  }, [animate, place, resetKey]);

  useEffect(() => {
    if (!playing) return undefined;
    let frame = 0;
    let last = performance.now();
    const step = (now: number) => {
      const next = Math.min(1, current.current + Math.max(0, now - last) / durationMs);
      last = now;
      place(next);
      if (next >= 1) setPlaying(false);
      else frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [playing, durationMs, place]);

  const toggle = useCallback(() => {
    if (current.current >= 1) place(0);
    setPlaying(value => !value);
  }, [place]);

  const seek = useCallback((next: number) => {
    setPlaying(false);
    place(Math.max(0, Math.min(1, next)));
  }, [place]);

  return { position, playing, toggle, seek };
}
