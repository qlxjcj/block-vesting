"""Fixtures for Block Vesting Escrow direct-mode tests.

Both providers answer JSON-RPC; the fixture can make either one return an
error object inside `result` (which is what a public RPC actually does when it
is unhappy - HTTP 200, unusable body), an empty body, or nothing at all.

Direct mode does not track native value flow, so the same two accounting hooks
are installed, and a refused payable call puts the value back.
"""

import json
import os

import pytest

CONTRACT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "block_vesting_escrow.py",
)

PAYER = "0x" + "aa" * 20
RECIPIENT = "0x" + "bb" * 20
SECOND = "0x" + "77" * 20
STRANGER = "0x" + "44" * 20

TOTAL = 10 ** 18          # 1 GEN in wei
START = 300
END = 400                 # 100 blocks, so 1e16 wei per block
TIP = 256


def hexs(n: int) -> str:
    return hex(int(n))


def tip_body(tip=TIP):
    return json.dumps({"jsonrpc": "2.0", "id": 1, "result": hexs(tip)})


# the shape an unhappy public RPC really returns: HTTP 200, error in `result`
def bad_tip_body():
    return json.dumps({"jsonrpc": "2.0", "id": 1,
                       "result": {"code": 503, "message": "upstream error"}})


def remock(vm, a=None, b=None):
    vm.clear_mocks()
    vm.mock_web(r".*publicnode\.com/\?m=tip.*",
                {"method": "POST", "status": 200,
                 "body": tip_body() if a is None else a})
    vm.mock_web(r".*drpc\.org/\?m=tip.*",
                {"method": "POST", "status": 200,
                 "body": tip_body() if b is None else b})


@pytest.fixture
def vest(direct_vm, direct_deploy):
    vm = direct_vm

    def _value_transfer_hook(vm, request):
        if "PostMessage" not in request:
            return None
        msg = request["PostMessage"]
        amount = int(msg.get("value", 0))
        if amount > 0:
            contract = vm._contract_address
            recipient = vm._to_bytes(msg["address"])
            vm._balances[contract] = vm._balances.get(contract, 0) - amount
            vm._balances[recipient] = vm._balances.get(recipient, 0) + amount
        return {"ok": None}

    vm._gl_call_hook = _value_transfer_hook

    remock(vm)
    c = direct_deploy(CONTRACT)

    def _wrap(fn):
        def inner(*args):
            paid = 0
            sender = vm._to_bytes(vm.sender)
            contract = vm._contract_address
            if vm.value > 0:
                vm._balances[sender] = vm._balances.get(sender, 0) - vm.value
                vm._balances[contract] = vm._balances.get(contract, 0) + vm.value
                paid = vm.value
            try:
                return fn(*args)
            except Exception:
                if paid:
                    vm._balances[sender] = vm._balances.get(sender, 0) + paid
                    vm._balances[contract] = vm._balances.get(contract, 0) - paid
                raise
        return inner

    c.open_vest = _wrap(c.open_vest)

    for addr in (PAYER, STRANGER):
        vm.deal(addr, 1000 * TOTAL)
    return vm, c


def balance(vm, addr):
    return vm._balances.get(vm._to_bytes(addr), 0)


def contract_balance(vm):
    return vm._balances.get(vm._contract_address, 0)


def open_vest(vm, c, recipient=RECIPIENT, start=START, end=END,
              total=TOTAL, sender=PAYER):
    vm.sender = sender
    vm.value = total
    try:
        return c.open_vest(recipient, start, end)
    finally:
        vm.value = 0


def release(vm, c, vid, height, sender=STRANGER):
    vm.sender = sender
    return c.release(vid, height)


def cancel(vm, c, vid, height, sender=PAYER):
    vm.sender = sender
    return c.cancel(vid, height)


def vesting(vm, c, vid):
    return json.loads(c.get_vest(vid))


def snapshot(vm, c, vid):
    return c.get_vest(vid)
