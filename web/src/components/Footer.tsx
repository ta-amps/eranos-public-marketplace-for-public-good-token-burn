import type { ShellNoun, SiteNoun } from "../lib/nouns";
import { AppLink } from "../router";

/** One line about the two surfaces, the links agents and people look for, and what the site loads and keeps. */
export function Footer({ shell, site }: { shell: ShellNoun | null; site: SiteNoun | null }) {
  return (
    <footer className="er-footer">
      <div className="er-footer-inner">
        {shell && (
          <div className="er-footer-row">
            <p>{shell.footer.line}</p>
            <nav className="er-footer-links" aria-label={shell.footer.links_label}>
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
        )}
        {site && (
          <p className="er-footer-privacy" data-testid="privacy-line">
            {site.privacy}
          </p>
        )}
        {shell && (
          <p className="er-footer-privacy" data-testid="storage-line">
            {shell.footer.storage}
          </p>
        )}
      </div>
    </footer>
  );
}
