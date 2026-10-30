/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SNAPSHOT?: string;
  readonly VITE_SURFACE_NAME?: string;
  readonly VITE_SURFACE_URL?: string;
  readonly VITE_FABRIC_DISPLAY_NAME?: string;
  readonly VITE_TESSERA_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare module "virtual:snapshot-data" {
  export const SNAPSHOT_DATA: Readonly<Record<string, unknown>>;
}

/** The Worker's vendored onboarding module, `deploy/cloudflare/agent_start.js` (see vite.config.ts). */
declare module "virtual:agent-start" {
  export const ONBOARDING_VERSION: string;
  export function buildAgentPrompt(origin: string, mode: "any" | "interests", interests?: string): string;
}
