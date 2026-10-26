# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
import json
from genlayer import *

# GEN in wei (10**18) is the only asset here. Time is an Ethereum block height:
# the caller names it, two providers check it, and the payout is integer math
# on heights. Consensus only ever binds a boolean - a height that is still
# moving cannot be voted on, so a live value never enters the round.

OPEN = "OPEN"
DONE = "DONE"
CANCELLED = "CANCELLED"
STALE_BLOCKS = 60

RPC_A = "https://ethereum-rpc.publicnode.com/?m="
RPC_B = "https://eth.drpc.org/?m="
HDR = {"content-type": "application/json"}


class BlockVestingEscrow(gl.Contract):
    """Streaming escrow: GEN vests linearly over a range of Ethereum blocks.

    The payer fixes the range and the recipient once. Anyone may release the
    part that has vested so far; the payer may cancel and take back what has
    not vested. The height is supplied by the caller and checked against both
    providers: it may never exceed the laggard's tip, so nobody can release a
    block that has not happened yet."""

    vests: TreeMap[str, str]
    vest_count: u256

    def __init__(self):
        self.vest_count = 0

    def _addr_hex(self, a) -> str:
        if isinstance(a, str):
            return a
        h = getattr(a, "as_hex", None)
        if isinstance(h, str):
            return h
        if isinstance(a, (bytes, bytearray)):
            return "0x" + bytes(a).hex()
        return str(a)

    def _is_evm(self, a) -> bool:
        if not isinstance(a, str) or not a.startswith("0x") or len(a) != 42:
            return False
        try:
            int(a[2:], 16)
        except ValueError:
            return False
        return True

    def _body(self, content) -> str:
        b = getattr(content, "body", None)
        if b is None:
            return str(content)
        return b.decode("utf-8", errors="replace") if isinstance(b, bytes) else str(b)

    def _transfer(self, to: Address, amount: int):
        if amount > 0:
            gl.get_contract_at(to).emit_transfer(value=u256(amount))

    def _load(self, vid: str) -> dict:
        raw = self.vests.get(str(vid), "")
        if not raw:
            raise gl.vm.UserError("Vesting not found")
        return json.loads(raw)

    def _save(self, d: dict):
        self.vests[d["vest_id"]] = json.dumps(d)

    def _hex_int(self, body: str) -> int:
        try:
            data = json.loads(body)
        except Exception:
            return 0
        if not isinstance(data, dict):
            return 0
        v = data.get("result")
        if isinstance(v, int):
            return v
        if not isinstance(v, str):
            return 0
        s = v.strip().lower()
        if not s.startswith("0x") or len(s) < 3:
            return 0
        try:
            return int(s[2:], 16)
        except ValueError:
            return 0

    def _vested(self, d: dict, height: int) -> int:
        start = int(d["start_block"])
        end = int(d["end_block"])
        total = int(d["total"])
        if height <= start:
            return 0
        if height >= end:
            return total
        return total * (int(height) - start) // (end - start)

    # ---------------- the block clock, as a boolean ----------------

    def _fresh(self, height: int) -> bool:
        """True when both providers agree this height is real and not stale.

        The consensus binds this boolean and nothing else. The rule is
        `min(tips) - STALE <= height <= min(tips)`: the laggard caps every
        release, so a height is never ahead of what the chain has produced,
        and it can be at most STALE_BLOCKS behind."""
        payload = json.dumps({"jsonrpc": "2.0", "id": 1,
                              "method": "eth_blockNumber", "params": []})

        def run() -> int:
            a = 0
            b = 0
            for _ in range(2):
                if a <= 0:
                    try:
                        a = self._hex_int(self._body(gl.nondet.web.post(
                            RPC_A + "tip", body=payload, headers=HDR)))
                    except Exception:
                        a = 0
                if b <= 0:
                    try:
                        b = self._hex_int(self._body(gl.nondet.web.post(
                            RPC_B + "tip", body=payload, headers=HDR)))
                    except Exception:
                        b = 0
            if a <= 0 or b <= 0:
                return 0
            laggard = a if a < b else b
            h = int(height)
            return 1 if (h <= laggard and h + STALE_BLOCKS >= laggard) else 0

        def agrees(leader) -> bool:
            return isinstance(leader, gl.vm.Return) and int(leader.calldata) == run()

        return int(gl.vm.run_nondet_unsafe(run, agrees)) == 1

    def _not_started(self, start: int) -> bool:
        """True when no provider has reached the first vested block yet."""
        payload = json.dumps({"jsonrpc": "2.0", "id": 1,
                              "method": "eth_blockNumber", "params": []})

        def run() -> int:
            a = 0
            b = 0
            for _ in range(2):
                if a <= 0:
                    try:
                        a = self._hex_int(self._body(gl.nondet.web.post(
                            RPC_A + "tip", body=payload, headers=HDR)))
                    except Exception:
                        a = 0
                if b <= 0:
                    try:
                        b = self._hex_int(self._body(gl.nondet.web.post(
                            RPC_B + "tip", body=payload, headers=HDR)))
                    except Exception:
                        b = 0
            if a <= 0 or b <= 0:
                return 0
            fresher = a if a > b else b
            return 1 if fresher < int(start) else 0

        def agrees(leader) -> bool:
            return isinstance(leader, gl.vm.Return) and int(leader.calldata) == run()

        return int(gl.vm.run_nondet_unsafe(run, agrees)) == 1

    # ---------------- lifecycle ----------------

    @gl.public.write.payable
    def open_vest(self, recipient: str, start_block: int, end_block: int) -> str:
        """Escrow GEN and fix the block range over which it vests."""
        payer = self._addr_hex(gl.message.sender_address)
        total = int(gl.message.value)
        if total <= 0:
            raise gl.vm.UserError("Escrow must be > 0 wei")
        if not self._is_evm(recipient) or self._addr_hex(recipient).lower() == payer.lower():
            raise gl.vm.UserError("Recipient must be another 0x address")
        try:
            start = int(start_block)
            end = int(end_block)
        except Exception:
            raise gl.vm.UserError("Block heights must be integers")
        if start <= 0 or end <= start:
            raise gl.vm.UserError("Need a block range with start < end")
        # a vesting cannot begin on a block the chain has already produced
        if not self._not_started(start):
            raise gl.vm.UserError("The vesting window has already started")
        vid = "v" + str(int(self.vest_count))
        self.vests[vid] = json.dumps({
            "vest_id": vid, "payer": payer,
            "recipient": self._addr_hex(recipient).lower(),
            "start_block": start, "end_block": end, "total": total,
            "released": 0, "returned": 0, "status": OPEN,
            "reason": "", "height": 0,
            "units": {"asset": "GEN", "amount_decimals": 18,
                      "time": "ethereum block height"},
        })
        self.vest_count = u256(int(self.vest_count) + 1)
        return vid

    @gl.public.write
    def release(self, vest_id: str, height: int) -> str:
        """Send the recipient whatever has vested up to `height`."""
        d = self._load(vest_id)
        if str(d["status"]) != OPEN:
            raise gl.vm.UserError("Vesting is " + str(d["status"]))
        try:
            h = int(height)
        except Exception:
            raise gl.vm.UserError("Height must be an integer")
        if not self._fresh(h):
            raise gl.vm.UserError("That height is not fresh on both providers")
        owed = self._vested(d, h) - int(d["released"])
        if owed <= 0:
            raise gl.vm.UserError("Nothing has vested since the last release")
        d["released"] = int(d["released"]) + owed
        d["height"] = h
        if int(d["released"]) >= int(d["total"]):
            d["status"] = DONE
            d["reason"] = "fully vested and released"
        self._save(d)
        self._transfer(Address(d["recipient"]), owed)
        return "RELEASED"

    @gl.public.write
    def cancel(self, vest_id: str, height: int) -> str:
        """Stop the stream: pay what has vested, return what has not."""
        d = self._load(vest_id)
        if str(d["status"]) != OPEN:
            raise gl.vm.UserError("Vesting is " + str(d["status"]))
        payer = self._addr_hex(gl.message.sender_address).lower()
        if payer != str(d["payer"]).lower():
            raise gl.vm.UserError("Only the payer cancels")
        try:
            h = int(height)
        except Exception:
            raise gl.vm.UserError("Height must be an integer")
        if not self._fresh(h):
            raise gl.vm.UserError("That height is not fresh on both providers")
        vested = self._vested(d, h)
        owed = vested - int(d["released"])
        back = int(d["total"]) - vested
        if owed < 0:
            owed = 0
        if back < 0:
            back = 0
        # cancelling settles both sides: whatever has vested already goes to the
        # recipient, whatever has not goes back to the payer, and nothing is
        # left for anyone to wait on.
        d["released"] = int(d["released"]) + owed
        d["returned"] = back
        d["height"] = h
        d["status"] = CANCELLED
        d["reason"] = "cancelled by the payer"
        self._save(d)
        if owed > 0:
            self._transfer(Address(d["recipient"]), owed)
        self._transfer(Address(payer), back)
        return CANCELLED

    # ---------------- views ----------------

    @gl.public.view
    def get_vest(self, vest_id: str) -> str:
        d = self._load(vest_id)
        total = int(d["total"])
        span = int(d["end_block"]) - int(d["start_block"])
        d["held"] = total - int(d["released"]) - int(d["returned"])
        d["per_block"] = total // span if span > 0 else 0
        return json.dumps(d)

    @gl.public.view
    def quote(self, vest_id: str, height: int) -> str:
        """Pure arithmetic on the stored terms: no consensus needed."""
        d = self._load(vest_id)
        try:
            h = int(height)
        except Exception:
            h = 0
        vested = self._vested(d, h)
        owed = vested - int(d["released"])
        back = int(d["total"]) - vested
        return json.dumps({"height": h, "vested": vested,
                           "would_release": owed if owed > 0 else 0,
                           "would_return": back if back > 0 else 0,
                           "status": str(d["status"])})

    @gl.public.view
    def get_vest_count(self) -> int:
        return int(self.vest_count)
