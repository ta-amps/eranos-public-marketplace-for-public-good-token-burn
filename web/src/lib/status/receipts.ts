/**
 * Receipts as Tessera writes them. A claim receipt is the SHA-256 of the canonical JSON of
 * `{namespace, task_id, fencing_token, claimed_at}`; Tessera computes it when it grants a lease, and every input
 * is in the `claimed` event a requester key may read, so this page can show it before the plan noun repeats it.
 * `canonicalJson` follows Tessera's own (deploy/cloudflare/cloud_buckets.js): sorted keys, no spaces, and its
 * number format.
 */

const MAX_EXACT = 9007199254740992; // 2^53

function canonicalNumber(value: number): string {
  if (!Number.isFinite(value)) throw new Error("JSON value may not contain NaN or Infinity");
  if (Object.is(value, -0) || value === 0) return "0";
  if (Number.isInteger(value) && Math.abs(value) < MAX_EXACT) return String(value);
  const abs = Math.abs(value);
  if (abs >= 1e-4 && abs < 1e16) return JSON.stringify(value);
  const raw = value.toString();
  const exp = raw.includes("e") || raw.includes("E") ? raw.toLowerCase() : value.toExponential();
  const [mantissa = "", power = ""] = exp.split("e");
  const sign = power.startsWith("-") ? "-" : "+";
  return `${mantissa}e${sign}${power.replace(/^[+-]/, "").padStart(2, "0")}`;
}

function codePointCompare(a: string, b: string): number {
  let ia = 0;
  let ib = 0;
  while (ia < a.length && ib < b.length) {
    const ca = a.codePointAt(ia) ?? 0;
    const cb = b.codePointAt(ib) ?? 0;
    if (ca !== cb) return ca - cb;
    ia += ca > 0xffff ? 2 : 1;
    ib += cb > 0xffff ? 2 : 1;
  }
  return a.length - b.length;
}

export function canonicalJson(value: unknown): string {
  if (value === null || typeof value === "boolean" || typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number") return canonicalNumber(value);
  if (Array.isArray(value)) return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    const keys = Object.keys(record).sort(codePointCompare);
    return `{${keys
      .filter((key) => record[key] !== undefined)
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`)
      .join(",")}}`;
  }
  throw new Error(`unsupported JSON value type: ${typeof value}`);
}

export async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function claimReceipt(namespace: string, taskId: string, fencingToken: number, claimedAt: number): Promise<string> {
  return sha256Hex(canonicalJson({ namespace, task_id: taskId, fencing_token: fencingToken, claimed_at: claimedAt }));
}

/** The first four hex digits, which is how receipts read on screen; the full hash is in the title and data. */
export function shortReceipt(receipt: string): string {
  return /^[0-9a-f]{8,}$/i.test(receipt) ? receipt.slice(0, 4) : receipt;
}

/** A request id is `rq-<principal>-<base36 time>`; people read it as `R-` and its last four characters. */
export function shortRequestId(id: string): string {
  if (id === "example") return "R-EXMP";
  const tail = id.replace(/[^A-Za-z0-9]/g, "").slice(-4).toUpperCase();
  return `R-${tail || "????"}`;
}

/** The shape the request box mints: `rq-r_<32 hex>-<base36>`. */
export const REQUEST_ID_RE = /^rq-r_[0-9a-f]{32}-[0-9a-z]{4,12}$/;
