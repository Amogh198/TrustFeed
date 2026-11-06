// The dashboard's only route to the backend. tools/compat_check.py reads the routes in this file.

/** @typedef {import('./types').AnalysisResponse} AnalysisResponse */

// Use the frontend origin by default. Vite proxies API requests locally, and a
// deployed frontend can route the same paths or set VITE_API_BASE_URL.
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
const REQUEST_TIMEOUT_MS = 180_000;
// Speech-to-text, synthetic speech and frame checks each have their own limit on the server.
const DEEP_TIMEOUT_MS = 720_000;

export class ApiError extends Error {
  /**
   * @param {string} message
   * @param {number} [status]
   * @param {any} [detail]
   */
  constructor(message, status = 0, detail = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

/**
 * @param {any} payload
 * @param {string} fallback
 * @returns {string}
 */
function errorMessage(payload, fallback) {
  const detail = payload?.detail;
  if (typeof detail === 'string') return detail;
  if (detail?.message) return detail.message;
  if (Array.isArray(detail)) {
    return detail.map(item => String(item.msg || '').replace(/^Value error, /, '')).filter(Boolean).join('. ') || fallback;
  }
  return fallback;
}

/**
 * @param {string} path
 * @param {RequestInit & {timeoutMs?: number}} [requestOptions]
 * @returns {Promise<any>}
 */
async function request(path, requestOptions = {}) {
  const { timeoutMs = REQUEST_TIMEOUT_MS, ...options } = requestOptions;
  const controller = new AbortController();
  let timedOut = false;
  const timer = window.setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
  const outer = options.signal;
  if (outer) outer.addEventListener('abort', () => controller.abort(), { once: true });
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, { credentials: 'include', ...options, signal: controller.signal });
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new ApiError(errorMessage(payload, `The API answered with an error (${response.status}).`), response.status, payload?.detail);
    return payload;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === 'AbortError') {
      if (timedOut) throw new ApiError(`This took longer than ${Math.round(timeoutMs / 60_000)} minutes. The API may still be working, so check Cases before trying again.`);
      throw new ApiError('Stopped waiting. The API may still finish this and save it under Cases.', 0, { code: 'cancelled' });
    }
    throw new ApiError(`The API isn't answering at ${API_BASE_URL}. Start it and try again.`, 0, { code: 'offline' });
  } finally {
    window.clearTimeout(timer);
  }
}

const json = { 'Content-Type': 'application/json' };
const id = (/** @type {string} */ value) => encodeURIComponent(value);

