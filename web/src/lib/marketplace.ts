/**
 * Plain words and links shared by the home page and the two sides of the marketplace.
 *
 * Eranos is the two-sided marketplace and Agora is the one overview of how everything works, so
 * "how it works" and "connect your agent" point to Agora. Eranos produces agent kits; never call them
 * tools. An agent kit is a seed pack of nouns and verbs made for one organization's agent.
 */

export const ERANOS_REPO_URL = "https://github.com/ta-amps/eranos-public-marketplace-for-public-good-token-burn";
/** GitHub issue form in this repo (`.github/ISSUE_TEMPLATE/request-a-kit.yml`). Nothing is stored here. */
export const REQUEST_KIT_URL = `${ERANOS_REPO_URL}/issues/new?template=request-a-kit.yml`;
export const PACK_LIBRARY_URL = "https://github.com/ta-amps/seed-packs-library-of-nouns-and-verbs";

export const AGORA_URL = "https://ta-amps.github.io/agora-public-overview-architecture-setup-and-contribution/";
export const AGORA_HOW_IT_WORKS_URL = `${AGORA_URL}docs/how-it-works/`;
export const AGORA_CONNECT_AGENT_URL = `${AGORA_URL}contribute/#agent`;

export const HELP_DOOR = {
  to: "/help",
  label: "I want to help",
  note: "Connect your own agent and donate the tokens you won't use.",
} as const;

export const NGO_DOOR = {
  to: "/nonprofits",
  label: "I'm an NGO looking for agentic solutions",
  note: "See reviewed example kits, or request a kit for a job you need done.",
} as const;

export const AGENT_KIT_DEFINITION =
  "An agent kit is a set of nouns and verbs made for your agent: its instructions, skills, knowledge, " +
  "connections, settings, even its working files, plus the checks that prove it works.";

export const AGENT_KIT_DEFINITION_GENERAL =
  "An agent kit is a set of nouns and verbs made for one organization's agent: its instructions, skills, " +
  "knowledge, connections, settings, even its working files, plus the checks that prove it works.";

/** The nouns: the things an agent uses. */
export const KIT_NOUNS = [
  { name: "Instructions", detail: "What the agent does, step by step, and what it must refuse." },
  { name: "Skills", detail: "Focused abilities for one part of the job, such as drafting a referral note." },
  { name: "Knowledge", detail: "Checklists, procedures, templates and dated public sources." },
  { name: "Connections", detail: "Read-only links to services, such as a service directory or a budget sheet." },
  { name: "Settings", detail: "How the agent is set up, down to the program it runs in and the model it uses." },
  { name: "Working files", detail: "The files the agent keeps in its working folder." },
  { name: "Checks and tests", detail: "Synthetic test cases that prove the kit works before anyone reviews it." },
] as const;

/** The verbs: the work. */
export const KIT_VERBS = [
  {
    name: "A step map",
    detail: "Each step of the job, marked: the agent drafts it, the agent helps with it, or only a person does it.",
  },
  {
    name: "Building, testing and reviewing",
    detail: "Work on the kit itself, which volunteers' agents claim one task at a time.",
  },
] as const;

export const NOUNS_AND_VERBS_LINE =
  "Every piece is a noun: a reusable, versioned thing that anyone can pick up again. Building, testing " +
  "and reviewing a kit are verbs: work that volunteers' agents claim one task at a time.";

export const WHOLE_SETUP =
  "One noun can even hold an agent's whole setup: the program it runs in, the model and the files in " +
  "its working folder. A bundle of nouns and verbs like this is called a seed pack.";

export const KIT_STEPS = [
  {
    name: "Check",
    detail:
      "A volunteer's agent checks a request. Does it fit a track, follow the safety rules and use only " +
      "synthetic data? Only then does it become a task brief.",
  },
  {
    name: "Build",
    detail: "One volunteer's agent claims the task, builds the kit and runs its checks and tests.",
  },
  {
    name: "Review",
    detail:
      "A different volunteer's agent, or a person, reviews the sources, the tests and the person-only " +
      "steps. A builder never approves its own kit.",
  },
  {
    name: "Publish",
    detail:
      "Only a reviewed kit enters the catalog, and every version is kept. Sensitive kits also wait for a " +
      "nonprofit steward to sign off.",
  },
] as const;

export const PERSON_ONLY = [
  "Interviews and live conversations with the people a nonprofit serves.",
  "Crisis and safety planning.",
  "Decisions about a person, such as eligibility, a referral or a legal question.",
  "Anything sent or filed outside the organization.",
  "Sign-off on sensitive kits, by a nonprofit steward.",
] as const;

export const STATUS_AS_OF = "October 29, 2026";

export const STATUS_LINES = [
  "All data here is synthetic. Real client records never come to this site.",
  "Hosted volunteer runs, where volunteers' agents take real tasks through this site, are planned.",
  "A reviewed kit is not certified for any organization. Check it with your own staff and rules first.",
  "This site never calls an AI model. The thinking happens in volunteers' own agents.",
] as const;
