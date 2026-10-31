export interface ReusedPiece {
  name: string;
  kind: "noun" | "verb";
  status: "checked";
}

export interface RequestStatusPayload {
  synthetic: boolean;
  request_id: string;
  kit_id: string;
  kit_title: string;
  status: "queued" | "splitting" | "building" | "reviewing" | "delivered";
  submitted_at: string;
  organization_type: string;
  plain_need: string;
  privacy_guarantee: string;
  split: {
    verb: string;
    queue: string;
    receipt: string;
    private_lane: {
      label: string;
      policy: string;
      items: string[];
      outcome_title: string;
      outcome_detail: string;
    };
    public_lane: {
      label: string;
      policy: string;
      items: string[];
      outcome_title: string;
      checks: string[];
    };
  };
  queue_build: {
    queue: string;
    verb: string;
    worker_id: string;
    harness: string;
    lease_minutes: number;
    fencing_token: number;
    claim_receipt: string;
    reused_pieces: ReusedPiece[];
    build_receipt: string;
  };
  independent_review: {
    queue: string;
    rule: string;
    self_approval_refusal: {
      actor: string;
      role: string;
      http_status: number;
      reason: string;
      receipt: string;
    };
    reviewer_approval: {
      actor: string;
      role: string;
      harness: string;
      checks_passed: number;
      summary: string;
      receipt: string;
    };
    cli_transcript: string[];
  };
  steward_and_delivery: {
    steward_signed_off: boolean;
    steward_id: string;
    steward_note: string;
    steward_receipt: string;
    catalog_path: string;
    public_report_summary: string;
  };
}

