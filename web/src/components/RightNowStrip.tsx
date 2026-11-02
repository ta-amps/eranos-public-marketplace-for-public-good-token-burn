import { SNAPSHOT } from "../config";
import { fill, type RightNowWords } from "../lib/nouns";
import type { NetworkStripResponse } from "../lib/types";
import { useResource } from "../lib/useResource";
import { AppLink } from "../router";
import { Icon } from "./Icon";

/** At most once a minute (network map contract: totals update at most once a minute). */
const NETWORK_POLL_MS = 60_000;

function ago(at: string | null): string {
  const when = at ? Date.parse(at) : Number.NaN;
  if (!Number.isFinite(when)) return "";
  const minutes = Math.round((Date.now() - when) / 60_000);
  const format = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  if (Math.abs(minutes) < 60) return format.format(-Math.max(0, minutes), "minute");
  return format.format(-Math.round(minutes / 60), "hour");
}

function recent(data: NetworkStripResponse): boolean {
  const at = data.last?.at ? Date.parse(data.last.at) : Number.NaN;
  return Number.isFinite(at) && Date.now() - at <= (data.recent_minutes ?? 10) * 60_000;
}

/**
 * "Right now" under the two doors (LiveMapStrip, site eranos): live counts from Herma's network summary, read through
 * `/api/network`. Live: workers, continents and the last claim with the model that ran (a volunteer's AI shows the
 * model it declared). Quiet or empty: the contract's own lines. Without a summary the strip says it is off; it never
 * shows a number the summary did not give. Places are Cloudflare data centers or continents, never anyone's home.
 */
export function RightNowStrip({ words }: { words: RightNowWords }) {
  const network = useResource<NetworkStripResponse>("/api/network", { pollMs: NETWORK_POLL_MS });
  if (SNAPSHOT || network.state.status === "loading") return null;
  const data = network.state.status === "ready" ? network.state.data : null;
  const totals = data?.available ? data.totals : undefined;
  const workers = totals?.workers ?? null;
  const live = Boolean(data && totals && workers && workers > 0 && recent(data));
  const cta = (
    <a className="er-now-strip-cta" href={words.cta_href}>
      {words.cta}
    </a>
  );

  if (!data || !totals || workers === null) {
    return (
      <section className="er-now-strip er-now-strip-quiet" aria-label={words.label} data-testid="right-now-strip" data-state="off">
        <p className="er-now-strip-eyebrow">{words.eyebrow}</p>
        <div className="er-now-strip-quiet-body" role="status">
          <Icon name="clock" size={22} />
          <p>
            <strong>{words.off_title}</strong> {words.off_text}
          </p>
        </div>
      </section>
    );
  }
  if (workers === 0) {
    return (
      <section className="er-now-strip er-now-strip-quiet" aria-label={words.label} data-testid="right-now-strip" data-state="empty">
        <p className="er-now-strip-eyebrow">{words.eyebrow}</p>
        <div className="er-now-strip-quiet-body" role="status">
          <Icon name="clock" size={22} />
          <p>
            <strong>{words.empty_title}</strong> {words.empty_text} <AppLink to={words.empty_to}>{words.empty_cta}</AppLink>
          </p>
        </div>
      </section>
    );
  }
  const last = data.last;
  const model = last?.model ? (last.model.declared ? fill(words.declared, { model: last.model.name }) : last.model.name) : words.not_declared;
  const lastLine =
    live && last?.kind_label
      ? last.via.type === "data_centre" && last.via.city
        ? fill(words.last, { kind: last.kind_label, model, city: last.via.city, ago: ago(last.at) })
        : last.via.continent
          ? fill(words.last_continent, { kind: last.kind_label, model, continent: last.via.continent, ago: ago(last.at) })
          : words.last_unplaced
            ? fill(words.last_unplaced, { kind: last.kind_label, model, ago: ago(last.at) })
            : null
      : null;
  const headline =
    totals.continents && totals.continents > 0
      ? fill(words.headline, { workers, continents: totals.continents })
      : fill(words.headline_short, { workers });
  return (
    <section className="er-now-strip" aria-label={words.label} data-testid="right-now-strip" data-state={live ? "live" : "quiet"}>
      <p className="er-now-strip-eyebrow">{words.eyebrow}</p>
      <p className="er-now-strip-headline" role="status">
        {headline}
      </p>
      {totals.nonprofit_claims !== null && <p className="er-now-strip-sub">{fill(words.sub, { nonprofit_claims: totals.nonprofit_claims })}</p>}
      {live && lastLine ? (
        <p className="er-now-strip-last">{lastLine}</p>
      ) : (
        <p className="er-now-strip-last">
          <strong>{words.quiet_title}</strong> {words.quiet_text}
        </p>
      )}
      {cta}
    </section>
  );
}
