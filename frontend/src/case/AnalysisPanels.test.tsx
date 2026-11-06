// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import FindingsTab from './FindingsTab';
import type { AnalysisResponse, Explanation } from '../types';

// Mocked until the media checks land: these ids aren't known to any code here.
const CHECKS = [
  { check_id: 'media.frames', module: 'media', label: 'Suspicious frames', status: 'complete', result: 'Two frames stand out.', reasoning: 'Frame 12 and frame 40.', benchmark: null, limitations: [], artifacts: [{ type: 'frame', label: 'Frame 12', data_url: 'data:image/png;base64,AAAA' }, { type: 'frame', label: 'Bad', data_url: 'https://evil.example/x.png' }] },
  { check_id: 'media.ocr', module: 'media', label: 'On-screen text', status: 'complete', result: 'Read 3 lines.', reasoning: ['Line one'], benchmark: null, limitations: [], artifacts: [] },
  { check_id: 'brand.new_check', module: 'future', label: 'A check from the future', status: 'complete', result: 'It ran.', reasoning: 'Reason.', benchmark: null, limitations: [], artifacts: [] },
];

const explanation = { case_id: 'c', what_was_submitted: [], what_was_detected: [], supports: [], refutes: [], uncertainties: [], checks: CHECKS, missing_checks: [] } as unknown as Explanation;
const report = { case_id: 'c', overall_risk: 'inconclusive', summary: 's', modules: {}, uncertainties: [], recommended_actions: [] } as unknown as AnalysisResponse;

describe('checks', () => {
  it('shows unknown check ids without a code change', () => {
    render(<FindingsTab report={report} explanation={explanation} loading={false} />);
    expect(screen.getByText('A check from the future')).toBeTruthy();
    expect(screen.getByText('On-screen text')).toBeTruthy();
  });

  it('shows inline frames and refuses images from elsewhere', () => {
    const { container } = render(<FindingsTab report={report} explanation={explanation} loading={false} />);
    const images = [...container.querySelectorAll('.check-artifacts img')].map(image => image.getAttribute('src'));
    expect(images).toEqual(['data:image/png;base64,AAAA']);
  });
});
