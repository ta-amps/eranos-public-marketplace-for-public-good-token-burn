import type { JudgeTourNoun, TrustNoun } from "../lib/nouns";
import { useNoun } from "../lib/useNoun";
import { AppLink, useHash, useSearch, type RouteMatch } from "../router";

const FALLBACK_TOUR: JudgeTourNoun = {
  label: "45-second tour",
  close: "Close",
  close_label: "Close the tour",
  steps: [
    {
      step: 1,
      label: "Agora",
      href: "https://agora.eranosforgood.org/?tour=judge",
      next_label: "Try the nonprofit journey →",
      next_to: "/nonprofits?tour=judge",
    },
    {
      step: 2,
      label: "Ask",
      to: "/nonprofits?tour=judge",
      next_label: "Watch a finished request →",
      next_to: "/requests/REQ-INTAKE-07?tour=judge",
    },
    {
      step: 3,
      label: "Watch a request",
      to: "/requests/REQ-INTAKE-07?tour=judge",
      next_label: "Open the result →",
      next_to: "/requests/REQ-INTAKE-07?tour=judge#step-ready",
    },
    {
      step: 4,
      label: "The result",
      to: "/requests/REQ-INTAKE-07?tour=judge#step-ready",
      next_label: "Test the queue live →",
      next_href: "https://agora.eranosforgood.org/studio/?tour=judge",
    },
    {
      step: 5,
      label: "Live queue",
      href: "https://agora.eranosforgood.org/studio/?tour=judge",
      next_label: "Back to Agora →",
      next_href: "https://agora.eranosforgood.org/?tour=judge",
    },
  ],
};

function activeStepFor(route: RouteMatch, hash: string): number {
  if (route.name === "report" || (route.name === "request" && hash === "#step-ready")) {
    return 4;
  }
  if (route.name === "request") {
    return 3;
  }
  return 2;
}

function JudgeTourStrip({ route, hash }: { route: RouteMatch; hash: string }) {
  const trust = useNoun<TrustNoun>("trust").value;
  const tour = trust?.tour ?? FALLBACK_TOUR;
  const activeStep = activeStepFor(route, hash);
  const current = tour.steps.find((item) => item.step === activeStep) ?? tour.steps[1];

  function closeTour() {
    const url = new URL(window.location.href);
    url.searchParams.delete("tour");
    const nextUrl = `${url.pathname}${url.search}${url.hash}`;
    window.history.replaceState(window.history.state, "", nextUrl);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }

  return (
    <nav className="er-judge-tour" aria-label={tour.label} data-testid="judge-tour">
      <div className="er-judge-tour-inner">
        <strong className="er-judge-tour-title">{tour.label}</strong>
        <ol className="er-judge-tour-steps">
          {tour.steps.map((item) => {
            const isCurrent = item.step === activeStep;
            const isDone = item.step < activeStep;
            const stateClass = isCurrent
              ? "er-judge-tour-pill er-judge-tour-pill-current"
              : isDone
                ? "er-judge-tour-pill er-judge-tour-pill-done"
                : "er-judge-tour-pill";
            const badge = (
              <span className="er-judge-tour-dot" aria-hidden="true">
                {isDone ? "✓" : item.step}
              </span>
            );
            return (
              <li key={item.step} className="er-judge-tour-item">
                {item.to ? (
                  <AppLink
                    to={item.to}
                    className={stateClass}
                    aria-current={isCurrent ? "step" : undefined}
                  >
                    {badge}
                    <span>{item.label}</span>
                  </AppLink>
                ) : (
                  <a
                    href={item.href}
                    className={stateClass}
                    aria-current={isCurrent ? "step" : undefined}
                  >
                    {badge}
                    <span>{item.label}</span>
                  </a>
                )}
              </li>
            );
          })}
        </ol>
        <div className="er-judge-tour-actions">
          {current &&
            (current.next_to ? (
              <AppLink to={current.next_to} className="er-judge-tour-next">
                {current.next_label}
              </AppLink>
            ) : (
              <a href={current.next_href} className="er-judge-tour-next">
                {current.next_label}
              </a>
            ))}
          <button
            type="button"
            className="er-judge-tour-close"
            aria-label={tour.close_label}
            onClick={closeTour}
          >
            {tour.close} <span aria-hidden="true">×</span>
          </button>
        </div>
      </div>
    </nav>
  );
}

/** Opt-in 5-step tour strip rendered below the header only when `?tour=judge` is present. */
export function JudgeTour({ route }: { route: RouteMatch }) {
  const search = useSearch();
  const hash = useHash();
  if (new URLSearchParams(search).get("tour") !== "judge") return null;
  return <JudgeTourStrip route={route} hash={hash} />;
}
