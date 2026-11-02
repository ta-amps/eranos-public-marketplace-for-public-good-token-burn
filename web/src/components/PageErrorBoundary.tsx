import { Component, type ErrorInfo, type ReactNode } from "react";

import type { ShellNoun } from "../lib/nouns";

interface Props {
  words: ShellNoun["page_error"] | undefined;
  children: ReactNode;
}

interface State {
  failed: boolean;
}

/**
 * A page that throws while it draws (page text or a record of an unexpected shape) shows a readable message with a
 * way back, instead of a blank page. The app keys it by path, so the next page starts clean. Its words are the
 * `shell` noun's `page_error`.
 */
export class PageErrorBoundary extends Component<Props, State> {
  override state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // Kept in the console for whoever debugs it; the page itself never shows the error text.
    console.warn("page error", error.message, info.componentStack?.split("\n")[1]?.trim() ?? "");
  }

  override render(): ReactNode {
    if (!this.state.failed) return this.props.children;
    const words = this.props.words;
    return (
      <section className="er-container er-page-error" role="alert" data-testid="page-error">
        <h1>{words?.title ?? ""}</h1>
        <p>{words?.body ?? ""}</p>
        <p className="er-page-error-actions">
          <button type="button" className="er-btn-primary" onClick={() => window.location.reload()}>
            {words?.reload ?? "↻"}
          </button>
          <a className="er-btn-secondary" href="/">
            {words?.home ?? "/"}
          </a>
        </p>
      </section>
    );
  }
}
