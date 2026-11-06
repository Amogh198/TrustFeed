// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import RelatedMedia from './RelatedMedia';
import { api } from '../api.js';
import type { RelatedMedia as RelatedMediaData } from '../types';

vi.mock('../api.js', async importOriginal => ({ ...(await importOriginal<object>()), api: { getRelatedMedia: vi.fn() } }));
const getRelatedMedia = api.getRelatedMedia as unknown as ReturnType<typeof vi.fn>;

const base: RelatedMediaData = { case_id: 'case-1', status: 'complete', compared_cases: 2, cases: [], history: [], limitations: ['A link means the pictures look alike.'] };

beforeEach(() => getRelatedMedia.mockReset());
afterEach(cleanup);

describe('RelatedMedia', () => {
  it('says what linked each case, and which ones went through another case', async () => {
    getRelatedMedia.mockResolvedValue({
      ...base,
      cases: [
        { case_id: 'crop-1', kind: 'likely_same_image', first_seen: '2026-11-01T00:00:00Z', through_case_id: null, links_from_start: 1, distances: { phash: 12, dhash: 9 } },
        { case_id: 'chain-2', kind: 'likely_same_image', first_seen: '2026-11-02T00:00:00Z', through_case_id: 'crop-1', links_from_start: 2, distances: {} },
        { case_id: 'heavy-3', kind: 'shares_visible_content', first_seen: '2026-11-03T00:00:00Z', through_case_id: null, links_from_start: 1, agreeing_features: 40 },
      ],
    });
    render(<RelatedMedia caseId="case-1" />);
    expect(await screen.findByText('Related media (3)')).toBeTruthy();
    expect(screen.getByText('Fingerprint distances: phash 12, dhash 9')).toBeTruthy();
    expect(screen.getByText('Matched case crop-1, not this one directly, so check that link')).toBeTruthy();
    expect(screen.getByText('40 small patches of the pictures line up')).toBeTruthy();
  });

  it('marks the earliest found without calling it the source, and labels replayed posts', async () => {
    getRelatedMedia.mockResolvedValue({
      ...base,
      cases: [{ case_id: 'crop-1', kind: 'exact_copy', links_from_start: 1 }],
      history: [
        { at: '2026-01-01T00:00:00Z', kind: 'web_page', case_id: 'crop-1', label: 'news.example', url: 'https://news.example/a', earliest_found: true },
        { at: '2026-01-02T00:00:00Z', kind: 'public_post', case_id: 'case-1', label: 'sim', synthetic: true },
      ],
    });
    render(<RelatedMedia caseId="case-1" />);
    expect(await screen.findByText('Earliest found, not shown to be the source')).toBeTruthy();
    expect(screen.getByText('Includes replayed synthetic posts, not real activity')).toBeTruthy();
  });

  it('says finding nothing does not show the picture was never reposted', async () => {
    getRelatedMedia.mockResolvedValue(base);
    render(<RelatedMedia caseId="case-1" />);
    expect(await screen.findByText('No related media found')).toBeTruthy();
    expect(screen.getByText(/doesn't show this picture hasn't been reposted/)).toBeTruthy();
  });

  it('shows nothing for a case with no fingerprints, and says so when loading fails', async () => {
    getRelatedMedia.mockResolvedValueOnce({ ...base, status: 'not_applicable' });
    const { container } = render(<RelatedMedia caseId="case-1" />);
    await vi.waitFor(() => expect(getRelatedMedia).toHaveBeenCalled());
    expect(container.textContent).toBe('');
    cleanup();
    getRelatedMedia.mockRejectedValueOnce(new Error('offline'));
    render(<RelatedMedia caseId="case-2" />);
    expect(await screen.findByText("Related media didn't load")).toBeTruthy();
  });
});
