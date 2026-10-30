import { useState, type FormEvent } from "react";

import { FABRIC_PUBLIC_URL, SNAPSHOT } from "../config";
import type { NonprofitsNoun, NounResponse, PlanNoun } from "../lib/nouns";

type Sent =
  | { state: "idle" }
  | { state: "sending" }
  | { state: "sent"; taskId: string; plan: string[] }
  | { state: "refused"; reason: string }
  | { state: "offline" };

/**
 * One plain box: what the organization needs, with optional public links. Every label and line is
 * the `eranos.instructions/nonprofits` noun. Sending signs the organization up for a narrow
 * requester key (kept only in this page's memory), keeps the request as a noun in its own
 * namespace and files it as one request verb. There is nothing to choose: the check plans the parts.
 */
export function RequestBox({ noun, describedBy }: { noun: NonprofitsNoun; describedBy?: string }) {
  const form = noun.form;
  const [key, setKey] = useState("");
  const [principal, setPrincipal] = useState("");
  const [sent, setSent] = useState<Sent>({ state: "idle" });

  async function call(path: string, body: unknown, token: string, shared = false): Promise<Response> {
    return fetch(FABRIC_PUBLIC_URL + path, {
      method: "POST",
      credentials: "omit",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${token}`,
        ...(shared ? { "x-namespace": "main" } : {}),
      },
      body: JSON.stringify(body),
    });
  }

  async function follow(taskId: string, attempt = 0): Promise<void> {
    const response = await fetch(`/api/nouns/eranos.plans/${encodeURIComponent(taskId)}`);
    if (response.ok) {
      const noun = (await response.json()) as NounResponse<PlanNoun>;
      setSent({ state: "sent", taskId, plan: noun.value.plain });
    } else if (attempt < 40) {
      window.setTimeout(() => void follow(taskId, attempt + 1), 15000);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (SNAPSHOT) {
      setSent({ state: "offline" });
      return;
    }
    const data = new FormData(event.currentTarget);
    const text = String(data.get("need") ?? "").trim();
    const links = String(data.get("links") ?? "")
      .split(/\s+/)
      .filter((link) => link.startsWith("https://"));
    setSent({ state: "sending" });
    try {
      let token = key;
      let id = principal;
      let organizationType = String(data.get("type") ?? "");
      if (!token) {
        const signup = await fetch(FABRIC_PUBLIC_URL + "/v1/session/requester", {
          method: "POST",
          credentials: "omit",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            profile: {
              display_name: String(data.get("name") ?? ""),
              organization_type: organizationType,
              causes: String(data.get("causes") ?? "")
                .split(",")
                .map((cause) => cause.trim())
                .filter(Boolean),
            },
          }),
        });
        const minted = (await signup.json()) as { key?: string; principal_id?: string; detail?: string; profile?: { organization_type: string } };
        if (!signup.ok || !minted.key || !minted.principal_id) throw new Error(minted.detail ?? String(signup.status));
        token = minted.key;
        id = minted.principal_id;
        organizationType = minted.profile?.organization_type ?? organizationType;
        setKey(token);
        setPrincipal(id);
      }
      const brief = { text, links, organization_type: organizationType };
      const taskId = `rq-${id}-${Date.now().toString(36)}`;
      const noun = await call(`/v1/stores/org.requests/records/${taskId}`, { value: { schema_version: 1, ...brief }, expected_version: 0 }, token);
      if (!noun.ok) throw new Error(((await noun.json()) as { detail?: string }).detail ?? String(noun.status));
      const filed = await call(
        "/v1/tasks",
        { queue: "eq01", kind: "request", effect_class: "write-internal", task_id: taskId, brief },
        token,
        true,
      );
      if (!filed.ok) throw new Error(((await filed.json()) as { detail?: string }).detail ?? String(filed.status));
      setSent({ state: "sent", taskId, plan: [] });
      void follow(taskId);
    } catch (error) {
      setSent({ state: "refused", reason: error instanceof Error ? error.message : String(error) });
    }
  }

  return (
    <form className="er-request-form" data-testid="request-box" onSubmit={(event) => void submit(event)}>
      <label htmlFor="need">{form.label}</label>
      <p className="er-small" id="need-hint">
        {form.hint}
      </p>
      <textarea
        id="need"
        name="need"
        className="er-input er-textarea"
        rows={5}
        required
        minLength={10}
        maxLength={4000}
        placeholder={form.placeholder}
        aria-describedby={["need-hint", describedBy].filter(Boolean).join(" ")}
      />
      <label htmlFor="links">{form.links_label}</label>
      <p className="er-small" id="links-hint">
        {form.links_hint}
      </p>
      <textarea id="links" name="links" className="er-input er-textarea" rows={2} maxLength={2000} aria-describedby="links-hint" />
      {!key && (
        <>
          <label htmlFor="name">{form.name_label}</label>
          <input id="name" name="name" className="er-input" required minLength={2} maxLength={80} />
          <label htmlFor="type">{form.type_label}</label>
          <input id="type" name="type" className="er-input" required minLength={3} maxLength={120} />
          <label htmlFor="causes">{form.causes_label}</label>
          <input id="causes" name="causes" className="er-input" maxLength={300} />
        </>
      )}
      <label className="er-consent">
        <input type="checkbox" name="consent" required /> {form.consent}
      </label>
      <div className="er-actions er-mt-12">
        <button type="submit" className="er-btn-primary" disabled={sent.state === "sending"}>
          {sent.state === "sending" ? form.sending : form.submit}
        </button>
      </div>
      <div role="status" aria-live="polite" className="er-mt-10">
        {sent.state === "offline" && <p className="er-muted">{form.offline}</p>}
        {sent.state === "refused" && (
          <p className="er-warning">
            {form.refused} {sent.reason}
          </p>
        )}
        {sent.state === "sent" && (
          <>
            <p>
              {form.sent} <code className="er-small">{sent.taskId}</code>
            </p>
            {sent.plan.length > 0 && (
              <>
                <p>{form.planned}</p>
                <ul className="er-plain-list" data-testid="request-plan">
                  {sent.plan.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </>
            )}
            <p className="er-small">{form.follow}</p>
          </>
        )}
      </div>
    </form>
  );
}
