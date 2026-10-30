import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, searchForWorkspaceRoot, type Plugin } from "vite";

/**
 * The Worker's onboarding module, vendored unchanged from Tessera. It also builds the `/agent-start.json`
 * noun, so importing it keeps the brief that the /help page copies identical to what the Worker serves.
 */
const AGENT_START_MODULE = fileURLToPath(new URL("../deploy/cloudflare/agent_start.js", import.meta.url));

/** `virtual:agent-start` resolves to the onboarding module above. */
function agentStart(): Plugin {
  return {
    name: "eranos-agent-start",
    resolveId(id) {
      return id === "virtual:agent-start" ? AGENT_START_MODULE : null;
    },
  };
}

/**
 * `virtual:snapshot-data` resolves to the bundled snapshot (VITE_SNAPSHOT=1) or to an empty map.
 * Bundling the snapshot means the offline demo makes no network request at all.
 */
function snapshotData(offline: boolean): Plugin {
  const file = offline ? "./src/lib/snapshot-data.offline.ts" : "./src/lib/snapshot-data.live.ts";
  const target = fileURLToPath(new URL(file, import.meta.url));
  return {
    name: "eranos-snapshot-data",
    resolveId(id) {
      return id === "virtual:snapshot-data" ? target : null;
    },
  };
}

/**
 * Normalizes any third-party em-dash characters in emitted bundle chunks and sourcemaps to `--`.
 */
function stripEmDashes(): Plugin {
  const literalDash = String.fromCharCode(0x2014);
  const escapedDash = "\\" + "u2014";
  const scrub = (value: string): string =>
    value.split(literalDash).join("--").split(escapedDash).join("--");

  return {
    name: "eranos-strip-em-dashes",
    generateBundle(_options, bundle) {
      for (const item of Object.values(bundle)) {
        if (item.type === "chunk") {
          item.code = scrub(item.code);
          if (item.map && Array.isArray(item.map.sourcesContent)) {
            item.map.sourcesContent = item.map.sourcesContent.map((src) =>
              typeof src === "string" ? scrub(src) : src,
            );
          }
        } else if (item.type === "asset" && typeof item.source === "string") {
          item.source = scrub(item.source);
        }
      }
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const offline = (process.env.VITE_SNAPSHOT ?? env.VITE_SNAPSHOT) === "1";
  const apiOrigin = process.env.VITE_API_ORIGIN ?? env.VITE_API_ORIGIN ?? "http://127.0.0.1:7720";
  return {
    plugins: [react(), snapshotData(offline), agentStart(), stripEmDashes()],
    server: {
      port: 5174,
      proxy: { "/api": apiOrigin },
      fs: { allow: [searchForWorkspaceRoot(process.cwd()), AGENT_START_MODULE] },
    },
    preview: { port: 4174 },
    build: { outDir: "dist", sourcemap: true },
  };
});
