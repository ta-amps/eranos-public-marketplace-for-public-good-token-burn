import { useEffect, useMemo, useState } from "react";

import { getJson } from "../lib/api";
import { loadLibrary, searchLibrary, type LibraryItem } from "../lib/library";
import { fill, type NounResponse } from "../lib/nouns";
import type { RequestExampleNoun } from "../lib/status/example";
import { firstSentence } from "../lib/status/live";
import { shortRequestId } from "../lib/status/ids";
import type { PartPlan } from "../lib/status/types";
import { useNoun } from "../lib/useNoun";
import { AppLink, useSearch } from "../router";
import { EXAMPLES } from "./RequestStatus";

type Choice = { id: string; label: string };

interface LibraryNoun {
  heading: string;
  lead: string;
  search_label: string;
  search_placeholder: string;
  search_button: string;
  tries_label: string;
  tries: string[];
  filters_label: string;
  filters: { id: "type" | "runs"; label: string; options: Choice[] }[];
  results_label: string;
  tag_process: string;
  tag_answer: string;
  example: string;
  meta_for: string;
  meta_checked: string;
  open: string;
  adapt: string;
  count_all_one: string;
  count_all_many: string;
  count_one: string;
  count_many: string;
  count_none: string;
  count_filtered_none: string;
  loading: string;
  unavailable: string;
  empty_title: string;
  empty_title_filters: string;
  empty_body: string;
  empty_ask: string;
  footnote: string;
  catalog_link: string;
  stored_title: string;
  show_stored: string;
  hide_stored: string;
  stored_lead: string;
  stored_objects: string;
  stored_tasks: string;
  stored_rows: Record<string, string>;
  stored_empty: string;
  back: string;
}

interface StoredRow {
  kind: "object" | "task";
  label: string;
  id: string;
}

/** The tasks and task objects that hold one request, by their real ids: from its plan, or the example's. */
function useStored(requestId: string | null, words: LibraryNoun | null): StoredRow[] | null {
  const exampleKey = requestId ? EXAMPLES[requestId] : undefined;
  const example = useNoun<RequestExampleNoun>(exampleKey ?? "request-example").value;
  const [parts, setParts] = useState<PartPlan[] | null>(null);
  const [id, setId] = useState<string | null>(null);
  useEffect(() => {
    if (!requestId) return;
    if (exampleKey) {
      if (!example) return;
      setId(example.request.id);
      setParts(example.events.find((e) => e.type === "planned")?.parts ?? []);
      return;
    }
    setId(requestId);
    getJson<NounResponse<{ parts?: PartPlan[] }>>(`/api/nouns/eranos.plans/${encodeURIComponent(requestId)}`)
      .then((plan) => setParts(plan.value.parts ?? []))
      .catch(() => setParts([]));
  }, [requestId, exampleKey, example]);
  if (!requestId || !words || !id || parts === null) return null;
  const rows: StoredRow[] = [
    { kind: "task", label: words.stored_rows.request_verb ?? "", id: `eq01 · ${id}` },
    { kind: "object", label: words.stored_rows.own_noun ?? "", id: `org.requests/${id}` },
    { kind: "object", label: words.stored_rows.public_request ?? "", id: `eranos.requests/${id}` },
    { kind: "object", label: words.stored_rows.plan ?? "", id: `eranos.plans/${id}` },
  ];
  for (const part of parts) {
    if (part.work_task_id) rows.push({ kind: "task", label: fill(words.stored_rows.work ?? "", { n: part.part }), id: `eq02 · ${part.work_task_id}` });
    if (part.review_task_id) rows.push({ kind: "task", label: fill(words.stored_rows.review ?? "", { n: part.part }), id: `eq03 · ${part.review_task_id}` });
    if (part.report_id) rows.push({ kind: "object", label: fill(words.stored_rows.report ?? "", { n: part.part }), id: `eranos.solutions/${part.report_id}` });
    if (part.kit_id) rows.push({ kind: "object", label: fill(words.stored_rows.kit ?? "", { n: part.part }), id: `eranos.catalog/${part.kit_id}` });
  }
  rows.push({ kind: "object", label: words.stored_rows.decisions ?? "", id: `org.decisions/${id}` });
  return rows;
}

