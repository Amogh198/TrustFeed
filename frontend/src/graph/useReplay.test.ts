// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useReplay } from './useReplay';

describe('spread replay', () => {
  it('stops at the end instead of staying in the playing state', async () => {
    const { result } = renderHook(() => useReplay(5, true, 'view'));
    await waitFor(() => expect(result.current.playing).toBe(false));
    expect(result.current.position).toBe(1);
  });

  it('starts at the end when it is not set to play by itself', () => {
    const { result } = renderHook(() => useReplay(5, false, 'view'));
    expect(result.current.position).toBe(1);
    expect(result.current.playing).toBe(false);
  });

  it('replays from the start, and stops when moved by hand', async () => {
    const { result } = renderHook(() => useReplay(60_000, false, 'view'));
    act(() => result.current.toggle());
    expect(result.current.position).toBeLessThan(0.1);
    expect(result.current.playing).toBe(true);
    act(() => result.current.seek(0.5));
    expect(result.current.position).toBe(0.5);
    expect(result.current.playing).toBe(false);
    act(() => result.current.seek(4));
    expect(result.current.position).toBe(1);
  });
});
