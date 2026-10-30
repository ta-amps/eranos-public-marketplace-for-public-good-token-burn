import { AppLink } from "../router";

export function NotFound({ path }: { path: string }) {
  return (
    <section className="er-card">
      <h1>Page not found</h1>
      <p className="er-muted">
        No Eranos page matches <code>{path}</code>.
      </p>
      <p>
        <AppLink to="/">Go to the home page</AppLink>
      </p>
    </section>
  );
}
