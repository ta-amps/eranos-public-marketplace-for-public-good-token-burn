import type { ShellNoun, SiteNoun } from "../lib/nouns";
import { AppLink } from "../router";
import { Mark } from "./Mark";

/**
 * The standard footer (ta-amps.footer/2, MUST-FOLLOW rule 13): the tile mark and the name, ONE row of links in the
 * canonical order (a link to another host is absolute and carries ↗), and one short line: the privacy line. Every
 * word is the `shell` noun's footer. The agent links live in the banner above every page. The beta note sits under
 * the footer, not in it, so the footer keeps its one row and one line.
 */
export function Footer({ shell }: { shell: ShellNoun | null; site: SiteNoun | null }) {
  if (!shell) return <footer className="er-footer er-site-footer" />;
  return (
    <>
      <footer className="er-footer er-site-footer">
      <div className="er-site-footer-row">
        <span className="er-site-footer-name">
          <Mark size={20} />
          <strong>{shell.footer.brand ?? "Eranos"}</strong>
        </span>
        <nav className="er-site-footer-links" aria-label={shell.footer.links_label}>
          {shell.footer.links.map((link) =>
            link.to ? (
              <AppLink key={link.label} to={link.to}>
                {link.label}
              </AppLink>
            ) : (
              <a key={link.label} href={link.href}>
                {link.label}
              </a>
            ),
          )}
        </nav>
      </div>
      <p className="er-site-footer-line" data-testid="footer-line">
        {shell.footer.line}
      </p>
    </footer>
    {shell.footer.beta_note ? (
      <p className="er-site-beta-note" data-testid="beta-note">
        {shell.footer.beta_note}
      </p>
    ) : null}
    </>
  );
}
