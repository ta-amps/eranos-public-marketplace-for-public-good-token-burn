import { SyntheticBanner } from "./components/SyntheticBanner";
import { TopBar } from "./components/TopBar";
import { About } from "./pages/About";
import { Catalog } from "./pages/Catalog";
import { Contribute } from "./pages/Contribute";
import { Fabric } from "./pages/Fabric";
import { KitDetail } from "./pages/KitDetail";
import { NotFound } from "./pages/NotFound";
import { Overview } from "./pages/Overview";
import { Tracks } from "./pages/Tracks";
import { matchPath, usePath, type RouteMatch } from "./router";

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
    </>
  );
}
