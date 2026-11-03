import { useEffect, useState } from "react";

import { Icon } from "../components/Icon";
import { Evidence, StateNotice } from "../components/status/StatusParts";
import { SNAPSHOT } from "../config";
import { ApiError, getJson } from "../lib/api";
import { AGORA_HOW_IT_WORKS_URL } from "../lib/marketplace";
import { modelName, useModels } from "../lib/models";
import { readableSummary, readableTitle } from "../lib/reportWords";
import { fill, type NounResponse, type RequestStatusNoun } from "../lib/nouns";
import type { ExampleSolution, Report, RequestExampleNoun } from "../lib/status/example";
import { requesterKeyFor, dropKeyFromAddress } from "../lib/status/keys";
import { DECISIONS_STORE, type DecisionsValue } from "../lib/status/live";
import { shortReceipt, shortRequestId } from "../lib/status/ids";
import { rememberKey } from "../lib/status/keys";
import { enqueueRequest, getOwnRecord, putOwnRecord } from "../lib/status/tessera";
import type { DecisionChoice, PartPlan } from "../lib/status/types";
import { useNoun } from "../lib/useNoun";
import { AppLink, useSearch } from "../router";
import { EXAMPLES, formatClock } from "./RequestStatus";

/** A reusable process, as an example holds it: the task object (the process noun) and the task to run. */
interface ProcessSolution {
  task_object: {
    id: string;
    title: string;
    description: string;
    how_to: string[];
    install: string[];
    holds: string[];
    person_only: string[];
  };
  /** Examples to try the process on before any real files (each marked as a practice case). */
  practice?: { input: string; expect: string }[];
  task: {
    id: string;
    title: string;
    input: string;
    output: string;
    schedule: string;
    embodiments: { id: string; name: string; how: string; container: string | null }[];
  };
}

type Solution = ExampleSolution & { process?: ProcessSolution; build_receipt?: string };

interface Loaded {
  example: boolean;
  /** The request's own id (the example's is its replayed request). */
  requestId: string;
  part: PartPlan | null;
  solution: Solution | null;
  /** The request has closed with no result for this part, so "appears once checked" would be untrue. */
  closedWithoutResult?: boolean;
  /** The workers' names and declared models, when the record has them (the example does). */
  builder?: { who?: string; model?: string };
  checker?: { who?: string; model?: string };
  decision: { choice: DecisionChoice; at: number; version?: number } | null;
  decisionsVersion: number;
}

interface PackageRecord {
  blob_sha256?: string;
  tags?: string[];
  review_receipt?: string | null;
  drafter_key_id?: string;
  reviewer_key_id?: string;
}

/** The same rule the Worker applies before it serves /p/<id>/download. */
function servable(value: PackageRecord): value is PackageRecord & { blob_sha256: string } {
  const tags = value.tags ?? [];
  return (
    /^[0-9a-f]{64}$/.test(value.blob_sha256 ?? "") &&
    tags.includes("status:verified") &&
    !tags.includes("status:quarantined") &&
    Boolean(value.review_receipt) &&
    Boolean(value.drafter_key_id) &&
    Boolean(value.reviewer_key_id) &&
    value.drafter_key_id !== value.reviewer_key_id
  );
}

function sentences(text: string): string[] {
  return text
    .split(/(?<=[.!?])\s+/)
    .map((line) => line.trim())
    .filter(Boolean);
}

/** The Markdown address of a process result, which any agent can read (served by the Worker from the same nouns). */
function processDoc(id: string, part: number, doc: "agent" | "practice"): string {
  return `${window.location.origin}/p/${encodeURIComponent(id)}/${doc}.md${part > 1 ? `?part=${part}` : ""}`;
}

function CopyLine({ text, words }: { text: string; words: RequestStatusNoun }) {
  const [done, setDone] = useState(false);
  return (
    <div className="er-copy-line">
      <code>{text}</code>
      <button
        type="button"
        className="er-btn-secondary er-btn-small"
        onClick={() =>
          void navigator.clipboard.writeText(text).then(
            () => {
              setDone(true);
              window.setTimeout(() => setDone(false), 2400);
            },
            () => setDone(false),
          )
        }
      >
        {done ? words.steps.copied : words.steps.copy}
      </button>
    </div>
  );
}

