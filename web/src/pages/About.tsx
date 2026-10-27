export function About() {
  return (
    <div>
      <section className="er-hero">
        <h1>About Eranos &amp; safety boundaries</h1>
        <p className="er-lede">
          In ancient Greece, an <em>eranos</em> was a civic potluck where everyone contributed a spare share to equip a
          common good. Eranos lets people donate unused AI tokens to build, test, and independently review
          off-the-shelf agent skills, tools, files, and agentic processes that NGOs, clinics, hotlines, and community
          organizations can adopt at zero cost -- without ever handing human judgment or client conversations over to
          automation.
        </p>
      </section>

      <div className="er-grid">
        <section className="er-card">
          <h2>Hard autonomy boundaries</h2>
          <p className="er-muted">
            Schema validators and the deterministic verifier enforce that <code>interview</code>,{" "}
            <code>legal_judgment</code>, <code>crisis_safety_plan</code>, <code>individual_decision</code>, and{" "}
            <code>external_send</code> steps remain strictly <code>human_only</code>. Every MCP tool in the catalog
            is read-only (<code>read_only: true</code>).
          </p>
        </section>

        <section className="er-card">
          <h2>Two-step independent verification &amp; quarantine</h2>
          <p className="er-muted">
            Unreviewed drafts on <code>eq01</code> and <code>eq02</code> remain quarantined (
            <code>visibility_scope: surface_only</code>) until deterministic schema, open-SPDX, copy, and citation
            checks pass and an independent agent or steward approves on <code>eq03</code> (
            <code>drafter != reviewer</code> across both worker ID and Tessera key ID).
          </p>
        </section>

        <section className="er-card">
          <h2>Synthetic-only &amp; non-accusatory</h2>
          <p className="er-muted">
            Every example fixture in Eranos begins with <code>SYNTHETIC:</code> and holds zero personal data. Copy
            validators reject accusatory labels and prohibit surveillance, scraping, or personal-data-harvesting
            requests.
          </p>
        </section>
      </div>
    </div>
  );
}
