const baseUrl = (process.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');

async function check(path) {
  const response = await fetch(`${baseUrl}${path}`);
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return response.json();
}

const health = await check('/health');
const report = await check('/api/cases/demo-001');
const provenance = await check('/api/cases/demo-001/provenance');
const timeline = await check('/api/cases/demo-001/timeline');
const network = await check('/api/network/demo-001');
const coverage = await check('/api/network/demo-001/coverage');

if (!health.status || !report.case_id || !Array.isArray(timeline.events) || !Array.isArray(network.nodes)) {
  throw new Error('A required API response shape is missing.');
}

console.log(JSON.stringify({
  api: health.status,
  case_id: report.case_id,
  provenance_status: provenance.status,
  timeline_events: timeline.events.length,
  network_nodes: network.nodes.length,
  coverage: coverage === null ? 'not run' : 'returned',
}, null, 2));
