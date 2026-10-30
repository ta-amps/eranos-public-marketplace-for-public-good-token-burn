/**
 * Page text, onboarding steps, the starting brief and request guidance are nouns. They live in
 * Tessera (seeded from `instructions/`), reach the page through `/api/nouns/...`, and are rendered
 * here as given. The page keeps no copy of its own.
 */

export interface NounResponse<T> {
  synthetic: boolean;
  store: string;
  key: string;
  version?: number;
  value: T;
}

export interface NounList<T> {
  synthetic: boolean;
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
