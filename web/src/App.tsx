import { lazy, Suspense, useEffect } from "react";

import { Footer } from "./components/Footer";
import { TopBar } from "./components/TopBar";
import { SURFACE_DISPLAY_NAME } from "./config";
import type { ShellNoun, SiteNoun } from "./lib/nouns";
import { useNoun } from "./lib/useNoun";
import { CONNECT_TITLE, Connect } from "./pages/Connect";
import { Help } from "./pages/Help";
import { Nonprofits } from "./pages/Nonprofits";
import { NotFound } from "./pages/NotFound";
import { Overview } from "./pages/Overview";
import { RequestStatus } from "./pages/RequestStatus";
import { matchPath, usePath, type RouteMatch } from "./router";

// The pages a first visit does not need load on demand, so the home page's first paint carries only its own code.
const About = lazy(() => import("./pages/About").then((page) => ({ default: page.About })));
const Catalog = lazy(() => import("./pages/Catalog").then((page) => ({ default: page.Catalog })));
const Contribute = lazy(() => import("./pages/Contribute").then((page) => ({ default: page.Contribute })));
const Fabric = lazy(() => import("./pages/Fabric").then((page) => ({ default: page.Fabric })));
const KitDetail = lazy(() => import("./pages/KitDetail").then((page) => ({ default: page.KitDetail })));
const YourRequests = lazy(() => import("./pages/YourRequests").then((page) => ({ default: page.YourRequests })));
const Library = lazy(() => import("./pages/Library").then((page) => ({ default: page.Library })));
const RequestResult = lazy(() => import("./pages/RequestResult").then((page) => ({ default: page.RequestResult })));
const Tracks = lazy(() => import("./pages/Tracks").then((page) => ({ default: page.Tracks })));

function Page({ route, site }: { route: RouteMatch; site: SiteNoun | null }) {
  switch (route.name) {
    case "overview":
      return <Overview site={site} />;
    case "help":
      return <Help />;
    case "nonprofits":
      return <Nonprofits />;
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
    case "library":
      return <Library />;
    case "yours":
      return <YourRequests />;
    case "request":
      return <RequestStatus id={route.id} />;
    case "report":
      return <RequestResult id={route.id} />;
    case "notFound":
      return <NotFound path={route.path} />;
  }
}

/** The tab title; request pages set their own, since it changes to "Your turn · R-…" when a decision waits. */
function pageTitle(route: RouteMatch, site: SiteNoun | null): string | null {
  switch (route.name) {
    case "overview":
      return site ? `${SURFACE_DISPLAY_NAME} · ${site.title}` : SURFACE_DISPLAY_NAME;
    case "help":
      return `I want to help · ${SURFACE_DISPLAY_NAME}`;
    case "nonprofits":
      return `Tell us what you need · ${SURFACE_DISPLAY_NAME}`;
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
    case "library":
      return `Shared library · ${SURFACE_DISPLAY_NAME}`;
    case "yours":
      return `Your requests · ${SURFACE_DISPLAY_NAME}`;
    case "request":
    case "report":
      return null;
    case "notFound":
      return `Page not found · ${SURFACE_DISPLAY_NAME}`;
  }
}

export function App() {
  const route = matchPath(usePath());
  const site = useNoun<SiteNoun>("site").value;
  const shell = useNoun<ShellNoun>("shell").value;
  const title = pageTitle(route, site);
  useEffect(() => {
    if (title) document.title = title;
  }, [title]);
  const compact = route.name === "request" || route.name === "report";
  const mainClass = route.name === "overview" ? "er-main er-main-home" : compact ? "er-main er-main-wide" : "er-main";

  return (
    <>
      <TopBar route={route} shell={shell} compact={compact} />
      <main id="main" className={mainClass} tabIndex={-1}>
        <Suspense fallback={null}>
          <Page route={route} site={site} />
        </Suspense>
      </main>
      <Footer shell={shell} site={site} />
    </>
  );
}
