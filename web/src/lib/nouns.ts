/**
 * Page text, onboarding steps, the starting brief and request guidance are nouns. They live in
 * Tessera (seeded from `instructions/`), reach the page through `/api/nouns/...`, and are rendered
 * here as given. The page keeps no copy of its own.
 */

export interface NounResponse<T> {
  is_example: boolean;
  store: string;
  key: string;
  version?: number;
  value: T;
}

export interface NounList<T> {
  is_example: boolean;
  store: string;
  records: { key: string; version: number; value: T }[];
}

export interface Step {
  id: string;
  title: string;
  detail: string;
  example?: string;
}

export interface HelpNoun {
  title: string;
  summary: string;
  command: string;
  command_note: string;
  brief: string;
  brief_interests_goal: string;
  steps: Step[];
  links: { roll_your_own: string; connect: string };
  ui: { copy: string; copied: string; copy_failed: string };
}

export interface RequestForm {
  label: string;
  hint: string;
  placeholder: string;
  links_label: string;
  links_hint: string;
  name_label: string;
  type_label: string;
  causes_label: string;
  consent: string;
  submit: string;
  sending: string;
  sent: string;
  planned: string;
  follow: string;
  offline: string;
  refused: string;
}

export interface NonprofitsNoun {
  title: string;
  /** The page's opening, in plain words: what a nonprofit can ask for. */
  lede: string;
  /** Who needs an AI agent of their own, and for what. */
  no_agent: string;
  warning: string;
  form: RequestForm;
  /** The heading over the steps, which come before the box. */
  next_title: string;
  steps: Step[];
  /** The honest state of the hosted queues. */
  hosted: string;
  follow: string;
  form_on_github: string;
  links: { roll_your_own: string };
}

/** The connect page's text: the `eranos.instructions/connect` noun. The same two sentences are in /connect.json. */
export interface ConnectNoun {
  title: string;
  authentication: string;
  restrictions: string;
  anonymous_link: string;
  key_link: string;
  anonymous_note: string;
  bearer_note: string;
  machine_link: string;
  links: { fabric_connect: string; machine: string };
}

export interface PlanNoun {
  request_id: string;
  plain: string[];
  parts: { part: number; route: string }[];
  next_step: string;
}

/** The starting brief with the reader's interests, composed locally and never sent anywhere. */
export function briefWithInterests(noun: HelpNoun, interests: string): string {
  const body = noun.brief.split("\n\n").slice(1).join("\n\n");
  return `${noun.brief_interests_goal} ${JSON.stringify(interests.trim().slice(0, 1500))}\n\n${body}`;
}

/** The site's headline, subline, title, intro and privacy line: the `eranos.instructions/site` noun. */
export interface SiteNoun {
  headline: string;
  subline: string;
  title: string;
  brand_sub: string;
  intro: string;
  /** What the site loads and keeps: no analytics, ads or cookies, and where requests go. */
  privacy: string;
}

/** A link a noun names: an app page (`to`) or any other address (`href`). */
export interface NounLink {
  label: string;
  to?: string;
  href?: string;
  external?: boolean;
  match?: string;
}

/** Plural-aware wording: "1 open task" or "{n} open tasks". */
export interface CountWords {
  none?: string;
  one: string;
  many: string;
}

/** The header, phone menu, notice line and footer: `eranos.instructions/shell`. */
export interface ShellNoun {
  skip: string;
  home_label: string;
  nav_label: string;
  nav: NounLink[];
  /** The right-hand link (SiteHeader, 20:15): How it works, on Agora. */
  right?: NounLink;
  external_note: string;
  menu: { button: string; open_label: string; close: string; close_label: string; sheet_label: string };
  /** SiteFooter v2 (ta-amps.footer/2, Nov 2): the brand, ONE row of links in the canonical order, and one short line. */
  footer: { brand?: string; line: string; links_label: string; links: NounLink[] };
  /** What a page that failed to draw says instead of going blank (the app's error boundary). */
  page_error?: { title: string; body: string; reload: string; home: string };
}

/** The home page: `eranos.instructions/home`. */
export interface HomeNoun {
  eyebrow: string;
  buttons_label: string;
  /** Exactly two, in this order: "My NGO needs help", then "I want to help". */
  buttons: { id: string; label: string; to: string; sub?: string; sub_short?: string }[];
  honesty: string;
  honesty_short?: string;
  /** The hero's line under the headline (EranosHome); the site noun's subline when absent. */
  lead?: string;
  /** The hero's four tiles: the request flow's steps, lit once after load (owner, Nov 1 evening). */
  tiles?: string[];
  /** The four process tiles with their lines (copy contract v1, eranos.home), in the split hero's right column. */
  process?: { label: string; steps: { title: string; text: string; text_short?: string }[] };
  gets: {
    title: string;
    items: { id: string; tag?: string; title: string; line: string; examples?: string[]; link?: string; to?: string }[];
  };
  how: { title: string; title_short: string; link: string; to: string; steps: { title: string; detail: string; short: string }[] };
  now: {
    title: string;
    requests: CountWords;
    open: CountWords;
    working: CountWords;
    kits: CountWords;
    swarm?: string;
    note: string;
  };
  safety: { title: string; items: { q: string; a: string; a_short: string }[] };
  /** The "Right now" strip under the doors (LiveMapStrip, site eranos): live, quiet, empty and off states. */
  right_now?: RightNowWords;
}

