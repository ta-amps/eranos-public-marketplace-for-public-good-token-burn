import "./styles/tokens-v2.css";
import "./styles/fonts.css";
import "./styles/base.css";
import "./styles/app.css";
import "./styles/eranos.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { preloadNouns } from "./lib/useNoun";

const root = document.getElementById("root");
if (!root) throw new Error("index.html is missing #root");

/** The nouns each page needs before its first paint, so the page appears whole instead of flashing empty. */
function pageNouns(path: string, search: string): string[] {
  const extra = new URLSearchParams(search).get("tour") === "judge" ? ["trust"] : [];
  if (path === "/" || path === "") return [...extra, "home"];
  if (path.startsWith("/nonprofits")) return [...extra, "nonprofits-page", "library"];
  if (path.startsWith("/help")) return [...extra, "help-page", "help"];
  if (path.startsWith("/requests/")) {
    const example = /^\/requests\/(example(?:-process)?|REQ-INTAKE-07)(?:\/|$)/.exec(path)?.[1];
    return [
      ...extra,
      "request-status",
      ...(example ? [example === "example-process" ? "request-example-process" : "request-example"] : []),
    ];
  }
  if (path.startsWith("/library")) return [...extra, "library"];
  if (path === "/privacy" || path === "/terms" || path === "/report") return ["trust"];
  return extra;
}

// The static page shows the headline until the app can draw the whole page, or for at most 1.5 s.
const ready = preloadNouns([
  "site",
  "shell",
  ...pageNouns(window.location.pathname.replace(/\/+$/, ""), window.location.search),
]);
const timeout = new Promise<void>((resolve) => window.setTimeout(resolve, 1500));

void Promise.race([ready, timeout]).then(() => {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