function RunChoice({
  way,
  words,
  open: initial,
  first,
  children,
}: {
  way: { id: string; name: string; how: string; container: string | null };
  words: RequestStatusNoun;
  open: boolean;
  first: boolean;
  children?: React.ReactNode;
}) {
  const [open, setOpen] = useState(initial);
  return (
    <li className="er-run-choice" data-embodiment={way.id} data-first={first || undefined}>
      <div className="er-run-head">
        <strong>{way.name}</strong>
        <button type="button" className="er-btn-quiet er-btn-small" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? words.steps.hide_how : words.steps.show_how}
        </button>
      </div>
      <span className="er-small">{way.how}</span>
      {open && (
        <div className="er-run-body">
          {children}
          {way.container && (
            <span className="er-embodiment-container">
              <span className="er-small">{words.result.container}</span>
              <code>{way.container}</code>
            </span>
          )}
        </div>
      )}
    </li>
  );
}

function host(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

function download(name: string, type: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function reportMarkdown(report: Report): string {
  const lines = [`# ${readableTitle(report.title, report.question)}`, ""];
  const summary = Array.isArray(report.summary) ? report.summary.join(" ") : report.summary;
  if (summary) lines.push(readableSummary(summary), "");
  const index = new Map(report.sources.map((s, i) => [s.id, i + 1]));
  for (const claim of report.claims) {
    lines.push(`- ${claim.text ?? ""} ${claim.citations.map((c) => `[${index.get(c.source) ?? "?"}]`).join(" ")}`);
    for (const c of claim.citations) lines.push(`  > ${c.quote}`);
  }
  lines.push("", "## Sources", "");
  report.sources.forEach((s, i) => lines.push(`${i + 1}. ${s.title}, ${s.url}${s.published ? `, published ${s.published}` : ""}`));
  if (report.disclaimer) lines.push("", report.disclaimer);
  if (report.decision) lines.push("", report.decision);
  return lines.join("\n") + "\n";
}

function useResult(id: string, partNumber: number, key: string | null): { loaded: Loaded | null; missing: boolean } {
  const exampleKey = EXAMPLES[id];
  const example = useNoun<RequestExampleNoun & { solution: Solution }>(exampleKey ?? "request-example").value;
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    if (exampleKey) {
      if (!example) return;
      const planned = example.events.find((e) => e.type === "planned");
      const submitted = example.events.find((e) => e.type === "work_submitted" && e.part === partNumber);
      const claimed = example.events.find((e) => e.type === "work_claimed" && e.part === partNumber);
      const checked = example.events.find((e) => e.type === "check_claimed" && e.part === partNumber);
      setLoaded({
        example: true,
        requestId: example.request.id,
        part: planned?.parts?.find((p) => p.part === partNumber) ?? null,
        solution: example.solution,
        builder: { who: submitted?.worker ?? claimed?.worker, model: claimed?.model },
        checker: { who: checked?.worker, model: checked?.model },
        decision: null,
        decisionsVersion: 0,
      });
      return;
    }
    let current = true;
    (async () => {
      try {
        const plan = await getJson<NounResponse<{ parts?: PartPlan[] }>>(`/api/nouns/eranos.plans/${encodeURIComponent(id)}`);
        const part = plan.value.parts?.find((p) => p.part === partNumber) ?? null;
        let solution: Solution | null = null;
        // A report part names its report; a process part names its kit; a reused part names the earlier result it
        // reuses. All three are eranos.solutions nouns.
        const resultId = part?.report_id ?? part?.kit_id ?? part?.reused_from?.key;
        if (resultId) {
          try {
            solution = (await getJson<NounResponse<Solution>>(`/api/nouns/eranos.solutions/${encodeURIComponent(resultId)}`)).value;
          } catch (error) {
            if (!(error instanceof ApiError && error.status === 404)) throw error;
          }
        }
        let closedWithoutResult = false;
        if (!solution) {
          try {
            const request = await getJson<NounResponse<{ status?: string }>>(`/api/nouns/eranos.requests/${encodeURIComponent(id)}`);
            closedWithoutResult = request.value.status === "closed";
          } catch (error) {
            if (!(error instanceof ApiError && error.status === 404)) throw error;
          }
        }
        let decision: Loaded["decision"] = null;
        let decisionsVersion = 0;
        if (key) {
          const record = await getOwnRecord<DecisionsValue>(DECISIONS_STORE, id, key);
          decisionsVersion = record?.version ?? 0;
          const mine = record?.value.parts?.[String(partNumber)];
          if (mine) decision = { choice: mine.choice, at: mine.decided_at, version: record?.version };
        }
        if (current) setLoaded({ example: false, requestId: id, part, solution, closedWithoutResult, decision, decisionsVersion });
      } catch {
        if (current) setMissing(true);
      }
    })();
    return () => {
      current = false;
    };
  }, [id, partNumber, key, example, exampleKey]);

  return { loaded, missing };
}