export interface RightNowWords {
  eyebrow: string;
  label: string;
  headline: string;
  headline_short: string;
  sub: string;
  last: string;
  last_continent: string;
  declared: string;
  not_declared: string;
  cta: string;
  cta_href: string;
  quiet_title: string;
  quiet_text: string;
  empty_title: string;
  empty_text: string;
  empty_cta: string;
  empty_to: string;
  off_title: string;
  off_text: string;
}

/** The request box and its page: `eranos.instructions/nonprofits-page`. */
export interface ChoiceOption {
  value: string;
  label: string;
  hint?: string;
  tip?: string;
  tip_label?: string;
  tip_title?: string;
  example?: string;
}

export interface AdvancedQuestion {
  id: "start" | "skill" | "runs" | "agents" | "models" | "tools" | "limits";
  label: string;
  pick: "one" | "any";
  other?: boolean;
  default?: string;
  options: string[];
}

export interface AdvancedWords {
  summary: string;
  optional: string;
  count_none: string;
  count_some: string;
  intro: string;
  questions: AdvancedQuestion[];
  pick_one: string;
  pick_any: string;
  other: { button: string; open: string; chosen: string; placeholder: string; aria: string };
  improve: {
    value: string;
    link_label: string;
    link_placeholder: string;
    what_label: string;
    what_placeholder: string;
    recent_label: string;
    recent_none: string;
  };
  footer: string;
  clear: string;
}

export interface NonprofitsPageNoun {
  eyebrow: string;
  heading: string;
  lead: string;
  bounds: { head: string; body: string };
  output: { legend: string; hint: string; options: ChoiceOption[] };
  frequency: {
    legend: string;
    options: ChoiceOption[];
    cadence_label: string;
    default_cadence: string;
    cadences: ChoiceOption[];
    help: Record<"process_once" | "process_regular" | "information_once" | "information_regular" | "none", string>;
  };
  advanced: AdvancedWords;
  form: {
    label: string;
    hint: string;
    placeholder: string;
    examples_label: string;
    examples: { id: string; short: string; text: string; output_type: string; frequency: string; cadence?: string }[];
    privacy: string;
    check: {
      lead: string;
      ask: string;
      kinds: Record<string, string>;
      and: string;
      empty: string;
      clean: string;
      case_hint?: string;
      case_kinds?: Record<string, string>;
    };
    placeholders: { process: string; information: string; none: string };
    min_chars: number;
    switch: { text: string; action: string };
    ready_note: string;
    not_ready: Record<"lead" | "lead_after" | "and" | "output" | "need" | "private" | "consent" | "name" | "type" | "improve", string>;
    too_short: { head: string; body: string };
    name_label: string;
    type_label: string;
    type_placeholder: string;
    profile_note: string;
    details_summary: string;
    links_label: string;
    links_hint: string;
    causes_label: string;
    consent: string;
    send: string;
    sending: string;
    waiting_connection: string;
    after_send: string;
    hosted: string;
    missing: { need: string; name: string; type: string; consent: string; output: string; frequency: string; cadence: string };
    draft_saved: string;
  };
  states: {
    refused: { head: string; personal: string; other: string; not_filed: string; action: string };
    quota: { head: string; body: string; action: string; copied: string };
    rate: { head: string; body: string };
    offline: { head: string; body: string };
    snapshot: string;
  };
  aside: {
    next_title: string;
    steps: { title: string; detail: string }[];
    example_link: string;
    example_to: string;
    kinds_title: string;
    kinds: { name: string; line: string; link: string; to: string }[];
    kits_link: string;
    kits_to: string;
  };
}

type Words = Record<string, string>;

