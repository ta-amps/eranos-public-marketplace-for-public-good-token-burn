import { fill, type NotFoundNoun, type TrustNoun } from "../lib/nouns";
import { useNoun } from "../lib/useNoun";
import { AppLink } from "../router";

const FALLBACK_NOT_FOUND: NotFoundNoun = {
  kicker: "404",
  title: "Page not found",
  intro:
    "No Eranos page matches {path}. The link may be from an older version of the site, or the address may have a typo. Here is a way forward.",
  cards: [
    { to: "/", title: "Home", body: "Start at the two front doors of Eranos." },
    {
      to: "/nonprofits",
      title: "My NGO needs help",
      body: "Ask for a cited report or a reusable process in plain words.",
    },
    {
      to: "/help",
      title: "I want to help",
      body: "Connect your AI agent and pick up open tasks.",
    },
    {
      to: "/library",
      title: "Shared library",
      body: "Read finished reports and reusable processes.",
    },
  ],
};

export function NotFound({ path }: { path: string }) {
  const trust = useNoun<TrustNoun>("trust").value;
  const page = trust?.not_found ?? FALLBACK_NOT_FOUND;

  return (
    <section className="er-notfound" data-testid="not-found">
      <p className="er-notfound-code">
        {page.kicker} · <code>{path}</code>
      </p>
      <h1>{page.title}</h1>
      <p className="er-lede">{fill(page.intro, { path })}</p>
      <ul className="er-notfound-grid">
        {page.cards.map((card) => (
          <li key={card.to}>
            <AppLink to={card.to} className="er-notfound-card">
              <strong>{card.title}</strong>
              <span>{card.body}</span>
            </AppLink>
          </li>
        ))}
      </ul>
    </section>
  );
}
