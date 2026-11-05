export const replayCase = {
  id: 'TF-2026-0418',
  title: 'Emergency flood warning — Rivergate Dam',
  submitted: 'A dam failure is imminent. Evacuate Rivergate immediately. Share this warning before officials take the post down.',
  source: '@CivicAlertNow · public post',
  time: 'Today, 09:42 UTC',
  risk: 'High',
  riskScore: 78,
  summary: 'The warning is unverified. A rapid burst of near-identical posts is visible in this replay dataset; no authoritative confirmation is included.',
  provenance: {
    status: 'No media attached',
    detail: 'This replay case contains text and synthetic account metadata only. There is no image, capture metadata, or verified origin record to inspect.',
    consent: 'No external source search was requested or performed.',
  },
  modules: [
    { key: 'claim', label: 'Claim assessment', status: 'Inconclusive', score: null, note: 'No trusted source match in this fixture' },
    { key: 'media', label: 'Media forensics', status: 'Unavailable', score: null, note: 'No media attached to this case' },
    { key: 'network', label: 'Spread pattern', status: 'Signal detected', score: 0.78, note: '18 accounts shared similar text within 2 minutes' },
  ],
  evidence: [
    { type: 'Network signal', title: 'Rapid coordinated sharing pattern', detail: '18 accounts posted near-identical captions within 120 seconds.', tag: 'Synthetic replay signal', tone: 'amber' },
    { type: 'Claim check', title: 'No authoritative confirmation found', detail: 'This fixture contains no matching bulletin from a verified emergency agency.', tag: 'Evidence gap', tone: 'slate' },
    { type: 'Language cue', title: 'Urgency and forwarding pressure', detail: 'The text urges immediate sharing and predicts content removal.', tag: 'Rule-based indicator', tone: 'blue' },
  ],
  nodes: [
    { id: 'origin', x: 150, y: 136, role: 'Origin candidate', label: 'account_07', time: '09:40:12' },
    { id: 'hub1', x: 308, y: 81, role: 'Amplifier', label: 'civic_watch', time: '09:40:39' },
    { id: 'hub2', x: 319, y: 192, role: 'Amplifier', label: 'rivergate_now', time: '09:40:54' },
    { id: 'a', x: 477, y: 54, role: 'Participant', label: 'local_updates', time: '09:41:02' },
    { id: 'b', x: 480, y: 114, role: 'Participant', label: 'alert_stream', time: '09:41:18' },
    { id: 'c', x: 482, y: 176, role: 'Participant', label: 'news_wire_24', time: '09:41:25' },
    { id: 'd', x: 480, y: 235, role: 'Participant', label: 'citypulse', time: '09:41:48' },
    { id: 'e', x: 617, y: 83, role: 'Participant', label: 'metro_report', time: '09:42:01' },
    { id: 'f', x: 620, y: 145, role: 'Participant', label: 'community_hub', time: '09:42:12' },
    { id: 'g', x: 618, y: 208, role: 'Participant', label: 'daily_signal', time: '09:42:20' },
  ],
  links: [['origin', 'hub1'], ['origin', 'hub2'], ['hub1', 'a'], ['hub1', 'b'], ['hub2', 'c'], ['hub2', 'd'], ['b', 'e'], ['c', 'f'], ['d', 'g']],
  timeline: [
    { time: '09:40:12', event: 'First appearance in this replay', who: 'account_07', kind: 'origin' },
    { time: '09:40:39', event: 'First amplifier shares near-match', who: 'civic_watch', kind: 'amplifier' },
    { time: '09:41:02', event: 'Sharing burst expands to 8 accounts', who: '4 new accounts', kind: 'burst' },
    { time: '09:42:01', event: '18 similar posts observed in 109 seconds', who: 'synthetic dataset', kind: 'burst' },
  ],
};

export const recentCases = [
  { id: 'TF-2026-0418', title: 'Emergency flood warning', time: '09:42 UTC', risk: 'High', type: 'Text · Network' },
  { id: 'TF-2026-0416', title: 'Vintage wildfire image recirculated', time: 'Yesterday', risk: 'Inconclusive', type: 'Image · Provenance' },
  { id: 'TF-2026-0412', title: 'Relief fund payment link', time: 'Nov 02', risk: 'Moderate', type: 'URL · Text' },
];
