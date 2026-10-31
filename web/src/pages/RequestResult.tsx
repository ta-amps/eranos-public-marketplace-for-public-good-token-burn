import { useEffect, useState } from "react";

import { Icon } from "../components/Icon";
import { Evidence, StateNotice } from "../components/status/StatusParts";
import { ApiError, getJson } from "../lib/api";
import { AGORA_HOW_IT_WORKS_URL } from "../lib/marketplace";
import { fill, type NounResponse, type RequestStatusNoun } from "../lib/nouns";
import type { ExampleSolution, Report, RequestExampleNoun } from "../lib/status/example";
import { requesterKeyFor } from "../lib/status/keys";
import { DECISIONS_STORE, type DecisionsValue } from "../lib/status/live";
import { shortReceipt, shortRequestId } from "../lib/status/receipts";
import { rememberKey } from "../lib/status/keys";
import { enqueueRequest, getOwnRecord, putOwnRecord } from "../lib/status/tessera";
import type { DecisionChoice, PartPlan } from "../lib/status/types";
import { useNoun } from "../lib/useNoun";
import { AppLink, useSearch } from "../router";
import { EXAMPLES, formatClock } from "./RequestStatus";

/** A reusable process, as a SYNTHETIC example holds it: the Task Object (the process noun) and the Task to run. */
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
  /** The workers' names and declared models, when the record has them (the example does). */
  builder?: { who?: string; model?: string };
  checker?: { who?: string; model?: string };
  decision: { choice: DecisionChoice; at: number; version?: number } | null;
  decisionsVersion: number;
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
  const lines = [`# ${report.title}`, ""];
  const summary = Array.isArray(report.summary) ? report.summary.join(" ") : report.summary;
  if (summary) lines.push(summary, "");
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
        if (part?.report_id) {
          try {
            solution = (await getJson<NounResponse<Solution>>(`/api/nouns/eranos.solutions/${encodeURIComponent(part.report_id)}`)).value;
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
        if (current) setLoaded({ example: false, requestId: id, part, solution, decision, decisionsVersion });
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
          {r.revising_head}
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
          {r.changes_label}
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
        <p className="er-small">{fill(r.changes_note ?? "", { n: partNumber })}</p>
        <button type="button" className="er-btn-primary" disabled={saving || note.trim().length < 3} onClick={() => onDecide("changes", note.trim())}>
          {saving ? r.saving : r.send_back}
        </button>
        <button type="button" className="er-btn-quiet" onClick={() => setAsking(false)}>
          {r.cancel}
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
    const label = loaded.decision.choice === "use" ? r.recorded_use : loaded.decision.choice === "changes" ? r.recorded_changes : r.recorded_dont;
    return (
      <div className="er-decision er-decision-done" data-testid="decision-recorded">
        <p className="er-decision-head">
          <Icon name="user-round-check" size={20} strokeWidth={2} />
          {label}
        </p>
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
        {r.your_turn}
      </p>
      <p className="er-small">
        {r.you_decide} {legal ? r.note : r.note_plain}
      </p>
      <button type="button" className="er-btn-primary er-btn-large" disabled={saving} onClick={() => onDecide("use")}>
        {saving ? r.saving : processPart ? words.result.use : r.use}
      </button>
      <button type="button" className="er-btn-secondary" disabled={saving} onClick={() => setAsking(true)}>
        {r.changes}
      </button>
      <button type="button" className="er-btn-quiet" disabled={saving} onClick={() => onDecide("dont")}>
        {r.dont}
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
  const search = useSearch();
  const partNumber = Math.max(1, Number(new URLSearchParams(search).get("part")) || 1);
  const [key] = useState(() => (EXAMPLES[id] ? "example" : requesterKeyFor(id, window.location.hash)));
  const { loaded, missing } = useResult(id, partNumber, EXAMPLES[id] ? null : key);
  const [decision, setDecision] = useState<Loaded["decision"]>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [revision, setRevision] = useState<{ id: string | null } | null>(null);
  const [decisionTask, setDecisionTask] = useState<string | null>(null);

  useEffect(() => {
    if (words) document.title = fill(words.titles.doc_report ?? "", { short: shortRequestId(id) });
  }, [words, id]);

  if (!words) return null;
  const r = words.report;
  const shortId = shortRequestId(loaded?.requestId ?? id);
  const back = (
    <AppLink to={`/requests/${encodeURIComponent(id)}`} className="er-text-link">
      {fill(words.result.back ?? "", { short: shortId })}
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
  const processPart = view.part?.route === "private-files" || Boolean(view.solution?.process);
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

  const receipts = [solution?.research_receipt ?? solution?.build_receipt, solution?.review_receipt].filter((x): x is string => Boolean(x));
  const named = view.builder?.who && view.checker?.who;
  const meta = [
    named
      ? fill(r.meta_named ?? "", { builder: view.builder?.who ?? "", builder_model: view.builder?.model ?? "", checker: view.checker?.who ?? "", checker_model: view.checker?.model ?? "" })
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
        <p className="er-chip-row">
          <span className="er-chip er-chip-noun">{fill(processPart ? (words.result.process_badge ?? "") : (r.part_badge ?? ""), { n: partNumber })}</span>
          {approved && (
            <span className="er-reviewed-line" data-testid="reviewed-badge">
              {view.checker?.who ? fill(r.reviewed_line ?? "", { who: view.checker.who }) : r.approved_badge}
              {solution?.review_receipt && <span className="er-receipt"> · {fill(words.chips.receipt ?? "", { r: shortReceipt(solution.review_receipt) })}</span>}
            </span>
          )}
        </p>
        {!solution && <StateNotice tone="wait" head={processPart ? (words.result.not_ready ?? "") : (r.not_ready ?? "")} testId="result-not-ready" />}
        {report && (
          <>
            <h1>{report.title}</h1>
            <p className="er-result-meta">{meta.join(" · ")}</p>
            {report.summary && (
              <section className="er-panel">
                <h2 className="er-panel-title">{r.in_short}</h2>
                <p>{Array.isArray(report.summary) ? report.summary.join(" ") : report.summary}</p>
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
                    {source.title.replace(/^SYNTHETIC\s+/, "")} · <span className="er-mono">{host(source.url)}</span>
                    {source.published ? ` · ${fill(r.published ?? "", { date: source.published })}` : ""} ·{" "}
                    <span className="er-checked">{r.checked}</span>
                  </li>
                ))}
              </ol>
              {report.sources.some((source) => source.synthetic) && <p className="er-small">{r.synthetic_sources}</p>}
              {report.disclaimer && <p className="er-small">{report.disclaimer}</p>}
            </section>
          </>
        )}
        {process && (
          <>
            <h1>{process.task_object.title}</h1>
            <p className="er-result-meta">{meta.join(" · ")}</p>
            {view.example && <p className="er-small">{words.result.example_note}</p>}
            <section className="er-panel er-process" aria-labelledby="process-title" data-testid="task-object">
              <p className="er-chip-row">
                <span className="er-chip er-chip-noun er-chip-mono">{words.result.task_object}</span>
                <span className="er-mono er-small">{process.task_object.id}</span>
              </p>
              <h2 id="process-title">{words.result.what}</h2>
              <p>{process.task_object.description}</p>
              <h3>{words.result.holds}</h3>
              <ul className="er-plain-list">
                {process.task_object.holds.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
              <div className="er-process-columns">
                <div>
                  <h3>{words.result.how_to}</h3>
                  <ol className="er-plain-steps">
                    {process.task_object.how_to.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ol>
                </div>
                <div>
                  <h3>{words.result.install}</h3>
                  <ol className="er-plain-steps">
                    {process.task_object.install.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ol>
                </div>
              </div>
              <h3>{words.result.person_only}</h3>
              <ul className="er-person-list">
                {process.task_object.person_only.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </section>
            <section className="er-panel er-process" aria-labelledby="task-title" data-testid="runnable-task">
              <p className="er-chip-row">
                <span className="er-chip er-chip-verb er-chip-mono">{words.result.task}</span>
                <span className="er-mono er-small">{process.task.id}</span>
              </p>
              <h2 id="task-title">{words.result.run_title}</h2>
              <p className="er-small">{words.result.run_lead}</p>
              <p>
                <strong>{process.task.title}</strong>
              </p>
              <dl className="er-task-facts">
                <div>
                  <dt>{words.result.input}</dt>
                  <dd>{process.task.input}</dd>
                </div>
                <div>
                  <dt>{words.result.output}</dt>
                  <dd>{process.task.output}</dd>
                </div>
                <div>
                  <dt>{words.result.schedule}</dt>
                  <dd>{process.task.schedule}</dd>
                </div>
              </dl>
              <h3>{words.result.embodiments}</h3>
              <ul className="er-embodiments">
                {process.task.embodiments.map((way) => (
                  <li key={way.id} data-embodiment={way.id}>
                    <strong>{way.name}</strong>
                    <span>{way.how}</span>
                    {way.container && (
                      <span className="er-embodiment-container">
                        <span className="er-small">{words.result.container}</span>
                        <code>{way.container}</code>
                      </span>
                    )}
                  </li>
                ))}
              </ul>
              <div className="er-actions">
                <button
                  type="button"
                  className="er-btn-secondary"
                  onClick={() =>
                    void navigator.clipboard
                      .writeText([process.task.title, process.task.input, process.task.output, ...process.task_object.how_to].join("\n"))
                      .then(() => setCopied(true), () => setCopied(false))
                  }
                >
                  <Icon name="copy" size={18} />
                  {copied ? words.result.copied : words.result.copy_task}
                </button>
              </div>
            </section>
          </>
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
            {receipts.map((receipt) => (
              <Evidence key={receipt} value={receipt} words={words} />
            ))}
          </section>
        )}
      </aside>
    </div>
  );
}
