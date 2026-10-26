// units.mjs — the browser half of the contract's rules.
//
// One asset: GEN in wei (10**18). One clock: Ethereum block heights, which are
// integers and never money. The contract never converts between them either;
// this module only mirrors its arithmetic so the page can show what a release
// would pay before anyone sends a transaction.

export const GEN_DECIMALS = 18;
export const STALE_BLOCKS = 60;

/** GEN text -> wei. */
export function toWei(text) {
  const s = String(text).trim();
  const m = /^(\d*)(?:\.(\d*))?$/.exec(s);
  if (!m || (m[1] === "" && (m[2] === undefined || m[2] === ""))) {
    throw new Error("Not a non-negative GEN amount: " + text);
  }
  const whole = m[1] || "0";
  const frac = m[2] || "";
  if (frac.length > GEN_DECIMALS) throw new Error("At most 18 decimals: " + text);
  return BigInt(whole) * 10n ** 18n + BigInt((frac + "0".repeat(18)).slice(0, 18));
}

/** wei -> GEN text. */
export function formatGen(wei, dp = 6) {
  const v = BigInt(wei);
  const whole = v / 10n ** 18n;
  const frac = (v % 10n ** 18n).toString().padStart(18, "0").slice(0, Math.max(0, dp)).replace(/0+$/, "");
  return frac ? whole + "." + frac : whole.toString();
}

/** A block height, as the page will send it. '' when it is not one. */
export function normHeight(text) {
  const s = String(text).trim();
  if (!/^\d+$/.test(s)) return "";
  const n = BigInt(s);
  if (n <= 0n || n > 10n ** 12n) return "";
  return s;
}

/** The part of `total` that has vested up to `height`. */
export function vested(total, start, end, height) {
  const t = BigInt(total);
  const s = BigInt(start);
  const e = BigInt(end);
  const h = BigInt(height);
  if (e <= s) return 0n;
  if (h <= s) return 0n;
  if (h >= e) return t;
  return (t * (h - s)) / (e - s);
}

/**
 * What the contract would do at `height`: release this much to the recipient,
 * and leave this much behind. Mirrors `quote`.
 */
export function quote(vest, height) {
  const h = BigInt(height);
  const total = BigInt(vest.total);
  const v = vested(total, vest.start_block, vest.end_block, h);
  const owed = v - BigInt(vest.released || 0);
  return {
    vested: v,
    wouldRelease: owed > 0n ? owed : 0n,
    wouldReturn: total - v > 0n ? total - v : 0n,
  };
}

/**
 * Two provider tips -> the range the contract will accept. Returns the
 * laggard (which caps every release), the fresher one, and whether both
 * answered at all.
 */
export function tipRange(a, b) {
  const x = Number(a) || 0;
  const y = Number(b) || 0;
  if (x <= 0 || y <= 0) return { ok: false, laggard: 0, fresher: 0, apart: 0 };
  return { ok: true, laggard: Math.min(x, y), fresher: Math.max(x, y), apart: Math.abs(x - y) };
}

/** Is `height` fresh on both providers? Mirrors the contract's rule. */
export function isFresh(height, laggard) {
  const h = Number(height);
  if (!Number.isInteger(h) || h <= 0) return false;
  return h <= laggard && h + STALE_BLOCKS >= laggard;
}
