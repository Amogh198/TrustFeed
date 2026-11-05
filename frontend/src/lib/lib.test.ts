import { describe, expect, it } from 'vitest';
import { safeHttpUrl } from '../api.js';
import type { AnalysisResponse, NetworkPayload } from '../types';
import { benchmarkSentence, markPhrases, quotedPhrases, scoreText, trustScore, uploadProblem, utc } from './format';
import { buildView, revealedAt } from './graph';
import { caseHref, parseRoute } from './route';

describe('honest values', () => {
  it('never shows a null score as zero', () => {
    expect(scoreText(null)).toBe('No score');
    expect(scoreText(undefined)).toBe('No score');
    expect(scoreText(0)).toBe('0.00');
  });

  it('reads a null benchmark as not measured', () => {
    expect(benchmarkSentence(null)).toBe('Not measured');
    expect(benchmarkSentence({ n_fake: 157, flagged_fake: 1, n_real: 75, flagged_real: 1, auc: 0.85 }))
      .toContain('Flagged 1 of 157 fakes');
  });

  it('never invents a date', () => {
    expect(utc(null)).toBe('No date');
    expect(utc('not a date')).toBe('not a date');
    expect(utc('2026-01-15T09:00:00Z')).toContain('09:00');
  });
});

describe('untrusted content', () => {
  it('only allows http and https links', () => {
    expect(safeHttpUrl('javascript:alert(1)')).toBeNull();
    expect(safeHttpUrl('data:text/html,x')).toBeNull();
    expect(safeHttpUrl('not a url')).toBeNull();
    expect(safeHttpUrl(null)).toBeNull();
    expect(safeHttpUrl('https://example.org/a')).toBe('https://example.org/a');
  });

  it('marks the quoted rule phrases without changing the text', () => {
    const phrases = quotedPhrases(["Urgency language detected: 'share before'", "Suppression: 'officials are (hiding)'"]);
    const parts = markPhrases('Please SHARE BEFORE it goes. officials are (hiding) it', phrases);
    expect(parts.map(part => part.text).join('')).toBe('Please SHARE BEFORE it goes. officials are (hiding) it');
    expect(parts.filter(part => part.marked).map(part => part.text)).toEqual(['SHARE BEFORE', 'officials are (hiding)']);
  });

  it('refuses bad uploads before sending them', () => {
    expect(uploadProblem({ type: 'text/plain', size: 10 })).toContain('supported type');
    expect(uploadProblem({ type: 'image/png', size: 0 })).toContain('empty');
    expect(uploadProblem({ type: 'image/png', size: 26 * 1024 * 1024 })).toContain('25 MB');
    expect(uploadProblem({ type: 'video/mp4', size: 201 * 1024 * 1024 })).toContain('200 MB');
    expect(uploadProblem({ type: 'video/mp4', size: 100 })).toBeNull();
  });
});

describe('routes', () => {
  it('opens a case tab and survives odd ids', () => {
    expect(parseRoute('#/case/demo-001/spread')).toEqual({ page: 'case', caseId: 'demo-001', tab: 'spread' });
    expect(parseRoute(caseHref('a/b'))).toEqual({ page: 'case', caseId: 'a/b', tab: 'findings' });
    expect(parseRoute('#/nothing')).toEqual({ page: 'home' });
  });
});

const payload: NetworkPayload = {
  nodes: [
    { id: 'a', handle: 'a', role: 'origin_candidate', role_label: '', cluster_id: 'c1', in_flagged_cluster: true, post_count: 1, appears_at: '2026-01-01T00:00:00Z', weighted_degree: 5, synthetic: true },
    { id: 'b', handle: 'b', role: 'amplifier', role_label: '', cluster_id: 'c1', in_flagged_cluster: true, post_count: 2, appears_at: '2026-01-01T00:01:00Z', weighted_degree: 5, synthetic: true },
    { id: 'c', handle: 'c', role: 'background', role_label: '', cluster_id: null, in_flagged_cluster: false, post_count: 1, appears_at: '2026-01-01T02:00:00Z', synthetic: true },
    { id: 'd', handle: 'd', role: 'background', role_label: '', cluster_id: null, in_flagged_cluster: false, post_count: 0, appears_at: null, synthetic: true },
  ],
  edges: [
    { id: 'e1', source: 'a', target: 'b', type: 'co_share', first_seen_at: '2026-01-01T00:01:00Z' },
    { id: 'e2', source: 'b', target: 'c', type: 'weak_co_share', first_seen_at: '2026-01-01T02:00:00Z' },
    { id: 'e3', source: 'a', target: 'd', type: 'co_share', first_seen_at: '2026-01-01T02:00:00Z' },
  ],
  timeline: [
    { start: '2026-01-01T00:00:00Z', post_count: 3, cluster_member_post_count: 3 },
    { start: '2026-01-01T02:00:00Z', post_count: 1, cluster_member_post_count: 0 },
  ],
};

describe('spread graph', () => {
  it('leaves out accounts with no part in the spread, and says how many', () => {
    const view = buildView(payload)!;
    expect(view.nodes.map(node => node.id).sort()).toEqual(['a', 'b', 'c']);
    expect(view.noActivity).toBe(1);
    expect(view.edges.map(edge => edge.id).sort()).toEqual(['e1', 'e2']);
    expect(view.synthetic).toBe(true);
  });

  it('reveals accounts and links in time order', () => {
    const view = buildView(payload)!;
    expect(revealedAt(view, Date.parse('2026-01-01T00:00:30Z'), false)).toEqual({ accounts: 1, flagged: 1, links: 0 });
    expect(revealedAt(view, view.end, false)).toEqual({ accounts: 3, flagged: 2, links: 1 });
    expect(revealedAt(view, view.end, true).links).toBe(2);
  });

  it('counts flagged and other posts separately and finds the burst', () => {
    const view = buildView(payload)!;
    expect(view.bins.reduce((sum, bin) => sum + bin.flagged, 0)).toBe(3);
    expect(view.bins.reduce((sum, bin) => sum + bin.other, 0)).toBe(1);
    expect(view.bursts).toHaveLength(1);
  });

  it('lays out the same way every time', () => {
    const first = buildView(payload)!;
    const second = buildView(payload)!;
    expect(first.nodes.map(node => [node.x, node.y])).toEqual(second.nodes.map(node => [node.x, node.y]));
  });

  it('returns nothing rather than an empty picture', () => {
    expect(buildView({ nodes: [], edges: [], timeline: [] })).toBeNull();
    expect(buildView(null)).toBeNull();
  });
});

describe('trust score', () => {
  const report = (modules: Record<string, [string, number | null]>) => ({
    modules: Object.fromEntries(Object.entries(modules).map(([key, [status, score]]) => [key, { status, score, confidence: null, evidence: [], limitations: [] }])),
  }) as unknown as AnalysisResponse;

  it('uses the strongest warning from checks on the content', () => {
    const trust = trustScore(report({ media: ['complete', 0.28], text: ['complete', 0.45], network: ['complete', 0.99] }));
    expect(trust.score).toBe(55);
    expect(trust.strongest?.name).toBe('Text');
  });

  it('gives no score rather than a high one when nothing measured the content', () => {
    const trust = trustScore(report({ media: ['unavailable', null], network: ['complete', 0.87] }));
    expect(trust.score).toBeNull();
    expect(trust.mediaMissing).toBe(true);
  });

  it('counts a real zero', () => {
    expect(trustScore(report({ url: ['complete', 0] })).score).toBe(100);
  });
});
