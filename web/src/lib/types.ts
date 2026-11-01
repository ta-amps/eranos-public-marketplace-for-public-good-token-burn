export type AutonomyBoundary = "drafts" | "assists" | "human_only";
export type TrackDomain = string;
export type VisibilityScope = "surface_only" | "allowlist_surfaces" | "public_commons";

export const OPEN_SPDX_ALLOWLIST = [
  "Apache-2.0",
  "BSD-3-Clause",
  "CC-BY-4.0",
  "CC0-1.0",
  "MIT",
] as const;

export interface SourceCitation {
  title: string;
  url: string;
  checked_date: string;
}

export interface OrgMandate {
  org_type: string;
  serves: string;
  mandate: string;
}

export interface TrackPack {
  id: string;
  title: string;
  domain: TrackDomain;
  domain_label?: string | null;
  summary: string;
  sister_area?: string | null;
  organizations: OrgMandate[];
  allowed_artifacts: string[];
  required_human_only: string[];
  never: string[];
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

export interface CustomArtifactSpec {
  name: string;
  title: string;
  artifact_format: string;
  boundary: "drafts" | "assists";
  summary: string;
  spec: unknown;
}

export interface SyntheticFixture {
  id: string;
  scenario: string;
  sample_input: string;
  expected_indicators: string[];
  expected_human_escalation: boolean;
}

export interface GovernanceMetadata {
  spdx_license: string;
  tags: string[];
  target_cohorts: string[];
  producer_surface: string;
  visibility_scope: VisibilityScope;
  allowed_surfaces: string[];
}

export interface KitRequest extends GovernanceMetadata {
  kit_id: string;
  track_id: string;
  title: string;
  problem_statement: string;
  target_org: string;
  requested_artifacts: string[];
  requires_steward_signoff: boolean;
  requested_by: string;
}

export interface KitDraft extends GovernanceMetadata {
  kit_id: string;
  track_id: string;
  domain: TrackDomain;
  deliverable_kind: string;
  title: string;
  summary: string;
  target_org: string;
  steps: WorkflowStep[];
  skill?: AgentSkillSpec | null;
  skills: AgentSkillSpec[];
  tool?: MCPToolSpec | null;
  tools: MCPToolSpec[];
  artifacts: CustomArtifactSpec[];
  checklist: string[];
  sources: SourceCitation[];
  fixtures: SyntheticFixture[];
  drafted_by: string;
  drafted_by_key: string;
}

export function allSkills(kit: KitDraft): AgentSkillSpec[] {
  const out: AgentSkillSpec[] = [];
  if (kit.skill) out.push(kit.skill);
  for (const s of kit.skills ?? []) {
    if (!out.some((x) => x.name === s.name)) out.push(s);
  }
  return out;
}

export function allTools(kit: KitDraft): MCPToolSpec[] {
  const out: MCPToolSpec[] = [];
  if (kit.tool) out.push(kit.tool);
  for (const t of kit.tools ?? []) {
    if (!out.some((x) => x.name === t.name)) out.push(t);
  }
  return out;
}

export interface VerificationReport {
  kit_id: string;
  passed: boolean;
  checks_run: string[];
  issues: string[];
  fixture_count: number;
  human_only_steps: string[];
}

export interface PublishedKit extends GovernanceMetadata {
  kit: KitDraft;
  verification: VerificationReport;
  reviewed_by: string;
  reviewed_by_key: string;
  review_notes: string;
  steward_signoff?: string | null;
  draft_receipt?: string | null;
  review_receipt?: string | null;
  blob_sha256?: string | null;
  catalog_version: number;
}

export interface PracticeVerifyResponse {
  is_example: boolean;
  passed: boolean;
  persisted: false;
  kit_id: string;
  track_id: string | null;
  spdx_license: string;
  checks_run: string[];
  issues: string[];
  fixture_count: number;
  human_only_steps: string[];
  receipt_sha256: string;
  receipt_scope: "validation_outcome";
  artifact_bound: false;
}

export interface CatalogResponse {
  is_example: boolean;
  two_step_verified: boolean;
  kits: PublishedKit[];
}

export interface TracksResponse {
  is_example: boolean;
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
  schema_version: number;
  task_id: string;
  repo: string;
  title: string;
  kind: string;
  owner_type: string;
  effect_class: string;
  branch: string;
  depends_on: string[];
  context: string[];
  constraints: string[];
  done_when: string;
  notes?: string | null;
}

export interface RequestsResponse {
  is_example: boolean;
  stages: StageSpec[];
  requests: TaskBrief[];
}

export interface QueueCount {
  name: string;
  label?: string;
  ready: number;
  leased: number;
  waiting: number;
  done: number;
  dead: number;
  cancelled: number;
}

/** An organization's need in its own plain words, read from the kit's seed pack (an example). */
export interface ExampleNeed {
  kit_id: string;
  kit_title: string;
  title: string;
  says: string;
  mark: string;
  noun: Record<string, unknown>;
}

/** The recorded example runs: evidence nouns written by the repository's own pipeline. */
export interface ExampleRunsSummary {
  count: number;
  label: string;
  kits: string[];
  outcomes: string[];
  recorded_at: string;
  source_commits: string[];
  model_calls: number;
}

export interface ExamplesResponse {
  is_example: boolean;
  needs: ExampleNeed[];
  runs: ExampleRunsSummary | null;
}

export interface FabricResponse {
  display_name: string;
  plan: string;
  is_example: boolean;
  queues: QueueCount[];
}