export const api = {
  /** @returns {Promise<{status: string, version: string}>} */
  health() { return request('/health'); },
  /**
   * @param {{text?: string, url?: string, searchWeb: boolean, signal?: AbortSignal}} input
   * @returns {Promise<AnalysisResponse>}
   */
  analyze({ text, url, searchWeb, signal }) {
    return request('/api/cases/analyze', {
      method: 'POST',
      headers: json,
      body: JSON.stringify({ text: text || null, url: url || null, search_web: searchWeb }),
      signal,
    });
  },
  /**
   * @param {{file: File, text?: string, url?: string, searchWeb: boolean, deepCheck?: boolean, signal?: AbortSignal}} input
   * @returns {Promise<AnalysisResponse>}
   */
  analyzeMedia({ file, text, url, searchWeb, deepCheck = false, signal }) {
    const body = new FormData();
    body.append('file', file);
    if (text) body.append('text', text);
    if (url) body.append('url', url);
    body.append('search_web', String(searchWeb));
    body.append('deep_check', String(deepCheck));
    return request('/api/cases/analyze-media', { method: 'POST', body, signal, timeoutMs: deepCheck || file.type.startsWith('audio/') ? DEEP_TIMEOUT_MS : REQUEST_TIMEOUT_MS });
  },
  /** @param {string} caseId @returns {Promise<AnalysisResponse>} */
  getCase(caseId) { return request(`/api/cases/${id(caseId)}`); },
  /**
   * @param {string} [riskLevel]
   * @param {number} [limit]
   * @returns {Promise<import('./types').CaseHistory>}
   */
  getHistory(riskLevel = '', limit = 100, q = '', kind = '') {
    const params = new URLSearchParams({ limit: String(limit) });
    if (q) params.set('q', q);
    if (kind) params.set('kind', kind);
    if (riskLevel) params.set('risk_level', riskLevel);
    return request(`/api/cases?${params}`);
  },
  /** @param {string} caseId @returns {Promise<AnalysisResponse>} */
  getExport(caseId) { return request(`/api/cases/${id(caseId)}/export`); },
  /** @param {string} caseId @returns {Promise<import('./types').ProvenanceReport>} */
  getProvenance(caseId) { return request(`/api/cases/${id(caseId)}/provenance`); },
  /** @param {string} caseId @returns {Promise<{events: import('./types').TimelineEvent[]}>} */
  getTimeline(caseId) { return request(`/api/cases/${id(caseId)}/timeline`); },
  /** @param {string} caseId @returns {Promise<import('./types').NetworkPayload>} */
  getNetwork(caseId) { return request(`/api/network/${id(caseId)}`); },
  /** @param {string} caseId @returns {Promise<import('./types').Coverage | null>} */
  getCoverage(caseId) { return request(`/api/network/${id(caseId)}/coverage`); },
  /** @returns {Promise<import('./types').AccountState>} */
  getAccount() { return request('/api/auth/me'); },
  /** @param {string} email @param {string} password */
  login(email, password) { return request('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) }); },
  /** @param {string} email @param {string} password */
  signup(email, password) { return request('/api/auth/signup', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) }); },
  logout() { return request('/api/auth/logout', { method: 'POST' }); },
  /** @returns {Promise<import('./types').Overview>} */
  getOverview() { return request('/api/overview'); },
  /** @param {string} caseId */
  reportPdfUrl(caseId) { return `${API_BASE_URL}/api/cases/${id(caseId)}/report.pdf`; },
  /** @param {string} caseId @returns {Promise<import('./types').NetworkTests | null>} */
  getNetworkTests(caseId) { return request(`/api/network/${id(caseId)}/tests`); },
  /** @param {string} caseId @returns {Promise<import('./types').Explanation>} */
  getExplanation(caseId) { return request(`/api/cases/${id(caseId)}/explanation`); },
  /** @param {string} caseId @returns {Promise<import('./types').RelatedMedia>} */
  getRelatedMedia(caseId) { return request(`/api/cases/${id(caseId)}/related-media`); },
  /** @param {File} file @returns {Promise<import('./types').Heatmap>} */
  heatmap(file) {
    const body = new FormData();
    body.append('file', file);
    return request('/api/media/heatmap', { method: 'POST', body });
  },
  /** @returns {Promise<{watches: string[]}>} */
  listMonitors() { return request('/api/monitors'); },
  /** @returns {Promise<Array<{campaign_id: string, platform_spread: string[], total_posts: number, risk_level: string}>>} */
  getMonitorAlerts() { return request('/api/monitor/alerts'); },
  /**
   * @param {{opted_in: boolean, text: string | null, urls: string[], hashtags: string[]}} watch
   * @returns {Promise<{watch_id: string}>}
   */
  startMonitor(watch) {
    return request('/api/monitors', { method: 'POST', headers: json, body: JSON.stringify(watch) });
  },
  /** @param {string} watchId @returns {Promise<import('./types').WatchSnapshot>} */
  pollMonitor(watchId) { return request(`/api/monitors/${id(watchId)}/poll`, { method: 'POST' }); },
  /** @param {string} watchId @returns {Promise<{stopped: boolean}>} */
  stopMonitor(watchId) { return request(`/api/monitors/${id(watchId)}`, { method: 'DELETE' }); },
  /** @returns {Promise<{scenarios: import('./types').Scenario[]}>} */
  getReplayScenarios() { return request('/api/replay/scenarios'); },
  /** @param {string} scenarioId @returns {Promise<AnalysisResponse>} */
  startReplay(scenarioId) { return request(`/api/replay/${id(scenarioId)}/start`, { method: 'POST' }); },
  /**
   * @param {string} caseId
   * @param {string} [audience]
   * @returns {Promise<import('./types').ActionPacket>}
   */
  actionPacket(caseId, audience = 'reviewers') {
    return request(`/api/cases/${id(caseId)}/action-packet`, {
      method: 'POST', headers: json, body: JSON.stringify({ audience }),
    });
  },
};

/**
 * @param {unknown} error
 * @returns {string}
 */
export function readableUploadError(error) {
  if (!(error instanceof ApiError)) return 'The upload failed. Try again.';
  /** @type {Record<string, string>} */
  const messages = {
    length_required: "The upload couldn't be sent because its size wasn't provided. Try again in another browser.",
    too_large: 'That file is too large. Images can be up to 25 MB, audio up to 100 MB and videos up to 200 MB.',
    unsupported_type: "That file isn't a supported type. Choose a JPEG, PNG, WebP, MP4, MOV, WebM, AVI, MP3, WAV, M4A, FLAC or OGG file.",
    empty_file: 'That file is empty. Choose another one.',
    corrupt_media: "That file couldn't be decoded. Choose another one.",
  };
  return messages[error.detail?.code] || error.message;
}

/**
 * @param {string | null | undefined} value
 * @returns {string | null}
 */
export function safeHttpUrl(value) {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
  } catch { return null; }
}
