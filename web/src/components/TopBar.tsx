import { FABRIC_DISPLAY_NAME, SURFACE_DISPLAY_NAME } from "../config";
import { AppLink, type RouteMatch } from "../router";

const NAV_ITEMS = [
  { to: "/", label: "Overview", match: "overview" },
  { to: "/catalog", label: "Off-the-Shelf Catalog", match: "catalog" },
  { to: "/contribute", label: "Donate Tokens", match: "contribute" },
  { to: "/tracks", label: "Public-Good Tracks", match: "tracks" },
  { to: "/fabric", label: FABRIC_DISPLAY_NAME, match: "fabric" },
  { to: "/about", label: "About", match: "about" },
] as const;

export function TopBar({ route }: { route: RouteMatch }) {
  const active = route.name === "kit" ? "catalog" : route.name;
  return (
    <header className="er-topbar">
      <div className="er-topbar-inner">
        <AppLink to="/" className="er-brand">
          <span>{SURFACE_DISPLAY_NAME}</span>
          <span className="er-brand-sub">Donate unused tokens · Off-the-shelf AI tools for NGOs</span>
        </AppLink>
        <nav className="er-nav" aria-label="Primary navigation">
          {NAV_ITEMS.map((item) => (
            <AppLink
              key={item.to}
              to={item.to}
              aria-current={active === item.match ? "page" : undefined}
            >
              {item.label}
            </AppLink>
          ))}
        </nav>
      </div>
    </header>
  );
}
