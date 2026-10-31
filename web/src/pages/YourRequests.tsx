import { useEffect, useState } from "react";

import { SNAPSHOT } from "../config";
import { getJson } from "../lib/api";
import { fill, type RequestStatusNoun } from "../lib/nouns";
import { forgetKey, savedRequests, type SavedRequest } from "../lib/status/keys";
import { firstSentence } from "../lib/status/live";
import { shortRequestId } from "../lib/status/receipts";
import { useNoun } from "../lib/useNoun";
import { AppLink } from "../router";

/**
 * "Your requests": the requests whose private links this browser holds. The list is read from this browser's own
 * storage; each title comes from the request's public record, so nothing new is stored and no key leaves the page.
 */
export function YourRequests() {
  const words = useNoun<RequestStatusNoun>("request-status").value;
  const [items, setItems] = useState<SavedRequest[]>(() => savedRequests());
  const [titles, setTitles] = useState<Record<string, string>>({});

  useEffect(() => {
    if (SNAPSHOT) return;
    let live = true;
    for (const item of items) {
      getJson<{ value?: { text?: string } }>(`/api/nouns/eranos.requests/${encodeURIComponent(item.id)}`)
        .then((found) => {
          const text = found.value?.text;
          if (live && text) setTitles((current) => ({ ...current, [item.id]: firstSentence(text) }));
        })
        .catch(() => undefined);
    }
    return () => {
      live = false;
    };
  }, [items]);

  if (!words) return null;
  const y = words.yours;
  return (
    <section className="er-section er-yours" aria-labelledby="yours-title">
      <h1 id="yours-title">{y.title}</h1>
      <p className="er-lede">{y.lead}</p>
      {items.length === 0 ? (
        <div className="er-panel" data-testid="your-requests-empty">
          <p>{y.empty}</p>
          <AppLink to="/nonprofits" className="er-btn-primary">
            {y.ask}
          </AppLink>
        </div>
      ) : (
        <ul className="er-yours-list" data-testid="your-requests">
          {items.map((item) => (
            <li key={item.id}>
              <span>
                <AppLink to={`/requests/${encodeURIComponent(item.id)}`}>
                  <strong>{titles[item.id] ?? fill(y.untitled ?? "", { short: shortRequestId(item.id) })}</strong>
                </AppLink>
                {item.sentAt && (
                  <span className="er-small er-block">
                    {fill(y.sent ?? "", { date: new Date(item.sentAt).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) })}
                  </span>
                )}
              </span>
              <button
                type="button"
                className="er-btn-secondary er-btn-small"
                onClick={() => {
                  forgetKey(item.id);
                  setItems(savedRequests());
                }}
              >
                {y.forget}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
