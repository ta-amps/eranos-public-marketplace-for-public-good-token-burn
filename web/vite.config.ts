import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type Plugin } from "vite";

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
    plugins: [react(), snapshotData(offline), stripEmDashes()],
    server: { port: 5174, proxy: { "/api": apiOrigin } },
    preview: { port: 4174 },
    build: { outDir: "dist", sourcemap: true },
  };
});
