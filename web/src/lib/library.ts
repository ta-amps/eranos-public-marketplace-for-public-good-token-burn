import { readableSummary, readableTitle } from "./reportWords";
import { getJson } from "./api";
import type { NounList } from "./nouns";
import type { ExampleSolution } from "./status/example";
import type { CatalogResponse } from "./types";

/**
 * The shared library: what volunteers' agents made and a different volunteer approved. Task objects are the
 * catalog's reviewed kits and the delivered reports (`eranos.solutions`); each kit's task is running it with the
 * nonprofit's own agent. Proposal-only packs are not in it: a proposal is not reviewed work.
 */
export interface LibraryItem {
  id: string;
  kind: "kit" | "report";
  title: string;
  /** Who it was made for, in the record's own words. */
  forWho: string;
  summary: string;
  reviewer?: string;
  href: string;
  /** True when the record says a different volunteer checked it (the catalog's two-step review, or a report's check). */
  checked: boolean;
  /** True when the catalog or the record marks it as an example the team made to show the format. */
  example: boolean;
  /** The words a search matches. */
  words: Set<string>;
}

const COMMON = new Set(
  "about after also because before being between both could does each every from have help into just like make many more most must need needs only other over please same should some such than that their them then there these they this those through very want what when where which while will with work would your agent agents build give find list".split(
    " ",
  ),
);

/** The words of a text that carry meaning: four letters or more, not common, plurals folded (as `match_track`). */
export function meaningWords(text: string): Set<string> {
  const out = new Set<string>();
  for (const word of text.toLowerCase().match(/[a-z]{4,}/g) ?? []) {
    if (COMMON.has(word)) continue;
    out.add(word.length > 4 && word.endsWith("s") ? word.slice(0, -1) : word);
  }
  return out;
}

/** Both public sources, the catalog API and the delivered reports; it fails only when neither can be read. */
export async function loadLibrary(): Promise<LibraryItem[]> {
  const [catalogRead, solutionsRead] = await Promise.allSettled([
    getJson<CatalogResponse>("/api/catalog?view=page"),
    getJson<NounList<ExampleSolution>>("/api/nouns/eranos.solutions"),
  ]);
  if (catalogRead.status === "rejected" && solutionsRead.status === "rejected") throw new Error("the library can't be read");
  const catalog = catalogRead.status === "fulfilled" ? catalogRead.value : ({ kits: [] } as unknown as CatalogResponse);
  const solutions = solutionsRead.status === "fulfilled" ? solutionsRead.value : ({ records: [] } as unknown as NounList<ExampleSolution>);
  const kits: LibraryItem[] = catalog.kits.map((entry) => ({
    id: entry.kit.kit_id,
    kind: "kit",
    title: entry.kit.title,
    forWho: entry.kit.target_org,
    summary: entry.kit.summary,
    reviewer: entry.reviewed_by,
    href: `/catalog/${entry.kit.kit_id}`,
    checked: Boolean(catalog.two_step_verified && entry.reviewed_by),
    example: Boolean(catalog.is_example),
    words: meaningWords(`${entry.kit.title} ${entry.kit.summary} ${entry.kit.target_org}`),
  }));
  // Only delivered reports a card can show and link: a record of another shape (no report, title or request of its
  // own to open) is skipped, never a crash or a dead link. The record itself stays as stored.
  const reports: LibraryItem[] = (solutions.records ?? []).filter((record) => record?.value?.report?.report_id && record.value.report.title && record.value.request_id).map((record) => {
    const report = record.value.report;
    return {
      id: report.report_id,
      kind: "report",
      title: readableTitle(report.title, report.question),
      forWho: "",
      summary: readableSummary(Array.isArray(report.summary) ? report.summary.join(" ") : (report.summary ?? "")),
      href: `/requests/${encodeURIComponent(record.value.request_id)}/result`,
      checked: Boolean(record.value.review_task_id || record.value.review_receipt),
      example: Boolean(record.value.is_example),
      words: meaningWords(`${report.title} ${report.question ?? ""} ${Array.isArray(report.summary) ? report.summary.join(" ") : (report.summary ?? "")}`),
    };
  });
  return [...reports, ...kits];
}

/** Library items that share at least `least` meaning words with the text, best first. */
export function searchLibrary(items: LibraryItem[], text: string, least = 3): LibraryItem[] {
  const wanted = meaningWords(text);
  return items
    .map((item) => ({ item, score: [...wanted].filter((word) => item.words.has(word)).length }))
    .filter((hit) => hit.score >= least)
    .sort((a, b) => b.score - a.score || a.item.title.localeCompare(b.item.title))
    .map((hit) => hit.item);
}
