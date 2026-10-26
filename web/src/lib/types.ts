export type AutonomyBoundary = "drafts" | "assists" | "human_only";
export type TrackDomain = "anti_exploitation" | "nonprofit_ops";

export interface SourceCitation {
  title: string;
  url: string;
  checked_date: string;
}

export interface TrackPack {
  id: string;
  title: string;
  domain: TrackDomain;
  summary: string;
  organizations: string[];
  agent_helps_with: string[];
  human_must_do: string[];
  required_human_only_kinds: string[];
  sources: SourceCitation[];
}

export interface WorkflowStep {
  id: string;
  title: string;
  kind: string;
  boundary: AutonomyBoundary;
  actor: string;
  guidance: string;
}

export interface AgentSkillSpec {
  name: string;
  description: string;
  boundary: "drafts" | "assists";
  instructions: string;
  refuses: string[];
}

export interface MCPToolSpec {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  output_fields: string[];
  read_only: boolean;
}

export interface SyntheticFixture {
  id: string;
  scenario: string;
  sample_input: string;
  expected_indicators: string[];
  expected_human_escalation: boolean;
}

export interface KitDraft {
  kit_id: string;
  track_id: string;
  domain: TrackDomain;
  title: string;
  summary: string;
  target_org: string;
  steps: WorkflowStep[];
  skill: AgentSkillSpec;
  tool: MCPToolSpec;
  checklist: string[];
  sources: SourceCitation[];
  fixtures: SyntheticFixture[];
  drafted_by: string;
  drafted_by_key: string;
}

export interface VerificationReport {
  kit_id: string;
  passed: boolean;
  checks_run: string[];
  issues: string[];
  fixture_count: number;
}

export interface PublishedKit {
  kit: KitDraft;
  verification: VerificationReport;
  reviewed_by: string;
  reviewed_by_key: string;
  review_notes: string;
  steward_signoff?: string | null;
  draft_receipt: string;
  review_receipt: string;
  blob_sha256: string;
  catalog_version: number;
}

export interface CatalogResponse {
  synthetic: boolean;
  two_step_verified: boolean;
  kits: PublishedKit[];
}

export interface TracksResponse {
  synthetic: boolean;
  tracks: TrackPack[];
}

export interface StageSpec {
  queue: string;
  node: string;
  title: string;
  effect_class: string;
  purpose: string;
}

export interface TaskBrief {
  task_id: string;
  repo: string;
  kind: string;
  effect_class: string;
  goal: string;
  read_first: string[];
  touch: string[];
  do_not_touch: string[];
  checks: string[];
  done_when: string[];
  stop_and_ask: string[];
}

export interface RequestsResponse {
  synthetic: boolean;
  stages: StageSpec[];
  requests: TaskBrief[];
}

export interface QueueCount {
  name: string;
  ready: number;
  leased: number;
  waiting: number;
  done: number;
  dead: number;
  cancelled: number;
}

export interface FabricResponse {
  display_name: string;
  plan: string;
  synthetic: boolean;
  queues: QueueCount[];
}
