/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SNAPSHOT?: string;
  readonly VITE_FABRIC_DISPLAY_NAME?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare module "virtual:snapshot-data" {
  export const SNAPSHOT_DATA: Readonly<Record<string, unknown>>;
}