function DecisionPanel({
  words,
  loaded,
  processPart,
  keyHeld,
  onDecide,
  saving,
  error,
  partNumber,
  revision,
  decisionTask,
}: {
  words: RequestStatusNoun;
  loaded: Loaded;
  processPart: boolean;
  keyHeld: boolean;
  onDecide: (choice: DecisionChoice, note?: string) => void;
  saving: boolean;
  error: string;
  partNumber: number;
  revision: { id: string | null } | null;
  decisionTask: string | null;
}) {
  const r = words.report;
  const legal = Boolean(loaded.part?.legal);
  const [asking, setAsking] = useState(false);
  const [note, setNote] = useState("");
  if (revision) {
    return (
      <div className="er-decision er-decision-done" data-testid="decision-revising">
        <p className="er-decision-head">
          <Icon name="circle-dashed" size={20} strokeWidth={2} />
          {words.decide.pending_head}
        </p>
        <p className="er-small">
          {revision.id
            ? fill(r.revising_body ?? "", { n: partNumber, short: shortRequestId(revision.id) })
            : fill(r.revising_example ?? "", { n: partNumber })}
        </p>
        {revision.id && (
          <AppLink to={`/requests/${encodeURIComponent(revision.id)}`} className="er-text-link">
            {r.follow_link} →
          </AppLink>
        )}
      </div>
    );
  }
  if (asking && keyHeld) {
    return (
      <div className="er-decision er-decision-open" data-testid="decision-changes">
        <label htmlFor="changes-note" className="er-decision-head">
          {words.decide.changes_label}
        </label>
        <textarea
          id="changes-note"
          className="er-input er-textarea"
          rows={4}
          dir="auto"
          maxLength={1000}
          value={note}
          placeholder={r.changes_placeholder}
          onChange={(event) => setNote(event.target.value)}
        />
        <p className="er-small">{words.decide.changes_note}</p>
        <button type="button" className="er-btn-primary" disabled={saving || note.trim().length < 3} onClick={() => onDecide("changes", note.trim())}>
          {saving ? r.saving : words.decide.send}
        </button>
        <button type="button" className="er-btn-quiet" onClick={() => setAsking(false)}>
          {words.decide.cancel}
        </button>
        {error && (
          <p className="er-field-error" role="alert">
            {error}
          </p>
        )}
      </div>
    );
  }
  if (loaded.decision) {
    const label = loaded.decision.choice === "use" ? words.decide.done_head : loaded.decision.choice === "changes" ? r.recorded_changes : r.recorded_dont;
    return (
      <div className="er-decision er-decision-done" data-testid="decision-recorded">
        <p className="er-decision-head">
          <Icon name="user-round-check" size={20} strokeWidth={2} />
          {label}
        </p>
        {loaded.decision.choice === "use" && <p className="er-small">{words.decide.done_body}</p>}
        <p className="er-small">
          {loaded.example
            ? fill(r.recorded_example ?? "", { time: formatClock(loaded.decision.at) })
            : fill(r.recorded_at ?? "", { time: formatClock(loaded.decision.at), v: loaded.decision.version ?? "" })}
        </p>
        {decisionTask && (
          <p className="er-small" data-testid="decision-task">
            {fill(r.decision_filed ?? "", { short: shortRequestId(decisionTask) })}
          </p>
        )}
        <a href={AGORA_HOW_IT_WORKS_URL} className="er-text-link">
          {r.bridge_link} →
        </a>
      </div>
    );
  }
  if (!keyHeld) {
    return (
      <div className="er-decision" data-testid="decision-read-only">
        <p className="er-small">{r.read_only}</p>
      </div>
    );
  }
  return (
    <div className="er-decision er-decision-open" data-testid="decision-open">
      <p className="er-decision-head er-decision-turn">
        <Icon name="circle-alert" size={20} strokeWidth={2} />
        {words.decide.title}
      </p>
      <p className="er-small">{processPart ? words.decide.lead_process : legal ? words.decide.lead_information : r.note_plain}</p>
      <button type="button" className="er-btn-primary er-btn-large" disabled={saving} onClick={() => onDecide("use")}>
        {saving ? r.saving : words.decide.yes}
      </button>
      <button type="button" className="er-btn-secondary" disabled={saving} onClick={() => setAsking(true)}>
        {words.decide.changes}
      </button>
      {error && (
        <p className="er-field-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

/** `/requests/<id>/result?part=N`: a part's cited report or reusable process, and your decision on it. */
export function RequestResult({ id }: { id: string }) {
  const words = useNoun<RequestStatusNoun>("request-status").value;
  // Model names come from the models.meta Task Object (lib/models.ts), never from typed text.
  const catalog = useModels();
  const search = useSearch();
  const partNumber = Math.max(1, Number(new URLSearchParams(search).get("part")) || 1);
  const [key] = useState(() => (EXAMPLES[id] ? "example" : requesterKeyFor(id, window.location.hash)));
  useEffect(() => {
    if (!EXAMPLES[id]) dropKeyFromAddress(id);
  }, [id]);
  const { loaded, missing } = useResult(id, partNumber, EXAMPLES[id] ? null : key);
  const [decision, setDecision] = useState<Loaded["decision"]>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [revision, setRevision] = useState<{ id: string | null } | null>(null);
  const [decisionTask, setDecisionTask] = useState<string | null>(null);
  // A published process package (catalog record reviewed by a different key) can be downloaded as its exact bytes.
  const [packageSha, setPackageSha] = useState<string | null>(null);
  const kitId = loaded?.part?.kit_id;
  useEffect(() => {
    if (!kitId || EXAMPLES[id] || SNAPSHOT) return;
    let live = true;
    getJson<PackageRecord>(`/api/catalog/${encodeURIComponent(kitId)}`)
      .then((found) => {
        const value = (found as { value?: PackageRecord }).value ?? found;
        if (live && servable(value)) setPackageSha(value.blob_sha256 ?? null);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [kitId, id]);

  useEffect(() => {
    if (words) document.title = fill(words.titles.doc_report ?? "", { short: shortRequestId(id) });
  }, [words, id]);

  if (!words) return null;
  const r = words.report;
  const shortId = shortRequestId(loaded?.requestId ?? id);
  const back = (
    <AppLink to={`/requests/${encodeURIComponent(id)}`} className="er-text-link">
      {words.steps.back}
    </AppLink>
  );
  if (missing) {
    return (
      <div className="er-result-page">
        {back}
        <StateNotice tone="info" head={fill(words.notices.unknown?.head ?? "", { id })} body={words.notices.unknown?.body} testId="notice-unknown" />
      </div>
    );
  }
  if (!loaded) return null;
  const view: Loaded = { ...loaded, decision: decision ?? loaded.decision };
  const processPart = view.part?.route === "private-files" || view.part?.route === "process" || view.part?.output_type === "process" || Boolean(view.solution?.process);
  const solution = view.solution;
  const report = solution?.report;
  const process = solution?.process;

  async function decide(choice: DecisionChoice, note?: string) {
    setError("");
    const at = Date.now() / 1000;
    if (view.example) {
      setDecision({ choice, at });
      if (choice === "changes") setRevision({ id: null });
      return;
    }
    if (!key || key === "example") return;
    setSaving(true);
    try {
      const current = await getOwnRecord<DecisionsValue>(DECISIONS_STORE, id, key);
      const value: DecisionsValue = {
        schema_version: 1,
        request_id: id,
        parts: { ...(current?.value.parts ?? {}), [String(partNumber)]: { choice, decided_at: at, ...(note ? { note } : {}) } },
      };
      const saved = await putOwnRecord(DECISIONS_STORE, id, value, current?.version ?? 0, key);
      setDecision({ choice, at, version: saved.version });
      // Option A: the decision is one request task on eq01, filed with this request's key. The worker that claims it
      // records a "decided" event, with its receipt, on this request's history; a note sends the part back in line.
      const principal = /^rq-(r_[0-9a-f]{32})-/.exec(id)?.[1];
      if (principal) {
        const decisionTask = `rq-${principal}-${Date.now().toString(36)}`;
        const brief = {
          text: fill(choice === "changes" ? (r.changes_text ?? "") : (r.decision_text ?? ""), { n: partNumber, id, note: note ?? "", choice }),
          links: [],
          organization_type: "",
          decision: { request_id: id, part: partNumber, choice, ...(note ? { note } : {}) },
        };
        await enqueueRequest(decisionTask, brief, key);
        rememberKey(decisionTask, key);
        setDecisionTask(decisionTask);
        if (choice === "changes") setRevision({ id: decisionTask });
      }
    } catch (failure) {
      setError(fill(r.save_failed ?? "", { reason: failure instanceof Error ? failure.message : String(failure) }));
    } finally {
      setSaving(false);
    }
  }

  const namedModel = (helper: { who?: string; model?: string } | undefined) =>
    words.model_names
      ? (modelName(catalog, helper?.model, words.model_names, /^eranos[-_.\s]/i.test(helper?.who ?? "")) ?? words.model_names.own)
      : "";
  // The record that holds this result: the example's own noun, or the delivered report in the public store.
  const recordHref = loaded?.example
    ? `/api/nouns/eranos.instructions/${processPart ? "request-example-process" : "request-example"}`
    : report
      ? `/api/nouns/eranos.solutions/${encodeURIComponent(report.report_id)}`
      : undefined;
  const receipts = [solution?.research_receipt ?? solution?.build_receipt, solution?.review_receipt].filter((x): x is string => Boolean(x));
  const named = view.builder?.who && view.checker?.who;
  const meta = [
    named
      ? fill(r.meta_named ?? "", {
          builder: view.builder?.who ?? "",
          builder_model: namedModel(view.builder),
          checker: view.checker?.who ?? "",
          checker_model: namedModel(view.checker),
        })
      : processPart
        ? words.result.meta_anon
        : r.meta_anon,
    report ? fill(r.sources_count ?? "", { n: report.sources.length }) : null,
    receipts.length ? fill(r.receipts ?? "", { list: receipts.map(shortReceipt).join(", ") }) : null,
  ].filter(Boolean);
  const approved = Boolean(solution?.review_receipt);
  const sourceIndex = new Map((report?.sources ?? []).map((s, i) => [s.id, i + 1]));

  return (
    <div className="er-result-page" data-testid="request-result">
      <article className="er-result-main">
        {back}
        <p className="er-chip-row" data-testid="result-tags">
          <span className="er-chip er-chip-object">{processPart ? words.steps.tag_process : words.steps.tag_information}</span>
          {revision ? (
            <span className="er-chip">{words.steps.tag_updating}</span>
          ) : (
            approved && <span className="er-chip er-chip-real">{words.steps.tag_checked}</span>
          )}
        </p>
        {!solution &&
          (view.closedWithoutResult ? (
            <StateNotice tone="wait" head={words.result.closed_without_result ?? ""} testId="result-closed-without-result" />
          ) : (
            <StateNotice tone="wait" head={processPart ? (words.result.not_ready ?? "") : (r.not_ready ?? "")} testId="result-not-ready" />
          ))}
        {solution && view.part?.reused_from && <StateNotice tone="wait" head={words.result.reused_note ?? ""} testId="result-reused-note" />}
        {report && (
          <>
            <h1>{readableTitle(report.title, report.question)}</h1>
            {report.summary && (
              <section className="er-panel" data-testid="in-short">
                <h2 className="er-panel-title">{words.steps.in_short}</h2>
                {Array.isArray(report.summary) ? (
                  <ol className="er-plain-steps">
                    {report.summary.map((point) => (
                      <li key={point}>{readableSummary(point)}</li>
                    ))}
                  </ol>
                ) : (
                  <p>{readableSummary(report.summary)}</p>
                )}
                <p className="er-small">{words.steps.in_short_note}</p>
              </section>
            )}
            <section className="er-result-section" aria-labelledby="findings-title">
              <h2 id="findings-title">{r.findings}</h2>
              <ul className="er-claims">
                {report.claims.map((claim) => (
                  <li key={claim.id}>
                    <p>
                      {claim.text}{" "}
                      {[...new Set(claim.citations.map((c) => c.source))].map((source) => (
                        <a key={source} href={`#source-${sourceIndex.get(source) ?? 0}`} className="er-cite">
                          [{sourceIndex.get(source) ?? "?"}]
                        </a>
                      ))}
                    </p>
                    {claim.citations.map((c, i) => (
                      <blockquote key={`q-${i}`} className="er-quote">
                        “{c.quote}”
                      </blockquote>
                    ))}
                  </li>
                ))}
              </ul>
              {report.claims.some((claim) => claim.unclear) && <p className="er-gentle">{r.unclear}</p>}
            </section>
            <section className="er-result-section" aria-labelledby="sources-title">
              <h2 id="sources-title">{fill(r.sources ?? "", { n: report.sources.length })}</h2>
              <ol className="er-sources">
                {report.sources.map((source, i) => (
                  <li key={source.id} id={`source-${i + 1}`}>
                    {source.title} · <span className="er-mono">{host(source.url)}</span>
                    {source.published ? ` · ${fill(r.published ?? "", { date: source.published })}` : ""} ·{" "}
                    <span className="er-checked">{r.checked}</span>
                  </li>
                ))}
              </ol>
              {report.sources.some((source) => source.is_example) && <p className="er-small">{r.example_sources}</p>}
              {report.disclaimer && <p className="er-small">{report.disclaimer}</p>}
            </section>
          </>
        )}
        {process && (
          <>
            <h1>{process.task_object.title}</h1>
            {view.example && <p className="er-small">{words.result.example_note}</p>}
            <section className="er-panel er-process er-step" aria-labelledby="process-title" data-testid="task-object" data-object-id={process.task_object.id}>
              <h2 id="process-title">{words.steps.what}</h2>
              {packageSha && (
                <p className="er-download" data-testid="download-process">
                  <a href={`/p/${encodeURIComponent(id)}/download${partNumber > 1 ? `?part=${partNumber}` : ""}`} className="er-btn-secondary er-btn-small" download>
                    {words.steps.download}
                  </a>
                  <span className="er-small">{words.steps.download_note}</span>
                </p>
              )}
              <ul className="er-plain-list">
                {sentences(process.task_object.description).map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
              {process.task_object.person_only.length > 0 && (
                <>
                  <p className="er-small er-step-sub">{words.steps.only_person}</p>
                  <ul className="er-person-list">
                    {process.task_object.person_only.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </>
              )}
            </section>
            {(process.practice?.length ?? 0) > 0 && (
              <section className="er-panel er-process er-step" aria-labelledby="practice-title" data-testid="practice-step">
                <h2 id="practice-title">{words.steps.practice}</h2>
                <p>{words.steps.practice_lead}</p>
                <CopyLine text={fill(words.steps.practice_message, { url: processDoc(id, partNumber, "practice") })} words={words} />
              </section>
            )}
            <section className="er-panel er-process er-step" aria-labelledby="task-title" data-testid="runnable-task" data-task-id={process.task.id}>
              <h2 id="task-title">{words.steps.run}</h2>
              <p>{words.steps.run_lead}</p>
              <ul className="er-run-choices">
                {process.task.embodiments.map((way, index) => (
                  <RunChoice key={way.id} way={way} words={words} open={false} first={index === 0}>
                    {way.id === "agent" && <CopyLine text={fill(words.steps.agent_message, { url: processDoc(id, partNumber, "agent") })} words={words} />}
                    {way.id === "agent" && (
                      <ol className="er-plain-steps">
                        {process.task_object.how_to.map((line) => (
                          <li key={line}>{line}</li>
                        ))}
                      </ol>
                    )}
                    {way.id !== "agent" && (
                      <ol className="er-plain-steps">
                        {process.task_object.install.map((line) => (
                          <li key={line}>{line}</li>
                        ))}
                      </ol>
                    )}
                  </RunChoice>
                ))}
              </ul>
              <p className="er-small">
                {process.task.input} → {process.task.output}. {process.task.schedule}
              </p>
            </section>
          </>
        )}
        {approved && (
          <details className="er-details er-checked-how">
            <summary>{words.steps.checked_how}</summary>
            <p className="er-reviewed-line" data-testid="reviewed-badge">
              {view.checker?.who
                ? /^eranos[-_.\s]/i.test(view.checker.who) && r.reviewed_line_eranos
                  ? r.reviewed_line_eranos
                  : fill(r.reviewed_line ?? "", { who: view.checker.who })
                : r.approved_badge}
              {solution?.review_receipt && (
                <>
                  {" "}
                  · <Evidence value={solution.review_receipt} words={words} href={recordHref} />
                </>
              )}
            </p>
            <p className="er-result-meta">{meta.join(" · ")}</p>
          </details>
        )}
        {solution && (
          <section className="er-bridge">
            <span className="er-bridge-mark" aria-hidden="true" />
            <span>
              <strong>{r.bridge_title}</strong>
              <span>{r.bridge_body}</span>
            </span>
            <a href={AGORA_HOW_IT_WORKS_URL} className="er-btn-secondary">
              {r.bridge_link} →
            </a>
          </section>
        )}
      </article>
      <aside className="er-result-aside" aria-label={r.decision_label}>
        {solution && (
          <DecisionPanel
            words={words}
            loaded={view}
            processPart={processPart}
            keyHeld={Boolean(key)}
            onDecide={(choice, note) => void decide(choice, note)}
            saving={saving}
            error={error}
            partNumber={partNumber}
            revision={revision}
            decisionTask={decisionTask}
          />
        )}
        {report && (
          <section className="er-panel er-downloads">
            <h2 className="er-panel-title">{r.download}</h2>
            <button type="button" className="er-link-button" onClick={() => window.print()}>
              {r.download_pdf}
            </button>
            <button type="button" className="er-link-button" onClick={() => download(`${report.report_id}.md`, "text/markdown", reportMarkdown(report))}>
              {r.download_md}
            </button>
            <button
              type="button"
              className="er-link-button"
              onClick={() =>
                download(
                  `${report.report_id}-receipts.json`,
                  "application/json",
                  JSON.stringify({ request_id: id, report_id: report.report_id, report_sha256: solution?.report_sha256, research_receipt: solution?.research_receipt, review_receipt: solution?.review_receipt }, null, 2),
                )
              }
            >
              {r.download_json}
            </button>
            {receipts.length > 0 && <Evidence value={receipts[0]} words={words} href={recordHref} />}
          </section>
        )}
      </aside>
    </div>
  );
}