export const SHOWCASE_REQUESTS: Record<string, RequestStatusPayload> = {
  "REQ-INTAKE-07": {
    synthetic: true,
    request_id: "REQ-INTAKE-07",
    kit_id: "KIT-TRANSCR-07",
    kit_title: "Handwritten Statements to Text Kit",
    status: "delivered",
    submitted_at: "2026-10-31T19:00:00Z",
    organization_type: "Community shelter and neighborhood intake coalition",
    plain_need:
      "We have a folder of handwritten intake statements. We need them typed up, keeping how people actually talk, plus a monthly report for our funders that cites this year's state shelter budget.",
    privacy_guarantee:
      "Private handwritten statements stay on the nonprofit's own computer; donated volunteer agents never see personal files.",
    split: {
      verb: "eranos.triage-and-split",
      queue: "eq01",
      receipt: "91c4e20b8f3a11d4c6e87a205b9f3c1e74d02a8b5c61e9f01234abcd5678ef90",
      private_lane: {
        label: "Their own files",
        policy: "Files stay inside the nonprofit",
        items: [
          "Type up the handwritten statements, keeping how people actually talk",
          "Monthly report from our own program numbers",
        ],
        outcome_title: "Local agent kit (KIT-TRANSCR-07)",
        outcome_detail:
          "A kit their own agent runs locally. The statements never go to Eranos or the volunteers.",
      },
      public_lane: {
        label: "Only public information",
        policy: "Donated volunteer agents finish and cite it",
        items: ["This year's enacted state shelter budget lines, cited line by line"],
        outcome_title: "Finished cited report",
        checks: [
          "Every claim cited to public state budget tables",
          "Reviewed by a different volunteer's agent",
          "A person at the nonprofit decides how it is used",
        ],
      },
    },
    queue_build: {
      queue: "eq02",
      verb: "eranos.draft-and-verify-kit",
      worker_id: "volunteer-a (volunteer-drafter-07)",
      harness: "Muse Code 1.4.14 via Herma < 2 ms shim",
      lease_minutes: 30,
      fencing_token: 1,
      claim_receipt: "303ec10975484941132c8bf32019f94a173ad377d88bb1c9716e5569d7710d26",
      reused_pieces: [
        { name: "skills", kind: "noun", status: "checked" },
        { name: "connection", kind: "noun", status: "checked" },
        { name: "knowledge", kind: "noun", status: "checked" },
        { name: "working files", kind: "noun", status: "checked" },
        { name: "step map", kind: "verb", status: "checked" },
        { name: "tests", kind: "noun", status: "checked" },
      ],
      build_receipt: "436bc9a8d2104e9b88a712c3f9015e4b77d21c6a9804b12e3f445566778899aa",
    },
    independent_review: {
      queue: "eq03",
      rule: "drafter != reviewer across both worker ID and Tessera key ID",
      self_approval_refusal: {
        actor: "volunteer-a",
        role: "builder",
        http_status: 409,
        reason: "Refused: the builder can't approve its own kit.",
        receipt: "7749158fe0192b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4",
      },
      reviewer_approval: {
        actor: "volunteer-b (volunteer-reviewer-07)",
        role: "independent reviewer",
        harness: "Claude Code / OpenCode worker",
        checks_passed: 8,
        summary:
          "Claimed eq03 review lease, re-ran all 8 boundary, SPDX, citation and synthetic-case checks independently, and approved.",
        receipt: "2c97c1b6a584736251403928172635445566778899aabbccddeeff0011223344",
      },
      cli_transcript: [
        "› eranos claim --queue eq02 --worker volunteer-a",
        "  leased KIT-TRANSCR-07 · exclusive 30m lease · fencing_token 1 · only volunteer-a can submit",
        "  claim receipt 303ec10975484941…",
        "› eranos build-and-check KIT-TRANSCR-07 --synthetic-cases",
        "  reused from seed packs: skills · connection · knowledge · working files · step map · tests",
        "  8/8 deterministic checks pass · submitted build receipt 436bc9a8d2104e9b…",
        "› eranos review --approve KIT-TRANSCR-07 --worker volunteer-a",
        "  ✗ 409 refused: two-step rule, builder volunteer-a cannot approve its own kit (receipt 7749158f…)",
        "› eranos review --approve KIT-TRANSCR-07 --worker volunteer-b",
        "  ✓ independent checks pass · approved by volunteer-b · receipt 2c97c1b6a5847362…",
      ],
    },
    steward_and_delivery: {
      steward_signed_off: true,
      steward_id: "records-steward-lead",
      steward_note:
        "Sensitive kits wait for a person's sign-off. Checking flagged readings, in-person safety follow-up, and sharing outside the organization stay strictly person-only.",
      steward_receipt: "88e1f09a7c6b5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4a3b2c1d0e",
      catalog_path: "/catalog/KIT-TRANSCR-07",
      public_report_summary:
        "Enacted State Shelter & Supportive Housing Appropriations Summary (12 public budget lines cited and cross-checked).",
    },
  },
  "REQ-SHIFT-05": {
    synthetic: true,
    request_id: "REQ-SHIFT-05",
    kit_id: "KIT-SHIFT-05",
    kit_title: "Community Pantry Shift Onboarding & Incident Escalation SOP Pack",
    status: "delivered",
    submitted_at: "2026-10-31T18:20:00Z",
    organization_type: "Mutual-aid pantry and mobile meal team",
    plain_need:
      "We onboard weekend pantry volunteers in 15 minutes and need clear shift role cards, handoff checklists, and a person-led escalation tree alongside public health food-safety temperature citations.",
    privacy_guarantee:
      "Internal volunteer rosters and incident notes remain inside the pantry; volunteers build a local SOP kit.",
    split: {
      verb: "eranos.triage-and-split",
      queue: "eq01",
      receipt: "52a1b9c8d7e6f504132231405968778695a4b3c2d1e0f9a8b7c6d5e4f3a2b1c0",
      private_lane: {
        label: "Their own files",
        policy: "Files stay inside the nonprofit",
        items: ["Weekend volunteer shift role cards and internal handoff notes"],
        outcome_title: "Local agent kit (KIT-SHIFT-05)",
        outcome_detail: "Runs locally on pantry staff laptops; zero roster data uploaded.",
      },
      public_lane: {
        label: "Only public information",
        policy: "Donated volunteer agents finish and cite it",
        items: ["Published county food-safety holding-temperature rules, cited"],
        outcome_title: "Finished cited reference sheet",
        checks: [
          "Every rule linked to published health code",
          "Reviewed by a second volunteer's agent",
          "Site lead decides shift rules",
        ],
      },
    },
    queue_build: {
      queue: "eq02",
      verb: "eranos.draft-and-verify-kit",
      worker_id: "volunteer-c",
      harness: "Claude Code via Herma shim",
      lease_minutes: 30,
      fencing_token: 1,
      claim_receipt: "1199aa22bb33cc44dd55ee66ff77889900112233445566778899aabbccddeeff",
      reused_pieces: [
        { name: "skills", kind: "noun", status: "checked" },
        { name: "knowledge", kind: "noun", status: "checked" },
        { name: "working files", kind: "noun", status: "checked" },
        { name: "step map", kind: "verb", status: "checked" },
        { name: "tests", kind: "noun", status: "checked" },
      ],
      build_receipt: "66778899aabbccddeeff00112233445566778899aabbccddeeff001122334455",
    },
    independent_review: {
      queue: "eq03",
      rule: "drafter != reviewer across both worker ID and Tessera key ID",
      self_approval_refusal: {
        actor: "volunteer-c",
        role: "builder",
        http_status: 409,
        reason: "Refused: the builder can't approve its own kit.",
        receipt: "99887766554433221100ffeeddccbbaa99887766554433221100ffeeddccbbaa",
      },
      reviewer_approval: {
        actor: "volunteer-d",
        role: "independent reviewer",
        harness: "Muse Code 1.4.14",
        checks_passed: 8,
        summary: "Verified crisis_safety_plan and individual_decision remain human_only.",
        receipt: "445566778899aabbccddeeff00112233445566778899aabbccddeeff00112233",
      },
      cli_transcript: [
        "› eranos claim --queue eq02 --worker volunteer-c",
        "  leased KIT-SHIFT-05 · exclusive 30m lease · fencing_token 1",
        "› eranos review --approve KIT-SHIFT-05 --worker volunteer-d",
        "  ✓ approved by volunteer-d · published to eranos.catalog",
      ],
    },
    steward_and_delivery: {
      steward_signed_off: true,
      steward_id: "ops-steward-lead",
      steward_note: "Crisis safety planning and incident command remain strictly person-only.",
      steward_receipt: "2233445566778899aabbccddeeff00112233445566778899aabbccddeeff0011",
      catalog_path: "/catalog/KIT-SHIFT-05",
      public_report_summary: "Published County Food-Safety Cold/Hot Holding Reference Table.",
    },
  },
};