/** A process package (a reviewed kit) runs on your own computer; a delivered report is a public answer. */
function kindOf(item: LibraryItem): "process" | "answer" {
  return item.kind === "kit" ? "process" : "answer";
}

/** One result card (SearchSolutions): the kind, the title, one plain sentence, who it was for, and two ways on. */
function SolutionCard({ item, words }: { item: LibraryItem; words: LibraryNoun }) {
  const kind = kindOf(item);
  const meta = [item.forWho ? fill(words.meta_for, { who: item.forWho }) : "", item.checked ? words.meta_checked : ""].filter(Boolean).join(" · ");
  const adapt = `/nonprofits?improve=${encodeURIComponent(`${window.location.origin}${item.href}`)}`;
  return (
    <li className="er-solution" data-kind={kind}>
      <p className="er-solution-tags">
        <span className={kind === "process" ? "er-kind-tag er-kind-tag-task" : "er-kind-tag er-kind-tag-object"}>
          {kind === "process" ? words.tag_process : words.tag_answer}
        </span>
        {item.example && <span className="er-example-badge">{words.example}</span>}
      </p>
      <h3>
        <AppLink to={item.href}>{item.title}</AppLink>
      </h3>
      {item.summary && (
        <p className="er-solution-what" data-source-text>
          {firstSentence(item.summary)}
        </p>
      )}
      {meta && <p className="er-small">{meta}</p>}
      <p className="er-solution-actions">
        <AppLink to={item.href} className="er-btn-primary" aria-label={`${words.open.replace(/\s*→$/, "")}: ${item.title}`}>
          {words.open}
        </AppLink>
        <AppLink to={adapt} className="er-btn-secondary" aria-label={`${words.adapt}: ${item.title}`}>
          {words.adapt}
        </AppLink>
      </p>
    </li>
  );
}

/**
 * `/library`, "Find a solution" (SearchSolutions): search finished processes and answers by plain-language need,
 * from the catalog API and the delivered reports; when nothing fits, ask for it. `?q=` starts a search, and
 * `?request=<id>` also shows how one request is stored. Results carry people-readable facts only.
 */
