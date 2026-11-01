/*
 * <ta-agent-banner>: the one thin line above a site's header that says an AI agent can use the site, with a
 * Copy button and a "How" toggle that opens a panel under the line (it pushes the page down; it never overlays).
 * One file, no framework, no network calls of its own unless `src` asks for one: Eranos and Agora include the
 * same file. It follows the AgentBanner and BannerSpec boards of October 31, 2026.
 *
 * Every word comes from the agent-banner noun, given one of two ways:
 *   <ta-agent-banner><script type="application/json">{ ...the noun... }</script> fallback markup </ta-agent-banner>
 *   <ta-agent-banner src="/api/nouns/eranos.instructions/agent-banner" fallback-src="/snapshot/..."></ta-agent-banner>
 * The fallback markup (light DOM) stays visible until the noun loads, and is all a reader without scripts sees.
 *
 * Noun fields (the Eranos noun's older fields still work: `line`, `brief`, `other_title`, `links`):
 *   label                 the region's accessible name
 *   lead_strong, lead     "Have an AI agent?" and the sentence after it; lead_short on narrow screens
 *   chip                  the short "Read …/llms.txt" chip (hidden on narrow screens)
 *   copy_text             exactly what Copy puts on the clipboard (falls back to `brief`)
 *   copy, copy_short, copied, copied_status, copy_failed, more, less
 *   panel_title, panel_note, panel_line, can_title, can[], rules_title, rules[], links[{label, href}]
 * Attributes: src, fallback-src, base (where relative links point; the page's origin by default).
 * Theme: the page may set --agent-banner-bg, --agent-banner-ink, --agent-banner-muted, --agent-banner-raised,
 * --agent-banner-line, --agent-banner-link and --agent-banner-focus on the element.
 * Honesty: when copying fails, the button says so and the line is selected, instead of claiming success.
 */
