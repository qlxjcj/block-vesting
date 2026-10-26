# Block Vesting Escrow

**GEN that streams by Ethereum block height: released against a height that two
independent providers agree on, never against a clock nobody can vote on.**

Deployed on GenLayer Asimov: **`0x2A5b08ceDe80A88F2c18Fa30552c39B652810209`**
([explorer](https://explorer-asimov.genlayer.com/address/0x2A5b08ceDe80A88F2c18Fa30552c39B652810209))

App: https://qlxjcj.github.io/block-vesting/

> Bradbury was reset to Phase 2 (chain id 4221) in October 2026, so this runs on Asimov.

---

## What it does

A payer escrows GEN and fixes a block range. Over that range the money vests
linearly:

```
vested(height) = total * (height - start_block) / (end_block - start_block)
```

Nothing has vested at the first block, everything has vested at the last, and
anyone may release the part that has vested so far — the GEN always goes to the
recipient, never to whoever called. The payer may cancel at any height: the
vested part is paid to the recipient and the rest goes back, so a cancel settles
both sides at once and leaves nothing in the contract.

```
open_vest   (payable, window frozen, must be in the future)   -> OPEN
release     (permissionless, pays the recipient)              -> OPEN / DONE
cancel      (payer only, settles both sides)                  -> CANCELLED
```

## Where the time comes from

GenLayer has no clock. `gl.message` carries no timestamp, and the chain's own
clock cannot be trusted to the block anyway — so time here is an **Ethereum
block height**, read from two independent JSON-RPC operators.

Two facts about that, both measured rather than assumed:

- the two operators' tips **disagree sometimes** (in one sample the tips were
  **517 blocks apart**, in another they matched exactly);
- an operator occasionally answers **HTTP 200 with an error object inside
  `result`** instead of a height.

So the contract reads both tips and:

1. treats an unreadable tip — empty body, HTML, JSON-RPC error, whatever — as
   a failure, and refuses rather than guessing;
2. counts from the **laggard**, never the fresher tip;
3. accepts a release height only when `laggard - 60 <= height <= laggard`.

## Why the height is supplied by the caller

This is the part worth stealing.

The naive version passes no height at all: the contract reads the tip itself and
pays out the difference. That is also what a naive version does with consensus,
and it fails in the field: the tip is a **value that is still moving**, so two
validators reading it a second apart compute different payouts, they cannot
agree, the round fails, and the write is silently undone while every receipt
still looks like a success. I hit exactly this on a previous contract; every
`open` and `buy` came back with a spurious refusal and the evidence call never
recorded anything.

So the height is an **input**, and consensus binds only a **boolean** — "is this
height real on both providers and within 60 blocks of the laggard?". Two
validators reading at different moments now almost always answer the same
question the same way, and when they don't it is because the chain genuinely
moved across the boundary.

The rule `height <= laggard` is what makes it safe to leave the number to the
caller: **nobody can release a block that has not been mined yet**, so nobody can
take a wei that has not vested. The staleness bound stops a caller from
resurrecting an old height to under-pay and then claiming the money later — the
amount is computed from the height, and a stale height is simply refused.

## Money, exactly

One asset and one clock, both integers, never converted into one another:

| quantity | unit | representation |
|---|---|---|
| escrow, release, refund | **GEN** | integer **wei** (10¹⁸) |
| time | **Ethereum block** | integer height |

Every vesting stores the model on chain:

```json
{"asset":"GEN","amount_decimals":18,"time":"ethereum block height"}
```

```
released + returned == total        on every terminal path
held == 0                           once a vesting is DONE or CANCELLED
```

The browser converts GEN text with `toWei` / `formatGen` and mirrors the
vesting arithmetic in `units.mjs`, which is tested by `node --test` — the page
never carries a second, untested copy of the contract's rules.

## App

`index.html` is the product. It reads **both providers itself**, shows the two
tips, how far apart they are, and which laggard the contract will use, then
computes the live vested amount from it. Releasing or cancelling sends that
laggard height, and the contract re-checks it. Every view is bound to a vesting
id; there is no `get_latest()` anywhere. Writes go through the injected wallet
with loading states and surfaced errors; DOM APIs only.

## API

| method | note |
|---|---|
| `open_vest(recipient, start_block, end_block)` | **payable**; the value is `total`; the window must not have started on either provider |
| `release(vest_id, height)` | permissionless; pays the recipient `vested(height) - released`; `DONE` at the end |
| `cancel(vest_id, height)` | payer only; pays the vested part out and returns the rest |
| `get_vest` / `quote` / `get_vest_count` | JSON strings; `quote` is pure arithmetic, no consensus |

**Bounds** — `total` > 0, `end_block > start_block > 0`, recipient is another
0x address, `laggard - 60 <= height <= laggard`.

## Live

Verified on GenLayer Asimov against `0x2A5b08ceDe80A88F2c18Fa30552c39B652810209`. Every number
below is read back from chain state with `get_vest`, not from receipts.

### `v0` — a vesting that ran to the end

| step | result |
|---|---|
| `open_vest` | **0.1 GEN**, window `[26275958, 26275988]` (30 blocks) |
| `release` (partial) | confirmed inside the window |
| `release` (final) | at height **26275990**, past the end |
| state | `status` **DONE**, `released` **0.1 GEN**, `returned` 0, `held` **0** |

```
released 0.1 + returned 0 == total 0.1   ✓
```

### `v1` — cancelled mid-flight

| field | value |
|---|---|
| window | `[26276043, 26276943]` (900 blocks) |
| cancelled at height | **26276054** — 11 blocks into 900 |
| `released` (to the recipient) | **0.001222222222222222 GEN** |
| `returned` (to the payer) | **0.098777777777777778 GEN** |
| `held` | **0** |

The arithmetic is the contract's, and it checks out to the wei:

```
11 / 900 * 0.1 = 0.0012222222222222222…   →  1222222222222222 wei
```

Cancelling settled **both sides in one call** — the vested part to the
recipient and the rest back to the payer — which is why `held` is 0 and
`released + returned == total` holds for a cancelled vesting as well.

### What the chain balance says

Both vestings report `held == 0`, but the contract's **native balance is still
0.2 GEN**, and the recipient's account never received the two payouts. `emit_transfer`
is documented as emitting on `on='finalized'`, and on this network the emitted
transfer does not reach the recipient's EVM balance — measured here and in two
other contracts, several minutes after the writes reported `FINALIZED`.

So: **the ledger settles exactly and that is what the tests and the views prove;
the outbound native transfer is not reflected in balances on Asimov.** I am
stating that rather than claiming the money moved, because the balance is the
one thing I can actually check.

## Trust boundaries, stated plainly

1. **The two providers are the oracle.** They are contract constants, but a
   provider that lies about its tip can move the release height. The laggard
   rule caps what either of them can do *upward*: a provider cannot make the
   contract release more than the other has confirmed.
2. **A lag costs the recipient, not the payer.** If one provider sits ~500
   blocks behind, releases lag by roughly an hour. That is the conservative
   direction, and it is the price of never over-releasing.
3. **Cancellable vesting is cancellable.** The payer can stop the stream at any
   height; anything already vested is still paid out. If you need a hard
   commitment, open the vesting with the whole term and cancel nobody.
4. **The height is a height, not a promise about wall time.** Ethereum averages
   ~12s a block; the contract never uses that number, it only compares heights.

## Testing

```
python -m pytest tests -q        # 41 contract tests + the browser wrapper
node --test tests/js/units.test.mjs
```

**41 tests** in `tests/direct/test_block_vesting.py`: the unit model, the frozen
window, linear vesting and integer rounding, delta-only releases, money
never going to the caller, the laggard rule (a height above it refused, its own
tip accepted, staleness at the boundary), one provider down, a provider
answering **200 with an error object**, a provider answering with HTML, refusals
leaving the state byte-identical, both exit paths and the conservation
invariant.

The fixtures in `tests/direct/conftest.py` use the real JSON-RPC envelope,
including the error-in-`result` shape that public RPCs really do return.

## Source integrity

```
sha256  96523cf814a3c2b19bcdee299e9b27557b3f69428a34ef2cf323e6f5dddaf848
bytes   11233
```