export function buildLiveQueuedRequestStatus(requestId: string, customNeed?: string): RequestStatusPayload {
  const cleanNeed =
    customNeed && customNeed.trim().length > 0
      ? customNeed.trim()
      : "Submitted nonprofit request filed onto Tessera queue eq01 (scope and sort-and-split). Waiting for an authorized volunteer worker to claim.";
  return {
    synthetic: true,
    request_id: requestId,
    kit_id: "KIT-TRANSCR-07",
    kit_title: "Pending Scope & Kit Assignment",
    status: "queued",
    submitted_at: new Date().toISOString(),
    organization_type: "Nonprofit requester session",
    plain_need: cleanNeed,
    privacy_guarantee:
      "Requests hold only plain-words job descriptions and public links. Private files stay with your organization.",
    split: {
      verb: "eranos.triage-and-split",
      queue: "eq01",
      receipt: "queued-on-tessera-eq01",
      private_lane: {
        label: "Their own files",
        policy: "Files stay inside the nonprofit",
        items: ["Any step touching internal folders or records becomes a local kit"],
        outcome_title: "Local agent kit (queued)",
        outcome_detail: "A volunteer's agent will draft and test a kit you run locally.",
      },
      public_lane: {
        label: "Only public information",
        policy: "Donated volunteer agents finish and cite it",
        items: ["Publicly published budgets, statutes, or directories"],
        outcome_title: "Cited public research (queued)",
        checks: [
          "Every claim cited to public sources",
          "Reviewed by a second volunteer's agent",
          "Your staff decide how to use it",
        ],
      },
    },
    queue_build: {
      queue: "eq02",
      verb: "eranos.draft-and-verify-kit",
      worker_id: "waiting-for-volunteer-claim",
      harness: "Any connected MCP / Herma worker",
      lease_minutes: 30,
      fencing_token: 0,
      claim_receipt: "awaiting-claim",
      reused_pieces: [
        { name: "skills", kind: "noun", status: "checked" },
        { name: "connection", kind: "noun", status: "checked" },
        { name: "knowledge", kind: "noun", status: "checked" },
        { name: "working files", kind: "noun", status: "checked" },
        { name: "step map", kind: "verb", status: "checked" },
        { name: "tests", kind: "noun", status: "checked" },
      ],
      build_receipt: "awaiting-build",
    },
    independent_review: {
      queue: "eq03",
      rule: "drafter != reviewer across both worker ID and Tessera key ID",
      self_approval_refusal: {
        actor: "builder-guard",
        role: "policy gate",
        http_status: 409,
        reason: "Active: the builder will be blocked from approving its own kit.",
        receipt: "enforced-by-tessera",
      },
      reviewer_approval: {
        actor: "awaiting-second-volunteer",
        role: "independent reviewer",
        harness: "Second donor worker",
        checks_passed: 8,
        summary: "A second volunteer's agent must independently verify all 8 deterministic checks before catalog publication.",
        receipt: "awaiting-review",
      },
      cli_transcript: [
        `› tessera get_task ${requestId} --queue eq01`,
        "  status: ready · waiting for volunteer worker claim (claim · do · report)",
      ],
    },
    steward_and_delivery: {
      steward_signed_off: false,
      steward_id: "pending-steward",
      steward_note: "Sensitive kits wait for human steward sign-off before publication.",
      steward_receipt: "pending",
      catalog_path: "/catalog/KIT-TRANSCR-07",
      public_report_summary: "Example completed flow available at /requests/REQ-INTAKE-07.",
    },
  };
}
