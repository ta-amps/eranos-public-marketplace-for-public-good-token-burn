import { useEffect, useState } from "react";

import { SNAPSHOT } from "../config";
import { getJson } from "../lib/api";
import { fill, type RequestStatusNoun } from "../lib/nouns";
import { forgetKey, savedRequests, type SavedRequest } from "../lib/status/keys";
import { firstSentence } from "../lib/status/live";
import { shortRequestId } from "../lib/status/ids";
import { isListed } from "../lib/status/unlisted";
import { useNoun } from "../lib/useNoun";
import { AppLink } from "../router";

interface PublicRequest {
  id: string;
  title: string;
  sentAt: number | null;
}

function sentAt(id: string): number | null {
  const sent = parseInt(id.slice(id.lastIndexOf("-") + 1), 36);
  return Number.isFinite(sent) && sent > 1.6e12 && sent < 4.1e12 ? sent : null;
}

function when(at: number): string {
  return new Date(at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/**
 * "Requests" (SiteHeader, 20:15): recent public requests, read from their public records. Below them, the private
 * links this browser holds, if any: ids only, never the keys.
 */
export function YourRequests() {
  const words = useNoun<RequestStatusNoun>("request-status").value;
  const [saved, setSaved] = useState<SavedRequest[]>(() => savedRequests());
  const [recent, setRecent] = useState<PublicRequest[] | null>(null);

  useEffect(() => {
    if (SNAPSHOT) {
      setRecent([]);
      return;
    }
    let live = true;
    getJson<{ records?: { key: string; value?: { text?: string } }[] }>("/api/nouns/eranos.requests")
      .then((list) => {
        if (!live) return;
        setRecent(
          (list.records ?? [])
            .filter((record) => /^rq-r_[0-9a-f]{32}-[0-9a-z]+$/.test(record.key) || /^req-[0-9a-f]{12}$/.test(record.key))
            .filter((record) => isListed(record.key))
            .map((record) => ({ id: record.key, title: firstSentence(record.value?.text ?? ""), sentAt: sentAt(record.key) }))
            .sort((a, b) => (b.sentAt ?? 0) - (a.sentAt ?? 0))
            .slice(0, 20),
        );
      })
      .catch(() => live && setRecent([]));
    return () => {
      live = false;
    };
  }, []);

  if (!words) return null;
  const y = words.yours;
  return (
    <section className="er-section er-yours" aria-labelledby="yours-title">
      <h1 id="yours-title">{y.title}</h1>
      <p className="er-lede">{y.lead}</p>

      <h2>{y.public_title}</h2>
      {recent === null ? (
        <p className="er-small">{y.loading}</p>
      ) : recent.length === 0 ? (
        <div className="er-panel" data-testid="public-requests-empty">
          <p>{y.public_none}</p>
          <AppLink to="/nonprofits" className="er-btn-primary">
            {y.ask}
          </AppLink>
        </div>
      ) : (
        <ul className="er-yours-list" data-testid="public-requests">
          {recent.map((item) => (
            <li key={item.id}>
              <span>
                <AppLink to={`/requests/${encodeURIComponent(item.id)}`}>
                  <strong>{item.title || fill(y.untitled ?? "", { short: shortRequestId(item.id) })}</strong>
                </AppLink>
                {item.sentAt && <span className="er-small er-block">{fill(y.sent ?? "", { date: when(item.sentAt) })}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}

      {saved.length > 0 && (
        <>
          <h2>{y.saved_title}</h2>
          <p className="er-small">{y.saved_note}</p>
          <ul className="er-yours-list" data-testid="your-requests">
            {saved.map((item) => (
              <li key={item.id}>
                <span>
                  <AppLink to={`/requests/${encodeURIComponent(item.id)}`}>
                    <strong>{fill(y.untitled ?? "", { short: shortRequestId(item.id) })}</strong>
                  </AppLink>
                  {item.sentAt && <span className="er-small er-block">{fill(y.sent ?? "", { date: when(item.sentAt) })}</span>}
                </span>
                <button
                  type="button"
                  className="er-btn-secondary er-btn-small"
                  onClick={() => {
                    forgetKey(item.id);
                    setSaved(savedRequests());
                  }}
                >
                  {y.forget}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
