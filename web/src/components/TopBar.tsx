import { useEffect, useRef, useState } from "react";

import type { NounLink, ShellNoun } from "../lib/nouns";
import { AppLink, type RouteMatch } from "../router";
import { Icon } from "./Icon";
import { Mark } from "./Mark";

function activeMatch(route: RouteMatch): string {
  if (route.name === "kit") return "catalog";
  return route.name;
}

function NavLink({ link, active, note, onNavigate }: { link: NounLink; active: string; note: string; onNavigate?: () => void }) {
  if (link.to) {
    return (
      <AppLink to={link.to} aria-current={link.match === active ? "page" : undefined} onClick={onNavigate}>
        {link.label}
      </AppLink>
    );
  }
  return (
    <a href={link.href} onClick={onNavigate}>
      {link.label}
      {link.external && (
        <>
          <Icon name="arrow-up-right" size={16} className="er-nav-external" />
          <span className="er-visually-hidden"> ({note})</span>
        </>
      )}
    </a>
  );
}

/**
 * The header: the tile mark and wordmark, then the navigation in one row. Under 600 px the navigation moves into
 * a menu sheet behind a "Menu" button, so the header never wraps. The sheet is a modal dialog: focus moves to its
 * first link, Escape or Close shuts it and focus returns to the button. Every label is the `shell` noun.
 */
export function TopBar({ route, shell, compact = false }: { route: RouteMatch; shell: ShellNoun | null; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const active = activeMatch(route);

  useEffect(() => {
    const sheet = dialog.current;
    if (!sheet) return;
    if (open && !sheet.open) {
      sheet.showModal();
      sheet.querySelector<HTMLAnchorElement>("a")?.focus();
    } else if (!open && sheet.open) {
      sheet.close();
    }
  }, [open]);

  // A route change from inside the sheet closes it.
  useEffect(() => {
    setOpen(false);
  }, [route]);

  function close() {
    setOpen(false);
    window.requestAnimationFrame(() => button.current?.focus());
  }

  return (
    <header className={compact ? "er-header er-header-compact" : "er-header"}>
      <div className="er-header-inner">
        <AppLink to="/" className="er-brand" aria-current={active === "overview" ? "page" : undefined}>
          <Mark size={compact ? 24 : 28} className="er-brand-logo" />
          <span className="er-wordmark">Eranos</span>
        </AppLink>
        {shell && (
          <>
            <nav className="er-nav" aria-label={shell.nav_label}>
              {shell.nav.map((link) => (
                <NavLink key={link.label} link={link} active={active} note={shell.external_note} />
              ))}
            </nav>
            {shell.yours && (
              <AppLink to={shell.yours.to ?? "/requests"} className="er-yours-link" aria-current={active === "yours" ? "page" : undefined}>
                {shell.yours.label}
              </AppLink>
            )}
            <button
              ref={button}
              type="button"
              className="er-menu-button"
              aria-expanded={open}
              aria-controls="er-menu-sheet"
              aria-haspopup="dialog"
              onClick={() => setOpen(true)}
            >
              <Icon name="menu" size={18} strokeWidth={2} />
              <span>{shell.menu.button}</span>
            </button>
            <dialog
              id="er-menu-sheet"
              ref={dialog}
              className="er-menu-sheet"
              aria-label={shell.menu.sheet_label}
              onCancel={(event) => {
                event.preventDefault();
                close();
              }}
              onClick={(event) => {
                if (event.target === dialog.current) close();
              }}
            >
              <div className="er-menu-panel">
                <span className="er-menu-handle" aria-hidden="true" />
                <nav className="er-menu-nav" aria-label={shell.nav_label}>
                  {shell.nav.map((link) => (
                    <NavLink key={link.label} link={link} active={active} note={shell.external_note} onNavigate={() => setOpen(false)} />
                  ))}
                  {shell.yours && <NavLink link={{ ...shell.yours, match: "yours" }} active={active} note={shell.external_note} onNavigate={() => setOpen(false)} />}
                </nav>
                <button type="button" className="er-btn-secondary er-menu-close" onClick={close}>
                  {shell.menu.close}
                </button>
              </div>
            </dialog>
          </>
        )}
      </div>
    </header>
  );
}
