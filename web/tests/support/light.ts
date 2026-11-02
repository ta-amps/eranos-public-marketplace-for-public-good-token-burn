/**
 * The light check's detector (MUST-FOLLOW rule 13), run inside the page: every element larger than 5% of the
 * viewport whose own background is dark (relative luminance under 0.25), inside links and buttons too. Ink is allowed
 * for text, primary buttons and the logo only: those (and the skip link, a button while focused) are not panels.
 */
export function darkPanels(): string[] {
  const viewport = window.innerWidth * window.innerHeight;
  const channel = (c: number) => {
    const v = c / 255;
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  const out: string[] = [];
  for (const el of document.querySelectorAll("body, body *")) {
    if (el.closest(".er-btn-primary, svg, .er-skip-link")) continue;
    const box = el.getBoundingClientRect();
    if (box.width * box.height < viewport * 0.05) continue;
    const bg = getComputedStyle(el).backgroundColor;
    const m = /rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)/.exec(bg);
    if (!m || (m[4] !== undefined && Number(m[4]) < 0.5)) continue;
    const lum = 0.2126 * channel(Number(m[1])) + 0.7152 * channel(Number(m[2])) + 0.0722 * channel(Number(m[3]));
    if (lum < 0.25) out.push(`${el.tagName.toLowerCase()}.${(el.getAttribute("class") ?? "").split(" ")[0]} ${bg}`);
  }
  return out;
}
