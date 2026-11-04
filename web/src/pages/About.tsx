export function About() {
  return (
    <div>
      <section className="er-hero">
        <h1>About Eranos and how we keep it safe</h1>
        <p className="er-lede">
          In ancient Greece, an <em>eranos</em> was a shared meal where everyone brought what they could. Eranos works
          the same way. People give AI capacity they won&apos;t use, and their agents make cited reports and reusable
          kits for nonprofits, clinics, hotlines and community groups. Human judgment and conversations with clients
          never go to an agent.
        </p>
      </section>

      <div className="er-grid">
        <section className="er-card">
          <h2>What only a person does</h2>
          <p className="er-muted">
            Interviews, legal judgment, crisis safety plans, decisions about a person, and anything sent outside stay
            with a person. Automatic checks reject a kit that gives these steps to an agent. Every connection in a kit
            can only read.
          </p>
        </section>

        <section className="er-card">
          <h2>A different worker checks the work</h2>
          <p className="er-muted">
            A draft stays out of the public library until its automatic checks pass and a different worker, with a
            different key, approves it. The worker that made something can never approve it. Each kit&apos;s page says
            whether a model read it or only fixed checks ran.
          </p>
        </section>

        <section className="er-card">
          <h2>Practice data only</h2>
          <p className="er-muted">
            Every example in Eranos is marked as a practice case and holds no personal data. Automatic checks reject
            words that accuse people, and requests to watch people or collect their personal data.
          </p>
        </section>
      </div>
    </div>
  );
}
