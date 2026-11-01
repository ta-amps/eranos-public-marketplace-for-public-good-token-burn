import type { TrustNoun } from "../lib/nouns";
import { useNoun } from "../lib/useNoun";
import { AppLink } from "../router";

export type TrustPageKind = "privacy" | "terms" | "report";

const TRUST_LINKS: { kind: TrustPageKind; to: string; label: string }[] = [
  { kind: "privacy", to: "/privacy", label: "Privacy" },
  { kind: "terms", to: "/terms", label: "Terms of use" },
  { kind: "report", to: "/report", label: "Report a problem" },
];

export function TrustPage({ kind }: { kind: TrustPageKind }) {
  const trust = useNoun<TrustNoun>("trust").value;
  const page = trust?.[kind];
  if (!page) return null;

  return (
    <article className="er-trust" data-testid={`trust-${kind}`}>
      <header className="er-trust-header">
        <p className="er-trust-kicker">{page.kicker}</p>
        <h1>{page.title}</h1>
        <p className="er-lede">{page.intro}</p>
      </header>

      {page.actions && page.actions.length > 0 && (
        <div className="er-trust-actions">
          {page.actions.map((action) => (
            <a
              key={action.href}
              href={action.href}
              className={action.primary ? "er-btn-primary" : "er-btn-secondary"}
            >
              {action.label}
            </a>
          ))}
        </div>
      )}

      {page.sections.map((section) => (
        <section key={section.heading} className="er-trust-block">
          <h2>{section.heading}</h2>
          <ul>
            {section.items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      ))}

      <footer className="er-trust-foot">
        <p>{page.footer}</p>
        <nav className="er-trust-nav" aria-label="Trust and safety pages">
          {TRUST_LINKS.map((item) => (
            <AppLink
              key={item.to}
              to={item.to}
              aria-current={item.kind === kind ? "page" : undefined}
            >
              {item.label}
            </AppLink>
          ))}
        </nav>
      </footer>
    </article>
  );
}
