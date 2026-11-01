import type { ShellNoun, SiteNoun } from "../lib/nouns";
import { AppLink } from "../router";
import { Mark } from "./Mark";

/**
 * SiteFooter (Nov 1): the tile mark and the brand's line, the trust links (Privacy, Terms, Report a problem, then
 * Agora's Status, Accessibility, Source and Models used pages), and what this browser keeps. Every word is the
 * `shell` noun's footer, and the site noun's privacy line closes it.
 */
export function Footer({ shell, site }: { shell: ShellNoun | null; site: SiteNoun | null }) {
  return (
    <footer className="er-footer er-site-footer">
      {shell && (
        <div className="er-site-footer-row">
          <div className="er-site-footer-brand">
            <span className="er-site-footer-name">
              <Mark size={20} />
              <strong>{shell.footer.brand ?? "Eranos"}</strong>
            </span>
            <span className="er-site-footer-line">{shell.footer.line}</span>
          </div>
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
          <p className="er-site-footer-note" data-testid="storage-line">
            {shell.footer.storage}
          </p>
        </div>
      )}
      {site && (
        <p className="er-site-footer-privacy" data-testid="privacy-line">
          {site.privacy}
        </p>
      )}
    </footer>
  );
}
