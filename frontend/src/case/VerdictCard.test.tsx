import { describe, expect, it } from 'vitest';
import type { AnalysisResponse } from '../types';
import { plainVerdict } from './VerdictCard';

const media = (combined: string, web = 'Same image found online') => ({
  overall_risk: 'low',
  modules: { media: { status: 'complete' } },
  claims: [],
  unified_risk: {
    media_decision: { combined, detector_verdict: '', detector_detail: '0 of 3 detectors flagged it. AI likelihood 0.03%.', web_verdict: web, web_detail: 'This exact image is on 10 site(s), earliest found 2006-07-19.' },
    components: [],
  },
}) as unknown as AnalysisResponse;

describe('plain verdict', () => {
  it('words a real image without saying it is proven', () => {
    const plain = plainVerdict(media('Probably a real image: online early.'));
    expect(plain.label).toBe('Likely real');
    expect(plain.why[1].text).toContain('This same image');
    expect(plain.why[1].text).toContain('online since at least 2006-07-19');
    expect(plain.why.at(-1)?.text).toContain("haven't confirmed");
  });

  it('never reads an unclear image as real, whatever its score', () => {
    expect(plainVerdict({ ...media('Unclear: nothing found.'), overall_risk: 'inconclusive' }).tone).toBe('unknown');
  });

  it('warns about a dangerous link in plain words', () => {
    const plain = plainVerdict({ overall_risk: 'high', modules: {}, claims: [], link_analysis: { signs: [{ sign: 'x', strength: 'strong', why: 'Lookalike.' }] }, unified_risk: { components: [] } } as unknown as AnalysisResponse);
    expect(plain.label).toBe('Likely dangerous link');
    expect(plain.action).toContain("Don't open this link");
  });
});
