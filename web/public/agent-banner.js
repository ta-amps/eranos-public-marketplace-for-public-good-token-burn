/*
 * <ta-agent-banner>: one thin line above a site's header, "Use this site from your AI agent", with a Copy button
 * and a More toggle. More opens a full-width panel under the line with the instructions to paste and the other
 * ways to connect. One file, no framework: Eranos and Agora include the same file.
 *
 *   <script src="https://eranos.ta-amps.workers.dev/agent-banner.js" defer></script>
 *   <ta-agent-banner src="https://eranos.ta-amps.workers.dev/api/nouns/eranos.instructions/agent-banner"
 *                    base="https://eranos.ta-amps.workers.dev"></ta-agent-banner>
 *
 * Attributes:
 *   src           the `eranos.instructions/agent-banner` noun: its words, links and the brief to copy.
 *   fallback-src  read when `src` does not answer JSON, such as the noun exported with an offline build.
 *   base          where the noun's relative links point; the page's own origin when left out.
 * Every word comes from the noun, so nothing shows until it loads. Colours follow the page's Paper & Ink tokens
 * when it has them. The toggle reports aria-expanded, focus moves into the panel, and Escape closes it and
 * returns focus. Styles are a constructed stylesheet, so a strict style-src policy needs no exception.
 */
