// Sends the content to the local TrustFeed API and shows the result. Everything from the API or a
// page is set as plain text, never as HTML.
const API = 'http://localhost:8000';
const DASHBOARD = 'http://localhost:5173';
const MAX_BYTES = { image: 25 * 1024 * 1024, video: 200 * 1024 * 1024 };
const $ = id => document.getElementById(id);
let current = null;

function verdict(report) {
  const combined = report.unified_risk?.media_decision?.combined || '';
  const risk = report.overall_risk;
  if (combined.startsWith('Probably a real')) return ['real', 'Likely real'];
  if (combined.startsWith('Published widely') || combined.startsWith('No sign of AI')) return ['real', 'No sign of AI found'];
  if (combined.startsWith('Disputed')) return ['careful', 'Be careful: the evidence disagrees'];
  if (combined.startsWith('Likely')) return ['fake', 'Likely fake or AI-generated'];
  if (risk === 'critical' || risk === 'high') return ['fake', report.modules?.media?.status === 'complete' ? 'Likely fake or AI-generated' : report.link_analysis && !report.claims?.length ? 'Likely dangerous link' : 'Likely scam or fake'];
  if (risk === 'moderate') return ['careful', 'Be careful'];
  if (risk === 'low') return ['real', 'No warning signs found'];
  return ['unknown', "We can't tell"];
}

const TONES = {
  fake: ['#ff4f8b', 'Likely fake', "Don't share it until you've checked the original source."],
  careful: ['#ffa94d', 'Be careful', 'Check the original source before you share or rely on it.'],
  unknown: ['#a9a6d8', "We can't tell", 'Treat it as unverified, and look for the original source.'],
  real: ['#5fe0b0', 'Likely real', 'Still check any caption or claim before relying on it.'],
};

function reasons(report) {
  const lines = [];
  const decision = report.unified_risk?.media_decision;
  if (decision) {
    lines.push([!decision.detector_detail.startsWith('0 of'), decision.detector_detail.replace('detectors flagged it', 'AI checks flagged it')]);
    lines.push([decision.web_verdict !== 'Same image found online', decision.web_detail.replace('This exact image', 'This same image')]);
  }
  (report.scam_analysis?.signs || []).slice(0, 3).forEach(sign => lines.push([true, sign.why]));
  (report.link_analysis?.signs || []).slice(0, 3).forEach(sign => lines.push([true, sign.why]));
  if (!lines.length) lines.push([false, report.summary]);
  return lines;
}

function show(report) {
  const [tone, label] = verdict(report);
  const [colour, kicker, advice] = TONES[tone];
  document.documentElement.style.setProperty('--tone', colour);
  $('kicker').textContent = kicker;
  $('label').textContent = label;
  const score = report.unified_risk?.trust_score;
  $('score').textContent = score == null ? 'None' : Number(score).toFixed(2);
  $('risk').textContent = report.overall_risk;
  $('why').replaceChildren(...reasons(report).map(([bad, text]) => {
    const item = document.createElement('li');
    item.textContent = `${bad ? '✗' : '✓'} ${text}`;
    return item;
  }));
  const isScam = report.scam_analysis?.assessment === 'warning_signs_found';
  $('action').textContent = isScam ? "Don't pay, share a code or password, or click links in this message." : report.link_analysis && tone === 'fake' ? "Don't open this link or enter any details." : advice;
  $('open').href = `${DASHBOARD}/#/case/${encodeURIComponent(report.case_id)}`;
  $('card').hidden = false;
}

async function readError(response) {
  try {
    const detail = (await response.json()).detail;
    return typeof detail === 'string' ? detail : detail?.message || `The server answered with error ${response.status}.`;
  } catch {
    return `The server answered with error ${response.status}.`;
  }
}

async function fetchMedia(item) {
  let response;
  try {
    response = await fetch(item.url, { credentials: 'omit' });
  } catch {
    throw new Error("This site wouldn't let the file be downloaded. Save it, and upload it on the dashboard.");
  }
  if (!response.ok) throw new Error(`The site refused the file (error ${response.status}). Save it, and upload it on the dashboard.`);
  const blob = await response.blob();
  if (blob.size > MAX_BYTES[item.kind]) throw new Error('This file is over the size limit.');
  if (!blob.size) throw new Error('The file came back empty.');
  return blob;
}

async function analyze(item, search) {
  let request;
  if (item.kind === 'image' || item.kind === 'video') {
    const blob = await fetchMedia(item);
    const form = new FormData();
    form.append('file', blob, item.kind === 'image' ? 'image' : 'video');
    form.append('search_web', String(search));
    request = fetch(`${API}/api/cases/analyze-media`, { method: 'POST', body: form, credentials: 'omit' });
  } else {
    const body = item.kind === 'link' ? { url: item.url } : { text: item.text };
    request = fetch(`${API}/api/cases/analyze`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...body, search_web: search }), credentials: 'omit' });
  }
  let response;
  try {
    response = await request;
  } catch {
    throw new Error(`The TrustFeed server isn't answering at ${API}. Start it and try again.`);
  }
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

async function run(item, search = false) {
  current = item;
  $('form').hidden = true;
  $('card').hidden = true;
  $('search').hidden = true;
  $('error').hidden = true;
  $('status').hidden = false;
  $('status').textContent = search ? 'Checking and searching the web. This can take up to 3 minutes.' : 'Checking it now. This can take up to a minute.';
  try {
    show(await analyze(item, search));
    $('search').hidden = search;
  } catch (problem) {
    $('error').textContent = problem.message;
    $('error').hidden = false;
  }
  $('status').hidden = true;
}

$('check').addEventListener('click', () => {
  const value = $('text').value.trim();
  if (!value) return;
  run(/^https?:\/\/\S+$/i.test(value) ? { kind: 'link', url: value } : { kind: 'text', text: value });
});
$('searchButton').addEventListener('click', () => run(current, true));

chrome.storage.session.get('pending').then(({ pending }) => {
  if (pending) {
    chrome.storage.session.remove('pending');
    run(pending);
  } else {
    $('form').hidden = false;
  }
});
