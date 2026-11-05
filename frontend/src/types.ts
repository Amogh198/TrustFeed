// Shapes of the API's responses. API_CONTRACTS.md is the authority; these only describe it.

export type RiskLevel = 'low' | 'moderate' | 'high' | 'critical' | 'inconclusive';
export type ModuleStatus = 'complete' | 'unavailable' | 'not_applicable';

export interface ModuleResult {
  status: ModuleStatus;
  score: number | null;
  confidence: number | null;
  evidence: string[];
  limitations: string[];
}

export interface Claim {
  id: string;
  text: string;
  verdict: string;
  rationale: string;
}

export interface AnalysisResponse {
  case_id: string;
  created_at: string;
  overall_risk: RiskLevel;
  summary: string;
  modules: Record<string, ModuleResult>;
  claims: Claim[];
  uncertainties: string[];
  recommended_actions: string[];
  is_replay: boolean;
  replay_label: string | null;
}

export interface CaseSummary {
  case_id: string;
  created_at: string;
  overall_risk: RiskLevel;
  summary: string;
  is_replay: boolean;
  replay_label: string | null;
}

export interface CaseHistory {
  cases: CaseSummary[];
  total: number;
}

export interface Benchmark {
  dataset?: string;
  n_real?: number;
  n_fake?: number;
  flagged_fake?: number;
  flagged_real?: number;
  low_fake?: number;
  low_real?: number;
  auc?: number | null;
  measured_at?: string;
  applies_to?: string;
}

export interface ExplanationCheck {
  check_id: string;
  module: string;
  label: string;
  legacy_alias?: boolean;
  status: string | null;
  result: string;
  reasoning: string | string[];
  benchmark: Benchmark | null;
  artifacts: Record<string, string>[];
  limitations: string[];
}

export interface Explanation {
  case_id: string;
  what_was_submitted: string[];
  what_was_detected: string[];
  supports: string[];
  refutes: string[];
  uncertainties: string[];
  checks: ExplanationCheck[];
  missing_checks: { module: string; status: string; reason: string }[];
}

export interface Appearance {
  id: string;
  page_url: string | null;
  page_title: string | null;
  domain: string | null;
  platform: string;
  image_url: string | null;
  match_type: string;
  phash_distance: number | null;
  observed_at: string | null;
  date_source: string;
  date_evidence: string | null;
  provider: string;
}

export interface ProvenanceReport {
  case_id: string;
  status: string;
  searched_at: string | null;
  replay: boolean;
  synthetic: boolean;
  media_sha256: string | null;
  phash: string | null;
  providers: { name: string; status: string; result_count: number | null; limitation: string | null }[];
  earliest_found: {
    appearance_id: string;
    observed_at: string | null;
    date_source: string;
    caveat: string;
  } | null;
  appearances: Appearance[];
  limitations: string[];
}

export interface TimelineEvent {
  at: string | null;
  kind: string;
  label: string;
  module: string;
  ref: string;
  date_source: string;
  synthetic: boolean;
}

export interface GraphNode {
  id: string;
  handle: string;
  followers?: number | null;
  role: string;
  role_label: string;
  cluster_id: string | null;
  in_flagged_cluster: boolean;
  weighted_degree?: number;
  post_count: number;
  platforms?: string[];
  appears_at: string | null;
  synthetic?: boolean;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  weight?: number;
  signals?: Record<string, number>;
  platforms?: string[];
  cross_platform?: boolean;
  median_delay_seconds?: number | null;
  first_seen_at: string | null;
  cluster_id?: string | null;
  synthetic?: boolean;
}

export interface TimelineFrame {
  start: string;
  post_count: number;
  cluster_member_post_count: number;
}

export interface NetworkPayload {
  nodes: GraphNode[];
  edges: GraphEdge[];
  timeline: TimelineFrame[];
}

export interface CoveragePlatform {
  platform: string;
  label: string;
  status: string;
  matching_posts: number;
  notes?: string[];
}

export interface NotConnected {
  platform: string;
  reason: string;
}

export interface SpreadPost {
  order: number;
  platform: string;
  account_id: string;
  handle: string;
  posted_at: string;
  permalink: string | null;
  matched_on: string;
  repost_count: number | null;
  earliest_found: boolean;
}

export interface Coverage {
  mode?: string;
  searched_at?: string;
  synthetic?: boolean;
  platforms?: CoveragePlatform[];
  not_connected?: NotConnected[];
  account_histories?: { read?: number };
  spread?: SpreadPost[];
}

export interface ActionPacket {
  case_id: string;
  generated: boolean;
  label: string;
  draft: string;
  evidence_references: string[];
  sections: { heading: string; items: string[] }[];
}

export interface Scenario {
  id: string;
  title: string;
  description: string;
  label: string;
}

export interface Heatmap {
  status: string;
  label: string;
  grid_size: number;
  base_score: number | null;
  max_change: number | null;
  notable: boolean;
  reasoning: string;
  limitations: string[];
  png_base64: string | null;
}

export interface WatchSnapshot {
  poll: number;
  polled_at: string;
  platforms_read: string[];
  new_posts: Record<string, number>;
  total_matching_posts: number;
  alerts: { message: string }[];
  platforms?: CoveragePlatform[];
  not_connected?: NotConnected[];
}
