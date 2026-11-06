// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import TextLinkTab from '../case/TextLinkTab';
import type { AnalysisResponse, ModuleResult } from '../types';
import { EventList, Meter, SafeLink } from './ui';

afterEach(cleanup);

describe('state rules from UX-CONTRACT.md', () => {
  it('shows an empty meter, not a zero, for a null score', () => {
    const { container } = render(<Meter value={null} />);
    expect(screen.getByText('No score')).toBeTruthy();
    expect(container.querySelector('.meter-none')).toBeTruthy();
    expect(container.querySelector('.meter-track span')).toBeNull();
  });

  it('keeps a real zero as a real value', () => {
    render(<Meter value={0} label="Rule score" />);
    expect(screen.getByText('Rule score 0.00')).toBeTruthy();
  });

  it('shows a score out of 100 with its decimals', () => {
    render(<Meter value={0.9993} label="Model signal" />);
    expect(screen.getByText('Model signal 99.93')).toBeTruthy();
  });

  it('only makes links from http and https', () => {
    const { container, rerender } = render(<SafeLink href="javascript:alert(1)">bad</SafeLink>);
    expect(container.querySelector('a')).toBeNull();
    expect(screen.getByText('bad')).toBeTruthy();
    rerender(<SafeLink href="https://example.org">good</SafeLink>);
    expect(container.querySelector('a')?.getAttribute('rel')).toContain('noopener');
  });

  it('keeps undated events visible in their own group', () => {
    render(<EventList events={[
      { at: '2026-01-01T00:00:00Z', kind: 'social_post', label: 'dated one', module: 'network', ref: 'a', date_source: 'social_post', synthetic: false },
      { at: null, kind: 'web_appearance', label: 'undated one', module: 'provenance', ref: 'b', date_source: 'none', synthetic: false },
    ]} />);
    expect(screen.getByText('undated one')).toBeTruthy();
    expect(screen.getByText('Undated (1)')).toBeTruthy();
    expect(screen.getByText('No date')).toBeTruthy();
  });

  it('renders untrusted claim text as text, and marks the rule phrase', () => {
    const module = (evidence: string[]): ModuleResult => ({ status: 'complete', score: 0.3, confidence: null, evidence, limitations: [] });
    const report = {
      case_id: 'x', created_at: '', overall_risk: 'moderate', summary: '', uncertainties: [], recommended_actions: [],
      is_replay: false, replay_label: null,
      modules: { text: module(["Urgency language detected: 'urgent'"]) },
      claims: [{ id: '1', text: 'Urgent <img src=x onerror=alert(1)> news', verdict: 'unverified', rationale: 'None queried.' }],
    } as AnalysisResponse;
    const { container } = render(<TextLinkTab report={report} />);
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('mark')?.textContent).toBe('Urgent');
    expect(screen.getByText('Unverified.')).toBeTruthy();
  });
});
