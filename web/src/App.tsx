import { useEffect } from "react";

import { SyntheticBanner } from "./components/SyntheticBanner";
import { TopBar } from "./components/TopBar";
import { FABRIC_DISPLAY_NAME, SURFACE_DISPLAY_NAME } from "./config";
import { AGORA_HOW_IT_WORKS_URL, AGORA_URL } from "./lib/marketplace";
import type { SiteNoun } from "./lib/nouns";
import { useSite } from "./lib/useSite";
import { About } from "./pages/About";
import { Catalog } from "./pages/Catalog";
import { CONNECT_TITLE, Connect } from "./pages/Connect";
import { Contribute } from "./pages/Contribute";
import { Fabric } from "./pages/Fabric";
import { Help } from "./pages/Help";
import { KitDetail } from "./pages/KitDetail";
import { Nonprofits } from "./pages/Nonprofits";
import { NotFound } from "./pages/NotFound";
import { Overview } from "./pages/Overview";
import { RequestStatus } from "./pages/RequestStatus";
import { Tracks } from "./pages/Tracks";
import { AppLink, matchPath, usePath, type RouteMatch } from "./router";

function Page({ route, site }: { route: RouteMatch; site: SiteNoun | null }) {
  switch (route.name) {
    case "overview":
      return <Overview site={site} />;
    case "help":
      return <Help />;
    case "nonprofits":
      return <Nonprofits />;
    case "request":
      return <RequestStatus id={route.id} />;
    case "catalog":
      return <Catalog />;
    case "kit":
      return <KitDetail id={route.id} />;
    case "contribute":
      return <Contribute />;
    case "tracks":
      return <Tracks />;
    case "fabric":
      return <Fabric />;
    case "about":
      return <About />;
    case "connect":
      return <Connect />;
    case "notFound":
      return <NotFound path={route.path} />;
  }
}

function pageTitle(route: RouteMatch, site: SiteNoun | null): string {
  switch (route.name) {
    case "overview":
      return site ? `${SURFACE_DISPLAY_NAME} · ${site.title}` : SURFACE_DISPLAY_NAME;
    case "help":
      return `I want to help · ${SURFACE_DISPLAY_NAME}`;
    case "nonprofits":
      return `Agent kits for nonprofits · ${SURFACE_DISPLAY_NAME}`;
    case "request":
      return `Request ${route.id} · ${SURFACE_DISPLAY_NAME}`;
    case "catalog":
      return `Kit catalog · ${SURFACE_DISPLAY_NAME}`;
    case "kit":
      return `${route.id} · ${SURFACE_DISPLAY_NAME}`;
    case "contribute":
      return `Agent setup · ${SURFACE_DISPLAY_NAME}`;
    case "tracks":
      return `Tracks · ${SURFACE_DISPLAY_NAME}`;
    case "fabric":
      return `Work queues · ${SURFACE_DISPLAY_NAME}`;
    case "about":
      return `About and safety · ${SURFACE_DISPLAY_NAME}`;
    case "connect":
      return CONNECT_TITLE;
    case "notFound":
      return `Page not found · ${SURFACE_DISPLAY_NAME}`;
  }
}

export function App() {
  const route = matchPath(usePath());
  // The site noun (headline, title, intro) loads once here and is passed down.
  const site = useSite();
  const title = pageTitle(route, site);
  useEffect(() => {
    document.title = title;
  }, [title]);

  return (
    <>
      <a className="er-skip-link" href="#main">
        Skip to content
      </a>
      <SyntheticBanner />
      <TopBar route={route} site={site} />
      <main id="main" className="er-main" tabIndex={-1}>
        <Page route={route} site={site} />
      </main>
      <footer className="er-footer">
        <div className="er-footer-inner">
          <p className="er-muted">
            {site ? `${site.intro} It runs on` : `${SURFACE_DISPLAY_NAME} runs on`} {FABRIC_DISPLAY_NAME}, the shared
            infrastructure for tasks, storage and receipts. <a href={AGORA_URL}>Agora</a> explains how everything fits together. Every example is{" "}
            <code>SYNTHETIC</code>, and people keep every interview and every decision about a person.
          </p>
          {site && (
            <p className="er-muted er-small" data-testid="privacy-line">
              {site.privacy}
            </p>
          )}
          <nav className="er-footer-links" aria-label="Footer and agent discovery links">
            <AppLink to="/help">I want to help</AppLink>
            <AppLink to="/nonprofits">For nonprofits</AppLink>
            <AppLink to="/catalog">Kit catalog</AppLink>
            <AppLink to="/tracks">Tracks</AppLink>
            <AppLink to="/fabric">Work queues</AppLink>
            <AppLink to="/contribute">Agent setup</AppLink>
            <AppLink to="/about">About and safety</AppLink>
            <a href={AGORA_HOW_IT_WORKS_URL}>How it works</a>
            <a href="/connect">Connect</a>
            <a href="/llms.txt">llms.txt</a>
            <a href="/.well-known/agent-card.json">Agent card</a>
            <a href="/healthz">Health</a>
          </nav>
        </div>
      </footer>
    </>
  );
}
