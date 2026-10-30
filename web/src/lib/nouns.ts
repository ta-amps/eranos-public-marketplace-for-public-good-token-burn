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
  warning: string;
  form: RequestForm;
  steps: Step[];
  follow: string;
  form_on_github: string;
  links: { roll_your_own: string };
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
