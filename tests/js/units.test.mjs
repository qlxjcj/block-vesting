import test from "node:test";
import assert from "node:assert/strict";

import {
  GEN_DECIMALS,
  STALE_BLOCKS,
  formatGen,
  isFresh,
  normHeight,
  quote,
  tipRange,
  toWei,
  vested,
} from "../../units.mjs";

const ONE = 10n ** 18n;

test("GEN text becomes wei and back", () => {
  assert.equal(GEN_DECIMALS, 18);
  assert.equal(toWei("1"), ONE);
  assert.equal(toWei("0.5"), ONE / 2n);
  assert.equal(toWei("0.000000000000000001"), 1n);
  assert.throws(() => toWei("1e3"), Error);
  assert.throws(() => toWei("-1"), Error);
  assert.throws(() => toWei("0.0000000000000000001"), /18 decimals/);
  assert.equal(formatGen(ONE / 2n), "0.5");
  assert.equal(formatGen(1n, 18), "0.000000000000000001");
});

test("heights are integers, and only integers", () => {
  assert.equal(normHeight("26274000"), "26274000");
  assert.equal(normHeight(" 26274000 "), "26274000");
  assert.equal(normHeight(""), "");
  assert.equal(normHeight("26.5"), "");
  assert.equal(normHeight("-5"), "");
  assert.equal(normHeight("0"), "");
  assert.equal(normHeight("abc"), "");
});

test("vesting is linear, and nothing escapes the total", () => {
  const total = ONE;
  assert.equal(vested(total, 300, 400, 250), 0n, "before the window");
  assert.equal(vested(total, 300, 400, 300), 0n, "at the first block");
  assert.equal(vested(total, 300, 400, 350), ONE / 2n);
  assert.equal(vested(total, 300, 400, 399), (total * 99n) / 100n);
  assert.equal(vested(total, 300, 400, 400), total, "at the last block");
  assert.equal(vested(total, 300, 400, 9000), total, "past the end still caps");
});

test("an odd total leaves no wei behind at the end", () => {
  const total = ONE + 7n;
  assert.equal(vested(total, 300, 303, 400), total);
});

test("quote releases the delta and returns the rest", () => {
  const vest = { total: ONE.toString(), start_block: 300, end_block: 400, released: 0 };
  const mid = quote(vest, 350);
  assert.equal(mid.wouldRelease, ONE / 2n);
  assert.equal(mid.wouldReturn, ONE / 2n);
  const later = quote({ ...vest, released: (ONE / 2n).toString() }, 370);
  assert.equal(later.vested, (ONE * 70n) / 100n);
  assert.equal(later.wouldRelease, (ONE * 70n) / 100n - ONE / 2n);
});

test("the tip range takes the laggard and says how far apart they are", () => {
  const same = tipRange(26274000, 26274000);
  assert.equal(same.ok, true);
  assert.equal(same.laggard, 26274000);
  assert.equal(same.apart, 0);

  const apart = tipRange(26274517, 26274000);
  assert.equal(apart.ok, true);
  assert.equal(apart.laggard, 26274000, "the laggard caps releases");
  assert.equal(apart.fresher, 26274517);
  assert.equal(apart.apart, 517);

  assert.equal(tipRange(0, 26274000).ok, false, "one provider down is not a range");
  assert.equal(tipRange("", "").ok, false);
});

test("a height may never run ahead of the laggard", () => {
  assert.equal(isFresh(350, 350), true, "the laggard's own tip");
  assert.equal(isFresh(349, 350), true);
  assert.equal(isFresh(351, 350), false, "one block ahead of the chain");
  assert.equal(isFresh(350 - STALE_BLOCKS, 350), true, "exactly stale enough");
  assert.equal(isFresh(350 - STALE_BLOCKS - 1, 350), false, "too stale");
  assert.equal(isFresh(0, 350), false);
});