/** The request status and report pages: `eranos.instructions/request-status`. */
export interface RequestStatusNoun {
  titles: Words;
  meta: Words;
  /** How the request's own choices read: what kind of output, and how often. */
  choices: { output: Words; frequency: Words };
  result: Words;
  modes: Words;
  actions: Words;
  diagram: Words;
  nodes: Words;
  states: Words;
  chips: Words;
  overall: Words;
  list: Words;
  log: Words;
  queue: Words;
  stay: Words;
  about: Words;
  summary: Words;
  notices: Record<string, Words>;
  report: Words;
  legend: { title: string; items: { state: string; text: string }[]; motion: string };
  added: Words;
  yours: Words;
  plain: PlainWords;
  /** How a page names a model when the models.meta Task Object has no display name for it. */
  model_names?: { fallback: string; own: string };
  steps: Record<"tag_process" | "tag_information" | "tag_checked" | "tag_updating" | "tag_updated" | "back" | "what" | "only_person" | "practice" | "practice_lead" | "practice_message" | "run" | "run_lead" | "agent_message" | "copy" | "copied" | "show_how" | "hide_how" | "in_short" | "in_short_note" | "checked_how" | "download" | "download_note" | "curious", string>;
  decide: Record<"title" | "lead_process" | "lead_information" | "yes" | "changes" | "changes_label" | "changes_note" | "send" | "cancel" | "done_head" | "done_body" | "pending_head" | "pending_body" | "band_title" | "band_adding" | "band_added" | "band_none" | "band_some" | "band_link", string>;
  library_link: string;
}

/** The volunteer page: `eranos.instructions/help-page`. */
export interface HelpPageNoun {
  eyebrow: string;
  heading: string;
  lead: string;
  connect: Words;
  tasks: HelpTasksWords;
  tokens: {
    title: string;
    empty: string;
    key_note: string;
    example_title: string;
    example_chip: string;
    example_caption: string;
    rows: { tone: "real" | "caution"; head: string; body: string; receipts: string }[];
  };
  agent: Words;
  rules: { title: string; lines: string[] };
  safety: string;
  safety_link: string;
  states: Words;
  /** The network map notice (network map contract v1): claims show by Cloudflare data centre, never by home. */
  map_notice?: string;
}

/** The `tasks` part of the volunteer page noun, whose `kinds` names each Eranos queue's work. */
export interface HelpTasksWords {
  title: string;
  live: string;
  /** The open Tasks on the shared queue (Herma), listed under Eranos's own. */
  shared_title?: string;
  shared_count?: string;
  shared_tier?: Record<string, string>;
  shared_link?: string;
  shared_href?: string;
  shared_none?: string;
  kinds: Record<string, string>;
  count_one: string;
  count_many: string;
  guard_note: string;
  list_note: string;
  empty_head: string;
  empty_body: string;
  unavailable: string;
  slow_down: { head: string; body: string };
  by_kind: Record<string, string>;
  copy_for_agent: string;
  copied: string;
  claim_text: string;
  waiting: string;
  minutes: string;
  hours: string;
  days: string;
  check_needs_key: string;
  first_pick: string;
  swarm_head?: string;
  swarm_body?: string;
}

/** Fills `{name}` holes in noun text. A hole without a value stays visible, so a gap is never hidden. */
export function fill(template: string, values: Record<string, string | number> = {}): string {
  return template.replace(/\{(\w+)\}/g, (hole, name: string) =>
    Object.hasOwn(values, name) ? String(values[name]) : hole,
  );
}

/** "1 open task" or "3 open tasks" (or the `none` wording for zero, when the noun has one). */
export function countWords(words: CountWords, n: number): string {
  if (n === 0 && words.none) return words.none;
  return n === 1 ? words.one : fill(words.many, { n });
}