(() => {
  if (typeof customElements === "undefined" || customElements.get("ta-agent-banner")) return;

  const CSS = `
:host { display: block; position: relative; z-index: 40; font-family: "IBM Plex Sans", "Segoe UI", system-ui, sans-serif;
  --bg: var(--agent-banner-bg, #11161F); --ink: var(--agent-banner-ink, #F5F2EA); --muted: var(--agent-banner-muted, #C8D0DC);
  --raised: var(--agent-banner-raised, #222732); --line: var(--agent-banner-line, #2B313D); --edge: var(--agent-banner-edge, #3B4252);
  --link: var(--agent-banner-link, #9DBBF0); --focus: var(--agent-banner-focus, #F0884F); --can: #6E9BE8; --rule: #7FC29B;
  background: var(--bg); color: var(--ink); border-bottom: 1px solid var(--line); }
:host([hidden]) { display: none; }
* { box-sizing: border-box; }
section { margin: 0; }
.bar { max-width: 1248px; margin: 0 auto; padding: 0 24px; min-height: 36px; display: flex; align-items: center; gap: 12px;
  font-size: 14px; line-height: 20px; }
.icon { flex: none; width: 18px; height: 18px; }
.lead { flex: 0 1 auto; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.lead b { font-weight: 600; }
.short { display: none; }
.chip { font-family: "JetBrains Mono", ui-monospace, Menlo, Consolas, monospace; font-size: 13px; font-weight: 500;
  color: var(--muted); background: var(--raised); padding: 3px 8px; border-radius: 6px; white-space: nowrap; }
.space { flex: 1 1 0; }
button { font: inherit; font-weight: 600; color: var(--ink); cursor: pointer; white-space: nowrap; border-radius: 8px;
  min-height: 28px; padding: 0 10px; display: inline-flex; align-items: center; gap: 6px; }
.copy { background: transparent; border: 1px solid var(--edge); }
.copy:hover { border-color: var(--muted); }
.copy svg { width: 14px; height: 14px; flex: none; }
.toggle { background: var(--raised); border: 1px solid transparent; }
.toggle:hover { border-color: var(--edge); }
button:focus-visible, a:focus-visible, .line:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
.panel { border-top: 1px solid var(--line); }
.panel[hidden] { display: none; }
.grid { max-width: 1248px; margin: 0 auto; padding: 18px 24px 22px; display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr) minmax(0, 1fr); gap: 28px; }
.col { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.col + .col { gap: 8px; }
.title { margin: 0; font-size: 16px; line-height: 22px; font-weight: 600; }
.line { display: block; margin: 0; font-family: "JetBrains Mono", ui-monospace, Menlo, Consolas, monospace; font-size: 14px;
  line-height: 22px; color: var(--ink); background: var(--raised); padding: 12px 14px; border-radius: 10px;
  white-space: pre-wrap; word-break: break-word; user-select: all; -webkit-user-select: all; }
.row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.big { font-size: 15px; min-height: 40px; padding: 0 16px; border-radius: 10px; border: 0; background: var(--ink); color: var(--bg); }
.big:hover { opacity: 0.92; }
.note, .item { margin: 0; font-size: 14px; line-height: 20px; color: var(--muted); }
ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.item { display: flex; gap: 8px; }
.mark { flex: none; }
.can .mark { color: var(--can); }
.rules .mark { color: var(--rule); }
.links { display: flex; gap: 8px 16px; flex-wrap: wrap; margin-top: 4px; font-size: 14px; }
a { color: var(--link); text-decoration: underline; text-underline-offset: 0.18em; }
.sr { position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
@media (max-width: 719.98px) {
  .bar { min-height: 40px; padding: 0 16px; gap: 8px; }
  .long, .chip { display: none; }
  .short { display: inline; }
  .grid { grid-template-columns: minmax(0, 1fr); padding: 16px 16px 20px; gap: 20px; }
}
@media (prefers-reduced-motion: no-preference) { button { transition: border-color 120ms ease-out, opacity 120ms ease-out; } }
@media (forced-colors: active) { :host { border-bottom: 1px solid CanvasText; } .chip, .line, .toggle { border: 1px solid CanvasText; } }
`;

  const NS = "http://www.w3.org/2000/svg";

  function icon(kind) {
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    if (kind === "agent") {
      // A small robot head in a circle, drawn for the AgentBanner board.
      svg.setAttribute("viewBox", "0 0 40 40");
      svg.setAttribute("class", "icon");
      svg.innerHTML = '<circle cx="20" cy="20" r="17" fill="none" stroke="currentColor" stroke-width="2.6"></circle>'
        + '<path d="M20 12v-3h-3" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"></path>'
        + '<rect x="12" y="14" width="16" height="12" rx="3" fill="none" stroke="currentColor" stroke-width="2.6"></rect>'
        + '<path d="M17 19v2M23 19v2" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"></path>';
    } else {
      svg.setAttribute("viewBox", "0 0 24 24");
      svg.innerHTML = '<rect x="9" y="9" width="12" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="2"></rect>'
        + '<path d="M5 15V5a2 2 0 0 1 2-2h10" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"></path>';
    }
    return svg;
  }

  function el(tag, props, children) {
    const node = document.createElement(tag);
    for (const [name, value] of Object.entries(props || {})) {
      if (value === undefined || value === null || value === false) continue;
      if (name === "text") node.textContent = String(value);
      else if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
      else node.setAttribute(name, value === true ? "" : String(value));
    }
    for (const child of children || []) if (child) node.append(child);
    return node;
  }

  function words(raw) {
    const value = raw && typeof raw === "object" && "value" in raw && !("copy" in raw) ? raw.value : raw;
    if (!value || typeof value !== "object") throw new Error("not an agent banner noun");
    const copyText = typeof value.copy_text === "string" ? value.copy_text : value.brief;
    if (typeof copyText !== "string" || !copyText.trim()) throw new Error("the agent banner noun has nothing to copy");
    return Object.assign({}, value, { copy_text: copyText });
  }

  async function fetchNoun(url) {
    const response = await fetch(url, { headers: { accept: "application/json" }, credentials: "omit" });
    const type = response.headers.get("content-type") || "";
    if (!response.ok || !type.includes("json")) throw new Error(url + " answered " + response.status);
    return words(await response.json());
  }

  let count = 0;

  class AgentBanner extends HTMLElement {
    constructor() {
      super();
      this.root = this.attachShadow({ mode: "open" });
      this.noun = null;
      this.open = false;
      this.timer = 0;
      this.onKey = (event) => {
        if (event.key !== "Escape" || !this.open) return;
        const inside = event.composedPath().includes(this);
        this.setOpen(false, inside);
        if (inside) event.stopPropagation();
      };
    }

    connectedCallback() {
      document.addEventListener("keydown", this.onKey);
      if (!this.started) {
        this.started = true;
        this.load();
      }
    }

    disconnectedCallback() {
      document.removeEventListener("keydown", this.onKey);
      clearTimeout(this.timer);
    }

    async load() {
      const inline = this.querySelector('script[type="application/json"]');
      if (inline) {
        try {
          this.render(words(JSON.parse(inline.textContent)));
          return;
        } catch (error) {
          // fall through to src, then leave the fallback markup in place
        }
      }
      for (const src of [this.getAttribute("src"), this.getAttribute("fallback-src")].filter(Boolean)) {
        try {
          this.render(await fetchNoun(src));
          return;
        } catch (error) {
          // try the next source
        }
      }
    }

    href(value) {
      // Only web links: a noun fetched from another site must not be able to run script through a link (review N2).
      try {
        const url = new URL(value || "/", this.getAttribute("base") || window.location.origin);
        return url.protocol === "https:" || url.protocol === "http:" ? url.href : "#";
      } catch (error) {
        return "#";
      }
    }

    label(button, long, short) {
      button.querySelector(".long").textContent = long;
      button.querySelector(".short").textContent = short;
    }

    async copy(fromPanel) {
      const w = this.noun;
      clearTimeout(this.timer);
      let ok = false;
      try {
        if (!navigator.clipboard || !window.isSecureContext) throw new Error("no clipboard");
        await navigator.clipboard.writeText(w.copy_text);
        ok = true;
      } catch (error) {
        ok = false;
      }
      const message = ok ? (w.copied || "Copied") : (w.copy_failed || "Select the line to copy");
      for (const button of [this.copyButton, this.bigButton]) {
        this.label(button, message, message);
        button.dataset.state = ok ? "copied" : "failed";
      }
      this.status.textContent = ok ? (w.copied_status || message) : message;
      if (!ok) {
        this.setOpen(true, false);
        const selection = window.getSelection && window.getSelection();
        if (selection) {
          try {
            selection.selectAllChildren(this.lineBox);
          } catch (error) {
            // the line stays visible to select by hand
          }
        }
        this.lineBox.focus();
      } else if (fromPanel) {
        this.bigButton.focus();
      }
      this.timer = setTimeout(() => this.resetCopy(), 2400);
    }

    resetCopy() {
      const w = this.noun;
      this.label(this.copyButton, w.copy || "Copy for your agent", w.copy_short || "Copy");
      this.label(this.bigButton, w.copy || "Copy for your agent", w.copy_short || "Copy");
      delete this.copyButton.dataset.state;
      delete this.bigButton.dataset.state;
    }

    setOpen(open, returnFocus) {
      const w = this.noun;
      this.open = open;
      this.panel.hidden = !open;
      this.toggle.setAttribute("aria-expanded", String(open));
      this.label(this.toggle, (open ? (w.less || "Hide") + " ▴" : (w.more || "How") + " ▾"), open ? "▴" : "▾");
      this.toggle.setAttribute("aria-label", open ? (w.less || "Hide") : (w.more || "How"));
      this.dataset.open = String(open);
      if (!open && returnFocus) this.toggle.focus();
    }

    list(items, cls, mark) {
      return el("ul", { class: cls }, (items || []).map((item) =>
        el("li", { class: "item" }, [el("span", { class: "mark", "aria-hidden": "true", text: mark }), el("span", { text: item })])));
    }

    render(w) {
      this.noun = w;
      const id = "ta-agent-banner-panel-" + (++count);
      const both = (long, short) => [el("span", { class: "long", text: long }), el("span", { class: "short", text: short })];
      const lead = el("span", { class: "lead" }, [
        w.lead_strong ? el("b", { text: w.lead_strong }) : null,
        w.lead_strong ? document.createTextNode(" ") : null,
        el("span", { class: "long", text: w.lead || w.line || "" }),
        el("span", { class: "short", text: w.lead_short || w.lead || w.line || "" }),
      ]);
      this.copyButton = el("button", { type: "button", class: "copy", onclick: () => this.copy(false) },
        [icon("copy")].concat(both(w.copy || "Copy for your agent", w.copy_short || "Copy")));
      this.toggle = el("button", { type: "button", class: "toggle", "aria-expanded": "false", "aria-controls": id,
        onclick: () => this.setOpen(!this.open, false) }, both((w.more || "How") + " ▾", "▾"));
      this.status = el("span", { class: "sr", role: "status", "aria-live": "polite" });
      const bar = el("div", { class: "bar" }, [
        icon("agent"), lead, w.chip ? el("code", { class: "chip", text: w.chip }) : null,
        el("span", { class: "space" }), this.copyButton, this.toggle, this.status,
      ]);

      this.lineBox = el("code", { class: "line", tabindex: "0", text: w.copy_text });
      this.bigButton = el("button", { type: "button", class: "big", onclick: () => this.copy(true) },
        both(w.copy || "Copy for your agent", w.copy_short || "Copy"));
      const first = el("div", { class: "col" }, [
        el("p", { class: "title", text: w.panel_title || "Paste this into your agent" }),
        this.lineBox,
        el("div", { class: "row" }, [this.bigButton, w.panel_note ? el("span", { class: "note", text: w.panel_note }) : null]),
        w.panel_line ? el("p", { class: "note", text: w.panel_line }) : null,
      ]);
      const columns = [first];
      if (Array.isArray(w.can) && w.can.length) {
        columns.push(el("div", { class: "col" }, [el("p", { class: "title", text: w.can_title || "" }), this.list(w.can, "can", "→")]));
      }
      const links = Array.isArray(w.links) ? w.links : [];
      const linkRow = links.length
        ? el("p", { class: "links" }, links.map((item) => el("a", { href: this.href(item.href || item.to), text: item.label })))
        : null;
      if (Array.isArray(w.rules) && w.rules.length) {
        columns.push(el("div", { class: "col" }, [el("p", { class: "title", text: w.rules_title || "" }), this.list(w.rules, "rules", "✓"), linkRow]));
      } else if (linkRow) {
        columns.push(el("nav", { class: "col", "aria-label": w.other_title || "Links" }, [el("p", { class: "title", text: w.other_title || "" }), linkRow]));
      }
      this.panel = el("div", { class: "panel", id, hidden: true }, [el("div", { class: "grid" }, columns)]);

      const section = el("section", { "aria-label": w.label || "Use this site with your AI agent" }, [bar, this.panel]);
      if ("adoptedStyleSheets" in Document.prototype && "replaceSync" in CSSStyleSheet.prototype) {
        const sheet = new CSSStyleSheet();
        sheet.replaceSync(CSS);
        this.root.adoptedStyleSheets = [sheet];
        this.root.replaceChildren(section);
      } else {
        this.root.replaceChildren(el("style", { text: CSS }), section);
      }
      this.setOpen(false, false); // names the toggle from the start, even where it shows only the glyph (review N3)
      this.dataset.ready = "true";
      this.dispatchEvent(new CustomEvent("ta-agent-banner-ready", { bubbles: true }));
    }
  }

  customElements.define("ta-agent-banner", AgentBanner);
})();
