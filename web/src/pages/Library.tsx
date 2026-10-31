import { useEffect, useMemo, useState } from "react";

import { Icon } from "../components/Icon";
import { getJson } from "../lib/api";
import { loadLibrary, searchLibrary, type LibraryItem } from "../lib/library";
import { fill, type NounResponse } from "../lib/nouns";
import type { RequestExampleNoun } from "../lib/status/example";
import { shortRequestId } from "../lib/status/receipts";
import type { PartPlan } from "../lib/status/types";
import { useNoun } from "../lib/useNoun";
import { AppLink, useSearch } from "../router";
import { EXAMPLES } from "./RequestStatus";

interface LibraryNoun {
  heading: string;
  lead: string;
  search_label: string;
  search_placeholder: string;
  tabs_label: string;
  tabs: Record<"all" | "objects" | "tasks", string>;
  objects_title: string;
  objects_note: string;
  tasks_title: string;
  tasks_note: string;
  kinds: Record<string, string>;
  reviewed_by: string;
  for: string;
  run_title: string;
  open: string;
  none: string;
  count_one: string;
  count_many: string;
  stored_title: string;
  stored_lead: string;
  stored_objects: string;
  stored_tasks: string;
  stored_rows: Record<string, string>;
  stored_empty: string;
  next_title: string;
  next_body: string;
  back: string;
  catalog_link: string;
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

function ItemCard({ item, words, asTask }: { item: LibraryItem; words: LibraryNoun; asTask: boolean }) {
  return (
    <li className="er-library-item" data-kind={asTask ? "task" : item.kind}>
      <span className={asTask ? "er-feature-tile er-feature-tile-verb" : "er-feature-tile"} aria-hidden="true">
        <Icon name={asTask ? "arrow-right" : item.kind === "kit" ? "package" : "file-text"} size={22} />
      </span>
      <div>
        <p className="er-library-kind">{asTask ? words.kinds.run : words.kinds[item.kind]}</p>
        <h3>
          <AppLink to={item.href}>{asTask ? fill(words.run_title, { title: item.title }) : item.title}</AppLink>
        </h3>
        {item.forWho && <p className="er-small">{fill(words.for, { who: item.forWho })}</p>}
        {!asTask && item.reviewer && <p className="er-small">{fill(words.reviewed_by, { who: item.reviewer })}</p>}
      </div>
    </li>
  );
}

/** `/library`: the shared library of nonprofit tasks and task objects; `?request=<id>` shows how one is stored. */
export function Library() {
  const words = useNoun<LibraryNoun>("library").value;
  const params = new URLSearchParams(useSearch());
  const requestId = params.get("request");
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [tab, setTab] = useState<"all" | "objects" | "tasks">("all");
  const [items, setItems] = useState<LibraryItem[] | null>(null);
  const stored = useStored(requestId, words);

  useEffect(() => {
    void loadLibrary().then(setItems);
  }, []);

  const shown = useMemo(() => {
    if (!items) return [];
    return query.trim() ? searchLibrary(items, query, 1) : items;
  }, [items, query]);

  if (!words) return null;
  const objects = tab !== "tasks" ? shown : [];
  const tasks = tab !== "objects" ? shown.filter((item) => item.kind === "kit") : [];
  const short = requestId ? shortRequestId(requestId) : "";

  return (
    <div className="er-library">
      {requestId && (
        <AppLink to={`/requests/${encodeURIComponent(requestId)}`} className="er-text-link">
          {fill(words.back, { short })}
        </AppLink>
      )}
      <h1>{words.heading}</h1>
      <p className="er-lede">{words.lead}</p>
      <div className="er-library-tools">
        <label className="er-field er-library-search">
          <span>{words.search_label}</span>
          <input
            type="search"
            className="er-input"
            value={query}
            placeholder={words.search_placeholder}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <div className="er-segmented" role="group" aria-label={words.tabs_label}>
          {(["all", "objects", "tasks"] as const).map((name) => (
            <button key={name} type="button" aria-pressed={tab === name} onClick={() => setTab(name)}>
              {words.tabs[name]}
            </button>
          ))}
        </div>
      </div>
      {items && (
        <p className="er-small" role="status">
          {shown.length === 1 ? words.count_one : fill(words.count_many, { n: shown.length })}
        </p>
      )}

      {stored && (
        <section className="er-panel er-stored" aria-labelledby="stored-title" data-testid="stored">
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
      )}

      {objects.length > 0 && (
        <section aria-labelledby="objects-title" className="er-library-section">
          <h2 id="objects-title">{words.objects_title}</h2>
          <p className="er-small">{words.objects_note}</p>
          <ul className="er-library-list">
            {objects.map((item) => (
              <ItemCard key={item.id} item={item} words={words} asTask={false} />
            ))}
          </ul>
        </section>
      )}
      {tasks.length > 0 && (
        <section aria-labelledby="tasks-title" className="er-library-section">
          <h2 id="tasks-title">{words.tasks_title}</h2>
          <p className="er-small">{words.tasks_note}</p>
          <ul className="er-library-list">
            {tasks.map((item) => (
              <ItemCard key={`run-${item.id}`} item={item} words={words} asTask />
            ))}
          </ul>
        </section>
      )}
      {items && shown.length === 0 && <p>{words.none}</p>}

      <section className="er-panel" aria-labelledby="next-title">
        <h2 id="next-title" className="er-panel-title">
          {words.next_title}
        </h2>
        <p>{words.next_body}</p>
        <AppLink to="/catalog">{words.catalog_link}</AppLink>
      </section>
    </div>
  );
}