export function Library() {
  const words = useNoun<LibraryNoun>("library").value;
  const params = new URLSearchParams(useSearch());
  const requestId = params.get("request");
  const [typed, setTyped] = useState(params.get("q") ?? "");
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [filters, setFilters] = useState<Record<"type" | "runs", string>>({ type: "any", runs: "any" });
  const [showStored, setShowStored] = useState(false);
  const [items, setItems] = useState<LibraryItem[] | null>(null);
  const [failed, setFailed] = useState(false);
  const stored = useStored(requestId, words);

  useEffect(() => {
    loadLibrary()
      .then(setItems)
      .catch(() => setFailed(true));
  }, []);

  const shown = useMemo(() => {
    if (!items) return [];
    const found = query.trim() ? searchLibrary(items, query, 1) : items;
    return found.filter((item) => {
      const kind = kindOf(item);
      if (filters.type !== "any" && filters.type !== kind) return false;
      if (filters.runs === "local" && kind !== "process") return false;
      if (filters.runs === "public" && kind !== "answer") return false;
      return true;
    });
  }, [items, query, filters]);

  if (!words) return null;
  const short = requestId ? shortRequestId(requestId) : "";
  const q = query.trim();
  const filtered = filters.type !== "any" || filters.runs !== "any";

  function search(text: string) {
    setTyped(text);
    setQuery(text);
    const url = text.trim() ? `/library?q=${encodeURIComponent(text.trim())}` : "/library";
    window.history.replaceState(null, "", requestId ? `${url}${url.includes("?") ? "&" : "?"}request=${encodeURIComponent(requestId)}` : url);
  }

  const count = !items
    ? failed
      ? words.unavailable
      : words.loading
    : shown.length === 0
      ? q
        ? fill(words.count_none, { q })
        : words.count_filtered_none
      : q
        ? shown.length === 1
          ? fill(words.count_one, { q })
          : fill(words.count_many, { n: shown.length, q })
        : shown.length === 1
          ? words.count_all_one
          : fill(words.count_all_many, { n: shown.length });

  return (
    <div className="er-library er-find">
      {requestId && (
        <AppLink to={`/requests/${encodeURIComponent(requestId)}`} className="er-text-link">
          {fill(words.back, { short })}
        </AppLink>
      )}
      <header className="er-find-head">
        <h1>{words.heading}</h1>
        <p className="er-lede">{words.lead}</p>
      </header>

      <form
        role="search"
        className="er-find-form"
        onSubmit={(event) => {
          event.preventDefault();
          search(typed);
        }}
      >
        <label htmlFor="find-q">{words.search_label}</label>
        <div className="er-find-row">
          <input
            id="find-q"
            type="search"
            className="er-input er-find-input"
            value={typed}
            placeholder={words.search_placeholder}
            onChange={(event) => setTyped(event.target.value)}
          />
          <button type="submit" className="er-btn-primary er-find-button">
            {words.search_button}
          </button>
        </div>
        <p className="er-find-tries">
          <span>{words.tries_label}</span>
          {words.tries.map((label) => (
            <button key={label} type="button" className="er-find-chip" onClick={() => search(label.toLowerCase())}>
              {label}
            </button>
          ))}
        </p>
      </form>

      <div className="er-find-filters" role="group" aria-label={words.filters_label}>
        {words.filters.map((group) => (
          <div key={group.id} className="er-find-filter" role="group" aria-label={group.label}>
            <span aria-hidden="true">{group.label}</span>
            {group.options.map((option) => (
              <button
                key={option.id}
                type="button"
                className="er-find-chip er-find-option"
                aria-pressed={filters[group.id] === option.id}
                onClick={() => setFilters((current) => ({ ...current, [group.id]: option.id }))}
              >
                {option.label}
              </button>
            ))}
          </div>
        ))}
      </div>

      <p className="er-find-count" role="status" data-testid="find-count">
        {count}
      </p>

      {shown.length > 0 && (
        <ol className="er-solutions" aria-label={words.results_label} data-testid="solutions">
          {shown.map((item) => (
            <SolutionCard key={`${item.kind}-${item.id}`} item={item} words={words} />
          ))}
        </ol>
      )}

      {items && shown.length === 0 && (
        <section className="er-find-empty" aria-labelledby="find-empty-title" data-testid="find-empty">
          <div>
            <h2 id="find-empty-title">{q ? fill(words.empty_title, { q }) : words.empty_title_filters}</h2>
            <p>{words.empty_body}</p>
          </div>
          <AppLink to={q ? `/nonprofits?q=${encodeURIComponent(q)}` : "/nonprofits"} className="er-btn-primary er-btn-large">
            {words.empty_ask}
          </AppLink>
        </section>
      )}

      <p className="er-find-note">
        {words.footnote} <AppLink to="/catalog">{words.catalog_link}</AppLink>
      </p>

      {stored && (
        <>
          <button type="button" className="er-btn-secondary er-btn-small" aria-expanded={showStored} onClick={() => setShowStored(!showStored)} data-testid="stored-switch">
            {showStored ? words.hide_stored : fill(words.show_stored, { short })}
          </button>
          <section className="er-panel er-stored" aria-labelledby="stored-title" data-testid="stored" hidden={!showStored}>
            <h2 id="stored-title">{fill(words.stored_title, { short })}</h2>
            <p className="er-small">{fill(words.stored_lead, { short })}</p>
            <div className="er-stored-columns">
              {(["object", "task"] as const).map((kind) => (
                <div key={kind}>
                  <h3>{kind === "object" ? words.stored_objects : words.stored_tasks}</h3>
                  <ul>
                    {stored
                      .filter((row) => row.kind === kind)
                      .map((row) => (
                        <li key={row.id}>
                          <span>{row.label}</span>
                          <code>{row.id}</code>
                        </li>
                      ))}
                  </ul>
                </div>
              ))}
            </div>
            <p className="er-small">{fill(words.stored_empty, { short })}</p>
          </section>
        </>
      )}
    </div>
  );
}