(() => {
  if (customElements.get("ta-agent-banner")) return;

  const CSS = `
:host { display: block; position: relative; z-index: 60; font-family: var(--font-text, "IBM Plex Sans", system-ui, sans-serif);
  --b-bg: var(--sunken, #EDE8DC); --b-surface: var(--surface, #FFFDF8); --b-text: var(--text, #11161F);
  --b-text-2: var(--text-2, #3B4252); --b-line: var(--line, #E2DCCF); --b-line-strong: var(--line-strong, #8A8476);
  --b-action: var(--action, #11161F); --b-action-text: var(--action-text, #F5F2EA); --b-link: var(--link, #24519B);
  --b-focus: var(--focus, #2A5DB0); --b-mono: var(--font-mono, "JetBrains Mono", ui-monospace, Menlo, monospace); }
@media (prefers-color-scheme: dark) {
  :host { --b-bg: var(--sunken, #0B0F16); --b-surface: var(--surface, #1B2230); --b-text: var(--text, #F5F2EA);
    --b-text-2: var(--text-2, #C8D0DC); --b-line: var(--line, #2C3443); --b-line-strong: var(--line-strong, #6B7487);
    --b-action: var(--action, #F5F2EA); --b-action-text: var(--action-text, #11161F); --b-link: var(--link, #8DB7F4);
    --b-focus: var(--focus, #8DB7F4); }
}
:host([hidden]) { display: none; }
* { box-sizing: border-box; }
.bar { display: flex; align-items: center; justify-content: center; gap: 12px; min-height: 36px; padding: 2px 16px;
  background: var(--b-bg); color: var(--b-text-2); border-bottom: 1px solid var(--b-line); font-size: 14px; line-height: 20px; }
.line { display: inline-flex; align-items: center; gap: 8px; min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.line span { overflow: hidden; text-overflow: ellipsis; }
.line svg { flex-shrink: 0; }
.actions { display: inline-flex; align-items: center; gap: 6px; flex-shrink: 0; }
button { font: inherit; font-size: 14px; font-weight: 600; line-height: 1; cursor: pointer; border-radius: 8px; min-height: 30px; padding: 0 12px; }
.copy { background: var(--b-action); color: var(--b-action-text); border: 1.5px solid var(--b-action); }
.more { background: transparent; color: var(--b-text); border: 1.5px solid var(--b-line-strong); display: inline-flex; align-items: center; gap: 6px; }
.caret { display: inline-block; transition: transform 120ms cubic-bezier(0.2, 0, 0, 1); }
.more[aria-expanded="true"] .caret { transform: rotate(180deg); }
button:focus-visible, a:focus-visible, textarea:focus-visible, .panel:focus-visible { outline: 3px solid var(--b-focus); outline-offset: 2px; }
.short { display: none; }
.panel { position: absolute; left: 0; right: 0; top: 100%; background: var(--b-surface); color: var(--b-text);
  border-bottom: 1px solid var(--b-line); box-shadow: 0 10px 30px rgb(17 22 31 / 0.12); }
.panel[hidden] { display: none; }
.inner { max-width: 1200px; margin: 0 auto; padding: 20px 32px 24px; display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); gap: 32px; }
.title { margin: 0 0 6px; font-weight: 600; font-size: 16px; color: var(--b-text); }
.note { margin: 0 0 10px; font-size: 14px; color: var(--b-text-2); line-height: 1.45; }
textarea { width: 100%; min-height: 150px; resize: vertical; padding: 12px 14px; border-radius: 12px; border: 1.5px solid var(--b-line-strong);
  background: var(--b-bg); color: var(--b-text); font: 500 13px/1.6 var(--b-mono); }
.row { display: flex; align-items: center; gap: 12px; margin-top: 10px; flex-wrap: wrap; }
.row .copy { min-height: 40px; padding: 0 16px; font-size: 15px; }
.status { font-size: 14px; color: var(--b-text-2); }
ul { margin: 0; padding: 0; list-style: none; display: grid; gap: 8px; }
a { color: var(--b-link); font-size: 15px; text-underline-offset: 0.18em; }
.sr { position: absolute; width: 1px; height: 1px; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
@media (max-width: 599px) {
  .bar { justify-content: space-between; padding: 2px 12px; gap: 8px; }
  .long { display: none; } .short { display: inline; }
  .inner { grid-template-columns: minmax(0, 1fr); padding: 16px; gap: 20px; }
}
@media (prefers-reduced-motion: reduce) { .caret { transition: none; } }
`;

  const ICON =
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><rect width="14" height="14" x="8" y="8" rx="2"></rect><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path></svg>';

  let sheet = null;
  function styles(root) {
    if ("adoptedStyleSheets" in Document.prototype && "replaceSync" in CSSStyleSheet.prototype) {
      if (!sheet) {
        sheet = new CSSStyleSheet();
        sheet.replaceSync(CSS);
      }
      root.adoptedStyleSheets = [sheet];
    }
  }

  function el(tag, props = {}, children = []) {
    const node = document.createElement(tag);
    for (const [name, value] of Object.entries(props)) {
      if (value === undefined || value === null || value === false) continue;
      if (name === "text") node.textContent = value;
      else if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
      else node.setAttribute(name, value === true ? "" : String(value));
    }
    for (const child of children) node.append(child);
    return node;
  }

  async function readNoun(url) {
    const response = await fetch(url, { headers: { accept: "application/json" }, credentials: "omit" });
    const type = response.headers.get("content-type") || "";
    if (!response.ok || !type.includes("json")) throw new Error(`${url} answered ${response.status}`);
    const body = await response.json();
    const value = body && typeof body === "object" && "value" in body ? body.value : body;
    if (!value || typeof value.brief !== "string") throw new Error(`${url} is not the agent banner noun`);
    return value;
  }

  let count = 0;

  class AgentBanner extends HTMLElement {
    constructor() {
      super();
      this.root = this.attachShadow({ mode: "open" });
      styles(this.root);
      this.words = null;
      this.open = false;
      this.onKey = (event) => {
        if (event.key === "Escape" && this.open) {
          event.preventDefault();
          this.setOpen(false, true);
        }
      };
      this.onPointer = (event) => {
        if (this.open && !event.composedPath().includes(this)) this.setOpen(false, false);
      };
    }

    connectedCallback() {
      document.addEventListener("keydown", this.onKey);
      document.addEventListener("pointerdown", this.onPointer);
      if (!this.loading) this.load();
    }

    disconnectedCallback() {
      document.removeEventListener("keydown", this.onKey);
      document.removeEventListener("pointerdown", this.onPointer);
    }

    async load() {
      this.loading = true;
      const sources = [this.getAttribute("src"), this.getAttribute("fallback-src")].filter(Boolean);
      for (const src of sources) {
        try {
          this.words = await readNoun(src);
          this.render();
          return;
        } catch {
          // try the next source
        }
      }
      this.loading = false;
    }

    link(href) {
      try {
        return new URL(href, this.getAttribute("base") || window.location.origin).href;
      } catch {
        return href;
      }
    }

    async copy() {
      const words = this.words;
      try {
        await navigator.clipboard.writeText(words.brief);
        this.say(words.copied);
      } catch {
        this.setOpen(true, false);
        this.say(words.copy_failed);
        this.text.focus();
        this.text.select();
      }
    }

    say(message) {
      this.status.textContent = message;
      this.visibleStatus.textContent = message;
    }

    setOpen(open, returnFocus) {
      this.open = open;
      this.toggle.setAttribute("aria-expanded", String(open));
      this.toggleLabel.textContent = open ? this.words.less : this.words.more;
      this.panel.hidden = !open;
      if (open) this.panel.focus();
      else if (returnFocus) this.toggle.focus();
    }

    render() {
      const w = this.words;
      const id = `ta-agent-panel-${++count}`;
      this.status = el("span", { class: "sr", role: "status", "aria-live": "polite" });
      this.visibleStatus = el("span", { class: "status", "aria-hidden": "true" });
      this.toggleLabel = el("span", { text: w.more });
      this.toggle = el("button", { type: "button", class: "more", "aria-expanded": "false", "aria-controls": id, onclick: () => this.setOpen(!this.open, false) }, [
        this.toggleLabel,
        el("span", { class: "caret", "aria-hidden": "true", text: "▾" }),
      ]);
      const line = el("span", { class: "line" });
      line.insertAdjacentHTML("afterbegin", ICON);
      line.append(el("span", { text: w.line }));
      const copyButton = el("button", { type: "button", class: "copy", "aria-label": w.copy, onclick: () => this.copy() }, [
        el("span", { class: "long", text: w.copy }),
        el("span", { class: "short", text: w.copy_short }),
      ]);
      const bar = el("section", { class: "bar", "aria-label": w.label }, [line, el("span", { class: "actions" }, [copyButton, this.toggle]), this.status]);
      const textId = `${id}-brief`;
      this.text = el("textarea", { id: textId, readonly: true, rows: "7" });
      this.text.value = w.brief;
      const links = el(
        "ul",
        {},
        (w.links || []).map((item) => el("li", {}, [el("a", { href: this.link(item.href || item.to || "/"), text: item.label })])),
      );
      this.panel = el("div", { id, class: "panel", hidden: true, tabindex: "-1", role: "region", "aria-label": w.panel_title }, [
        el("div", { class: "inner" }, [
          el("div", {}, [
            el("label", { class: "title", for: textId, text: w.panel_title }),
            el("p", { class: "note", text: w.panel_note }),
            this.text,
            el("div", { class: "row" }, [el("button", { type: "button", class: "copy", onclick: () => this.copy(), text: w.copy }), this.visibleStatus]),
          ]),
          el("nav", { "aria-label": w.other_title }, [el("p", { class: "title", text: w.other_title }), links]),
        ]),
      ]);
      this.root.replaceChildren(bar, this.panel);
      this.dataset.ready = "true";
    }
  }

  customElements.define("ta-agent-banner", AgentBanner);
})();
