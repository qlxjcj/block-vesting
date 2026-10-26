"""Direct-mode tests for Block Vesting Escrow.

Groups:

  A  unit model   -- GEN in wei, time in block heights, the range is frozen
  B  opening      -- the window must not have started, on either provider
  C  release      -- linear vesting, integer math, and who gets the money
  D  freshness    -- the height is caller-supplied and checked, never assumed
  E  cancel       -- settles both sides, then nothing can move again
  F  invariants   -- money is conserved, refusals change nothing, views are str
"""

import json

import pytest

from conftest import (
    END,
    PAYER,
    RECIPIENT,
    SECOND,
    STRANGER,
    START,
    TIP,
    TOTAL,
    balance,
    bad_tip_body,
    cancel,
    contract_balance,
    open_vest,
    release,
    remock,
    snapshot,
    tip_body,
    vesting,
)


# ==========================================================================
# A. unit model
# ==========================================================================

def test_opening_escrows_the_total(vest):
    vm, c = vest
    before = balance(vm, PAYER)
    vid = open_vest(vm, c)
    assert contract_balance(vm) == TOTAL
    assert balance(vm, PAYER) == before - TOTAL
    d = vesting(vm, c, vid)
    assert d["total"] == TOTAL
    assert d["released"] == 0 and d["returned"] == 0
    assert d["held"] == TOTAL


def test_the_terms_and_the_unit_model_are_stored(vest):
    vm, c = vest
    d = vesting(vm, c, open_vest(vm, c))
    assert d["units"] == {"asset": "GEN", "amount_decimals": 18,
                          "time": "ethereum block height"}
    assert d["start_block"] == START and d["end_block"] == END
    assert d["payer"] == PAYER.lower()
    assert d["recipient"] == RECIPIENT.lower()
    assert d["per_block"] == TOTAL // (END - START)


def test_a_refused_open_moves_no_funds(vest):
    vm, c = vest
    before = balance(vm, PAYER)
    with pytest.raises(Exception):
        open_vest(vm, c, total=0)
    assert balance(vm, PAYER) == before
    assert contract_balance(vm) == 0
    assert c.get_vest_count() == 0


@pytest.mark.parametrize("kw", [
    {"recipient": PAYER}, {"recipient": "0x1234"}, {"recipient": ""},
    {"start": END, "end": START}, {"start": START, "end": START},
    {"start": 0, "end": END},
])
def test_rejects_bad_terms(vest, kw):
    vm, c = vest
    with pytest.raises(Exception):
        open_vest(vm, c, **kw)
    assert c.get_vest_count() == 0
    assert contract_balance(vm) == 0


def test_a_vesting_cannot_start_in_the_past(vest):
    vm, c = vest
    with pytest.raises(Exception):
        open_vest(vm, c, start=TIP)
    with pytest.raises(Exception):
        open_vest(vm, c, start=TIP - 10)
    assert c.get_vest_count() == 0


def test_count_tracks_opens(vest):
    vm, c = vest
    assert c.get_vest_count() == 0
    open_vest(vm, c)
    open_vest(vm, c, total=TOTAL * 2)
    assert c.get_vest_count() == 2


# ==========================================================================
# C. release math
# ==========================================================================

