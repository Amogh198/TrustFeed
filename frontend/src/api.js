const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
const REQUEST_TIMEOUT_MS = 180_000;

export class ApiError extends Error {
  constructor(message, status = 0, detail = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

function errorMessage(payload, fallback) {
  const detail = payload?.detail;
  if (typeof detail === 'string') return detail;
  if (detail?.message) return detail.message;
  if (Array.isArray(detail)) return detail.map(item => item.msg).filter(Boolean).join('. ') || fallback;
  return fallback;
}

async function request(path, options = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, { ...options, signal: controller.signal });
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new ApiError(errorMessage(payload, `Request failed (${response.status}).`), response.status, payload?.detail);
    return payload;
  } catch (error) {
    if (error.name === 'AbortError') throw new ApiError('The request took longer than 3 minutes. The API may still be processing it; check case history before retrying.');
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

export const api = {
  analyze({ text, url, searchWeb }) {
    return request('/api/cases/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text || null, url: url || null, search_web: searchWeb }),
    });
  },
  analyzeMedia({ file, text, url, searchWeb }) {
    const body = new FormData();
    body.append('file', file);
    if (text) body.append('text', text);
    if (url) body.append('url', url);
    body.append('search_web', String(searchWeb));
    return request('/api/cases/analyze-media', { method: 'POST', body });
  },
  getCase(caseId) { return request(`/api/cases/${encodeURIComponent(caseId)}`); },
  getHistory(riskLevel = '') {
    const query = riskLevel ? `?risk_level=${encodeURIComponent(riskLevel)}` : '';
    return request(`/api/cases${query}`);
  },
  getExport(caseId) { return request(`/api/cases/${encodeURIComponent(caseId)}/export`); },
  getProvenance(caseId) { return request(`/api/cases/${encodeURIComponent(caseId)}/provenance`); },
  getTimeline(caseId) { return request(`/api/cases/${encodeURIComponent(caseId)}/timeline`); },
  getNetwork(caseId) { return request(`/api/network/${encodeURIComponent(caseId)}`); },
  getCoverage(caseId) { return request(`/api/network/${encodeURIComponent(caseId)}/coverage`); },
  getExplanation(caseId) { return request(`/api/cases/${encodeURIComponent(caseId)}/explanation`); },
  heatmap(file) {
    const body = new FormData();
    body.append('file', file);
    return request('/api/media/heatmap', { method: 'POST', body });
  },
  startMonitor(watch) {
    return request('/api/monitors', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(watch) });
  },
  pollMonitor(watchId) { return request(`/api/monitors/${encodeURIComponent(watchId)}/poll`, { method: 'POST' }); },
  stopMonitor(watchId) { return request(`/api/monitors/${encodeURIComponent(watchId)}`, { method: 'DELETE' }); },
  getReplayScenarios() { return request('/api/replay/scenarios'); },
  startReplay(scenarioId) { return request(`/api/replay/${encodeURIComponent(scenarioId)}/start`, { method: 'POST' }); },
  actionPacket(caseId, audience = 'reviewers') {
    return request(`/api/cases/${encodeURIComponent(caseId)}/action-packet`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ audience }),
    });
  },
};

export function readableUploadError(error) {
  if (!(error instanceof ApiError)) return 'The API could not be reached. Start it at the configured VITE_API_BASE_URL and try again.';
  const code = error.detail?.code;
  const messages = {
    length_required: 'The upload could not be sent because its size was not provided.',
    too_large: 'That file is over the API upload limit. Images must be 25 MB or less; videos must be 200 MB or less.',
    unsupported_type: 'Choose a JPEG, PNG, WebP, MP4, MOV, WebM, or AVI file.',
    empty_file: 'The selected file is empty. Choose another file.',
    corrupt_media: 'The selected file could not be decoded. Choose another file.',
  };
  return messages[code] || error.message;
}

export function safeHttpUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
  } catch { return null; }
}