type T = string;
/** The request page's plain view (Flow-Prototype step 3). */
export interface PlainWords {
  sent_line: T;
  sent_line_key: T;
  technical_line: T;
  show_technical: T;
  show_simple: T;
  chip: Record<
    | "in_line"
    | "planning"
    | "waiting_volunteer"
    | "making"
    | "waiting_check"
    | "checking"
    | "changes"
    | "ready"
    | "in_use"
    | "in_use_regular"
    | "in_use_plain"
    | "sent_back"
    | "ready_public"
    | "decided"
    | "not_used"
    | "withdrawn"
    | "blocked"
    | "unfinished",
    T
  > &
    /** reused: a request answered from the library with no new work (F-UI-STALE-001); the fit check's states. */
    Partial<Record<"reused" | "reused_unchecked" | "reuse_does_not_fit", T>>;
  /** Over the steps when a closed request was opened again: after an undone library answer, with a reason, or plain. */
  reopened_note?: T;
  reopened_note_reason?: T;
  reopened_note_plain?: T;
  stages_label: T;
  stages: {
    sent: { title: T; done: T };
    line: { title: T; ahead_many: T; ahead_one: T; next: T; waiting: T; done: T };
    made: { title: T; upcoming: T; planning: T; between: T; making: T; changes: T; done: T; stopped?: T };
    checked: { title: T; upcoming: T; waiting: T; checking: T; done: T };
    ready: { title: T; upcoming: T; now: T; done: T; decided: T };
    shared: { title: T; upcoming: T; done: T };
  };
  making_title: T;
  making: { process: T[]; information: T[] };
  kind: { process: T; information: T };
  tags: { not_yet: T; made: T; checked: T; changing: T };
  happened_title: T;
  happened_more: T;
  happened: Record<"received" | "queued" | "queued_next" | "plan_claimed" | "planned" | "blocked" | "work_claimed" | "work_claimed_changes" | "work_released" | "work_released_reason" | "work_submitted" | "work_submitted_changes" | "check_claimed" | "check_claimed_changes" | "check_sent_back" | "ready" | "ready_changes" | "signoff_required" | "decided_use" | "decided_changes" | "decided_dont" | "library_added" | "withdrawn" | "closed" | "closed_unfinished" | "check_refused" | "work_claimed_eranos" | "reused" | "scheduled" | "work_failed", T> &
    Partial<Record<"plan_claimed_eranos" | "check_claimed_eranos" | "check_claimed_changes_eranos" | "reopened" | "reopened_reason" | "reopened_plain" | "reuse_fits" | "reuse_does_not_fit", T>>;
  share_lead: T;
  share: T;
  shared: T;
  share_text: T;
  ready_title: T;
  every: Record<string, T>;
  tab_title: T;
  private_line: T;
  copy_link: T;
  copied_link: T;
  /** The request track's six stations (owner v2, Nov 1): the name while the request is there, and otherwise. */
  track: { stations: { now: T; now_public?: T; other: T }[]; token: T; token_public: T; token_done: T; done?: T; next?: T; skipped?: T };
  bands: {
    sorted: Record<"title" | "process" | "information" | "checked" | "waiting", T>;
    made: Record<
      | "title_now" | "title_done" | "helper_volunteer" | "helper_eranos" | "picked" | "picked_eranos" | "waiting" | "fallback" | "recorded"
      | "models_link" | "models_href" | "failed" | "retry" | "retry_count",
      T
    > &
      Partial<Record<"title_reused", T>>;
    checked: Record<"title" | "rule" | "blocked" | "sent_back_one" | "sent_back_many" | "waiting" | "checking" | "done" | "upcoming", T> &
      Partial<Record<"title_eranos" | "checking_eranos" | "title_reused", T>>;
    ready: Record<
      | "title" | "title_public" | "process" | "information" | "open_process" | "open_information" | "decide" | "decide_link"
      | "library_title" | "library_added" | "library_link" | "library_how" | "upcoming" | "reused" | "reused_link" | "next_run",
      T
    > &
      Partial<Record<"title_done", T>>;
    /** Each band's one-line status in its header (the accordion, owner Nov 1). */
    status: Record<
      "done" | "done_untimed" | "sorting" | "working" | "waiting_helper" | "checking" | "waiting_check" | "sent_back" | "your_turn" | "their_turn" | "signoff" | "upcoming",
      T
    > &
      /** closed: a step the request closed before reaching; reused_*: each step of a request answered from the library. */
      Partial<
        Record<
          | "closed" | "reused_sorted" | "reused_made" | "reused_ready" | "reuse_fits" | "reuse_fits_untimed" | "reuse_does_not_fit"
          | "reuse_unchecked" | "reuse_waiting_check",
          T
        >
      >;
    /** What each step says for a request answered from the library, and of the check that it fits (F-REUSE-001). */
    reused?: Partial<Record<"sorted" | "made" | "fits" | "fits_by" | "no_model" | "does_not_fit" | "unchecked", T>>;
  };
}

export interface TrustAction {
  label: string;
  href: string;
  primary?: boolean;
}

export interface TrustSection {
  heading: string;
  items: string[];
}

export interface TrustPageContent {
  kicker: string;
  title: string;
  tab_title: string;
  intro: string;
  actions?: TrustAction[];
  sections: TrustSection[];
  footer: string;
}

export interface NotFoundNoun {
  kicker: string;
  title: string;
  intro: string;
  cards: { to: string; title: string; body: string }[];
}

export interface TourStepNoun {
  step: number;
  label: string;
  to?: string;
  href?: string;
  next_label: string;
  next_to?: string;
  next_href?: string;
}

export interface JudgeTourNoun {
  label: string;
  close: string;
  close_label: string;
  steps: TourStepNoun[];
}

/** Privacy, terms, report, 404 guidance and the opt-in judge tour: `eranos.instructions/trust`. */
export interface TrustNoun {
  privacy: TrustPageContent;
  terms: TrustPageContent;
  report: TrustPageContent;
  not_found: NotFoundNoun;
  tour: JudgeTourNoun;
}
