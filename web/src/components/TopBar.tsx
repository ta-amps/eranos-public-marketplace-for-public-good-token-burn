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
          <svg
            className="er-brand-logo"
            width="28"
            height="28"
            viewBox="0 0 64 64"
            aria-hidden="true"
            focusable="false"
          >
            <rect width="64" height="64" rx="14" fill="#155e49" />
            <circle
              cx="32"
              cy="32"
              r="21"
              fill="none"
              stroke="#e3f2ed"
              strokeWidth="2.5"
              strokeDasharray="6 4"
            />
            <path
              d="M20 38c0-9 5.5-16 12-18 6.5 2 12 9 12 18"
              fill="none"
              stroke="#6ee0be"
              strokeWidth="3"
              strokeLinecap="round"
            />
            <polygon points="32,23 39,32 32,41 25,32" fill="#ffffff" />
          </svg>
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
