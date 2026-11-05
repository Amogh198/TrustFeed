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
const explanation = await check('/api/cases/demo-001/explanation');
const story = await check('/api/cases/demo-story-001');
const storyCoverage = await check('/api/network/demo-story-001/coverage');
const monitors = await check('/api/monitors');

if (!Array.isArray(explanation.checks) || !explanation.checks.length) throw new Error('The explanation has no checks.');
if (!story.is_replay || !storyCoverage?.synthetic) throw new Error('The demo story must be labelled as synthetic replay.');
if (!report.is_replay) throw new Error('demo-001 must be labelled as synthetic.');
if (!Array.isArray(monitors.watches)) throw new Error('The monitor list is missing.');

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
  explanation_checks: explanation.checks.length,
  story_posts: storyCoverage.spread.length,
}, null, 2));