def test_nothing_vests_before_the_window(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    remock(vm, a=tip_body(START - 1), b=tip_body(START - 1))
    with pytest.raises(Exception):
        release(vm, c, vid, START - 1)
    assert vesting(vm, c, vid)["released"] == 0


def test_half_the_window_pays_half_the_total(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    remock(vm, a=tip_body(350), b=tip_body(350))
    release(vm, c, vid, 350)
    d = vesting(vm, c, vid)
    assert d["released"] == TOTAL // 2
    assert balance(vm, RECIPIENT) == TOTAL // 2
    assert d["held"] == TOTAL - TOTAL // 2


def test_a_second_release_only_pays_the_delta(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    remock(vm, a=tip_body(320), b=tip_body(320))
    release(vm, c, vid, 320)
    remock(vm, a=tip_body(360), b=tip_body(360))
    release(vm, c, vid, 360)
    d = vesting(vm, c, vid)
    per = TOTAL // (END - START)
    assert d["released"] == per * 60
    assert balance(vm, RECIPIENT) == per * 60


def test_releasing_at_the_end_pays_everything_and_finishes(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    remock(vm, a=tip_body(END), b=tip_body(END))
    release(vm, c, vid, END)
    d = vesting(vm, c, vid)
    assert d["released"] == TOTAL
    assert d["status"] == "DONE"
    assert d["held"] == 0
    assert contract_balance(vm) == 0


def test_a_height_past_the_end_still_caps_at_total(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    remock(vm, a=tip_body(END + 500), b=tip_body(END + 500))
    release(vm, c, vid, END + 500)
    assert vesting(vm, c, vid)["released"] == TOTAL
    assert contract_balance(vm) == 0


def test_anyone_may_release_but_the_money_goes_to_the_recipient(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    remock(vm, a=tip_body(350), b=tip_body(350))
    before_stranger = balance(vm, STRANGER)
    release(vm, c, vid, 350, sender=STRANGER)
    assert balance(vm, STRANGER) == before_stranger
    assert balance(vm, RECIPIENT) == TOTAL // 2


def test_an_odd_total_never_leaves_a_wei_behind(vest):
    vm, c = vest
    total = 10 ** 18 + 7
    vid = open_vest(vm, c, total=total, start=300, end=303)
    remock(vm, a=tip_body(302), b=tip_body(302))
    release(vm, c, vid, 302)                  # 2 of 3 blocks
    remock(vm, a=tip_body(400), b=tip_body(400))
    release(vm, c, vid, 400)
    d = vesting(vm, c, vid)
    assert d["released"] == total
    assert balance(vm, RECIPIENT) == total
    assert contract_balance(vm) == 0


def test_a_finished_vesting_takes_no_more(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    remock(vm, a=tip_body(END), b=tip_body(END))
    release(vm, c, vid, END)
    before = balance(vm, RECIPIENT)
    with pytest.raises(Exception):
        release(vm, c, vid, END)
    assert balance(vm, RECIPIENT) == before


def test_releasing_twice_at_the_same_height_is_refused(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    remock(vm, a=tip_body(350), b=tip_body(350))
    release(vm, c, vid, 350)
    before = balance(vm, RECIPIENT)
    with pytest.raises(Exception):
        release(vm, c, vid, 350)
    assert balance(vm, RECIPIENT) == before


# ==========================================================================
# D. freshness: the height is checked, never assumed
# ==========================================================================

def test_a_height_above_the_laggard_is_refused(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    # one provider is 10 blocks ahead; the laggard caps every release
    remock(vm, a=tip_body(350), b=tip_body(340))
    with pytest.raises(Exception):
        release(vm, c, vid, 345)
    assert vesting(vm, c, vid)["released"] == 0


def test_the_laggards_own_tip_is_allowed(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    remock(vm, a=tip_body(350), b=tip_body(340))
    release(vm, c, vid, 340)
    assert vesting(vm, c, vid)["released"] == TOTAL * 40 // 100


def test_a_stale_height_is_refused(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    remock(vm, a=tip_body(350), b=tip_body(350))
    with pytest.raises(Exception):
        release(vm, c, vid, 350 - 61)
    assert vesting(vm, c, vid)["released"] == 0


def test_a_height_just_inside_the_staleness_limit_is_allowed(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    remock(vm, a=tip_body(410), b=tip_body(410))
    release(vm, c, vid, 410 - 60)
    assert vesting(vm, c, vid)["released"] == TOTAL * 50 // 100


def test_an_unreachable_provider_fails_closed(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    remock(vm, a=tip_body(350), b="")
    with pytest.raises(Exception):
        release(vm, c, vid, 350)
    assert vesting(vm, c, vid)["released"] == 0


def test_a_provider_that_answers_200_with_an_error_fails_closed(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    remock(vm, a=tip_body(350), b=bad_tip_body())
    with pytest.raises(Exception):
        release(vm, c, vid, 350)
    assert vesting(vm, c, vid)["released"] == 0


def test_a_provider_that_answers_with_html_fails_closed(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    remock(vm, a="<html>502 Bad Gateway</html>", b=tip_body(350))
    with pytest.raises(Exception):
        release(vm, c, vid, 350)
    assert vesting(vm, c, vid)["released"] == 0


def test_both_providers_failing_fails_closed(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    remock(vm, a=bad_tip_body(), b=bad_tip_body())
    with pytest.raises(Exception):
        release(vm, c, vid, 350)
    assert vesting(vm, c, vid)["released"] == 0


def test_a_non_integer_height_is_refused(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    remock(vm, a=tip_body(350), b=tip_body(350))
    for bad in ("abc", None):
        with pytest.raises(Exception):
            release(vm, c, vid, bad)


def test_a_refused_release_leaves_the_state_byte_identical(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    remock(vm, a=tip_body(350), b=tip_body(350))
    before = snapshot(vm, c, vid)
    with pytest.raises(Exception):
        release(vm, c, vid, 400)
    with pytest.raises(Exception):
        release(vm, c, vid, 100)
    remock(vm, a=bad_tip_body(), b=tip_body(350))
    with pytest.raises(Exception):
        release(vm, c, vid, 350)
    assert snapshot(vm, c, vid) == before


# ==========================================================================
# E. cancel
# ==========================================================================

def test_only_the_payer_cancels(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    remock(vm, a=tip_body(350), b=tip_body(350))
    for sender in (STRANGER, RECIPIENT):
        with pytest.raises(Exception):
            cancel(vm, c, vid, 350, sender=sender)
    assert vesting(vm, c, vid)["status"] == "OPEN"


def test_cancelling_pays_both_sides_and_empties_the_pool(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    remock(vm, a=tip_body(350), b=tip_body(350))
    before_payer = balance(vm, PAYER)
    cancel(vm, c, vid, 350)
    d = vesting(vm, c, vid)
    assert d["status"] == "CANCELLED"
    assert d["released"] == TOTAL // 2          # vested half to the recipient
    assert d["returned"] == TOTAL - TOTAL // 2  # unvested half back to the payer
    assert d["held"] == 0
    assert balance(vm, RECIPIENT) == TOTAL // 2
    assert balance(vm, PAYER) == before_payer + TOTAL - TOTAL // 2
    assert contract_balance(vm) == 0


def test_cancelling_at_the_start_returns_everything(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    remock(vm, a=tip_body(START), b=tip_body(START))
    before = balance(vm, PAYER)
    cancel(vm, c, vid, START)
    assert balance(vm, PAYER) == before + TOTAL
    assert balance(vm, RECIPIENT) == 0
    assert contract_balance(vm) == 0


def test_nothing_moves_after_a_cancel(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    remock(vm, a=tip_body(350), b=tip_body(350))
    cancel(vm, c, vid, 350)
    for call in (lambda: release(vm, c, vid, 400),
                 lambda: cancel(vm, c, vid, 350),
                 lambda: cancel(vm, c, vid, 400)):
        with pytest.raises(Exception):
            call()
    assert contract_balance(vm) == 0


def test_cancelling_a_finished_vesting_is_refused(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    remock(vm, a=tip_body(END), b=tip_body(END))
    release(vm, c, vid, END)
    with pytest.raises(Exception):
        cancel(vm, c, vid, END)
    assert contract_balance(vm) == 0


def test_a_cancel_with_a_bad_height_is_refused(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    remock(vm, a=tip_body(350), b=tip_body(340))
    before = balance(vm, PAYER)
    with pytest.raises(Exception):
        cancel(vm, c, vid, 345)
    assert balance(vm, PAYER) == before
    assert vesting(vm, c, vid)["status"] == "OPEN"
    assert contract_balance(vm) == TOTAL


# ==========================================================================
# F. invariants and views
# ==========================================================================

def test_released_plus_returned_always_equals_the_total(vest):
    vm, c = vest
    a = open_vest(vm, c)
    b = open_vest(vm, c, total=TOTAL * 3)
    remock(vm, a=tip_body(330), b=tip_body(330))
    release(vm, c, a, 330)
    cancel(vm, c, a, 330)
    remock(vm, a=tip_body(END + 10), b=tip_body(END + 10))
    release(vm, c, b, END + 10)
    for vid in (a, b):
        d = vesting(vm, c, vid)
        assert d["released"] + d["returned"] == d["total"]
        assert d["held"] == 0
    assert contract_balance(vm) == 0


def test_two_vestings_never_mix(vest):
    vm, c = vest
    a = open_vest(vm, c)
    b = open_vest(vm, c, total=TOTAL * 2, recipient=SECOND)
    remock(vm, a=tip_body(350), b=tip_body(350))
    release(vm, c, a, 350)
    assert vesting(vm, c, a)["released"] == TOTAL // 2
    assert vesting(vm, c, b)["released"] == 0
    assert balance(vm, RECIPIENT) == TOTAL // 2
    assert balance(vm, SECOND) == 0
    assert contract_balance(vm) == TOTAL * 3 - TOTAL // 2


def test_quote_is_pure_arithmetic_and_matches_the_chain_result(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    q = json.loads(c.quote(vid, 350))
    assert q == {"height": 350, "vested": TOTAL // 2,
                 "would_release": TOTAL // 2, "would_return": TOTAL // 2,
                 "status": "OPEN"}
    remock(vm, a=tip_body(350), b=tip_body(350))
    release(vm, c, vid, 350)
    q2 = json.loads(c.quote(vid, 370))
    assert q2["vested"] == TOTAL * 70 // 100
    assert q2["would_release"] == TOTAL * 70 // 100 - TOTAL // 2


def test_views_are_strings(vest):
    vm, c = vest
    vid = open_vest(vm, c)
    for v in (c.get_vest(vid), c.quote(vid, 350)):
        assert isinstance(v, str)
    assert c.get_vest_count() == 1


def test_an_unknown_vesting_raises(vest):
    vm, c = vest
    with pytest.raises(Exception):
        c.get_vest("v99")
    with pytest.raises(Exception):
        c.quote("v99", 350)
    with pytest.raises(Exception):
        release(vm, c, "v99", 350)
