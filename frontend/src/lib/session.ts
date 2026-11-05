import type { AnalysisResponse } from '../types';

// The API deletes uploads after analysis, so the file only lives in this tab, for the preview and
// the heatmap. A fresh result is kept too, so that opening it doesn't fetch it again.
const uploads = new Map<string, File>();
const fresh = new Map<string, AnalysisResponse>();

export function rememberResult(result: AnalysisResponse, file?: File | null): void {
  fresh.set(result.case_id, result);
  if (file) uploads.set(result.case_id, file);
}

export function freshResult(caseId: string): AnalysisResponse | undefined {
  return fresh.get(caseId);
}

export function uploadFor(caseId: string): File | undefined {
  return uploads.get(caseId);
}

export function setUploadFor(caseId: string, file: File): void {
  uploads.set(caseId, file);
}
