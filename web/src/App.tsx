import { SyntheticBanner } from "./components/SyntheticBanner";
import { TopBar } from "./components/TopBar";
import { FABRIC_DISPLAY_NAME, SIBLING_DETECTION_NAME, SURFACE_DISPLAY_NAME } from "./config";
import { About } from "./pages/About";
import { Catalog } from "./pages/Catalog";
import { Contribute } from "./pages/Contribute";
import { Fabric } from "./pages/Fabric";
import { KitDetail } from "./pages/KitDetail";
import { NotFound } from "./pages/NotFound";
import { Overview } from "./pages/Overview";
import { Tracks } from "./pages/Tracks";
import { AppLink, matchPath, usePath, type RouteMatch } from "./router";

function Page({ route }: { route: RouteMatch }) {
  switch (route.name) {
    case "overview":
      return <Overview />;
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
    case "notFound":
      return <NotFound path={route.path} />;
  }
}

export function App() {
  const route = matchPath(usePath());
  return (
    <>
      <a className="er-skip-link" href="#main">
        Skip to content
      </a>
      <SyntheticBanner />
      <TopBar route={route} />
      <main id="main" className="er-main" tabIndex={-1}>
        <Page route={route} />
      </main>
      <footer className="er-footer">
        <div className="er-footer-inner">
          <p className="er-muted">
            <strong>{SURFACE_DISPLAY_NAME}</strong> -- Public-good NGO &amp; nonprofit foundry built on{" "}
            {FABRIC_DISPLAY_NAME} alongside {SIBLING_DETECTION_NAME}. Every example fixture is{" "}
            <code>SYNTHETIC</code>; interviews and decisions about people remain strictly{" "}
            <code>human_only</code>.
          </p>
          <nav className="er-footer-links" aria-label="Footer and agent discovery links">
            <AppLink to="/catalog">Verified Catalog</AppLink>
            <AppLink to="/contribute">Donate Tokens</AppLink>
            <AppLink to="/tracks">Tracks</AppLink>
            <AppLink to="/about">Safety Boundaries</AppLink>
            <a href="/llms.txt">llms.txt</a>
            <a href="/.well-known/agent-card.json">Agent Card</a>
            <a href="/healthz">Health</a>
          </nav>
        </div>
      </footer>
    </>
  );
}
