import { FABRIC_DISPLAY_NAME } from "../config";
import { AppLink, type RouteMatch } from "../router";

const NAV_ITEMS = [
  { to: "/", label: "Overview", match: "overview" },
  { to: "/catalog", label: "Catalog", match: "catalog" },
  { to: "/contribute", label: "Connect an Agent", match: "contribute" },
  { to: "/tracks", label: "Tracks", match: "tracks" },
  { to: "/fabric", label: FABRIC_DISPLAY_NAME, match: "fabric" },
  { to: "/about", label: "About", match: "about" },
] as const;

export function TopBar({ route }: { route: RouteMatch }) {
  const active = route.name === "kit" ? "catalog" : route.name;
  return (
    <header className="er-topbar">
      <div className="er-topbar-inner">
        <AppLink to="/" className="er-brand">
          <span>Eranos</span>
          <span className="er-brand-sub">Volunteer agent tools for NGOs &amp; nonprofits</span>
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
