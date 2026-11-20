"""AI models: what a review by each costs and which three to suggest (ADR 0025)."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from previewit.domain.ai_models import (
    MAX_LISTED,
    MAX_SUGGESTED,
    InvalidModelCard,
    ModelCard,
    cost_of,
    estimate,
    flag,
    suggest,
    tokens_for,
)
from previewit.domain.credits import CreditPricing

MARGIN = CreditPricing(usd_to_eur=Decimal(1), margin=Decimal("0.30"), fees_and_tax=Decimal(0))


def card(key: str, **changes: object) -> ModelCard:
    base = ModelCard(
        key=key,
        name=key.title(),
        maker=key.split("/")[0],
        service=key.split("/")[0],
        service_name=key.split("/")[0].title(),
        api_model=key.split("/")[-1],
        hosted_in="US",
        hosting="Somewhere, USA",
        input_usd=Decimal("1"),
        output_usd=Decimal("5"),
        context_tokens=200_000,
        max_output_tokens=4_000,
        typical_output_tokens=2_500,
        tier=2,
    )
    return replace(base, **changes)  # type: ignore[arg-type]


LOCAL = card(
    "local/qwen3:8b", service="local", free=True, input_usd=Decimal(0), output_usd=Decimal(0),
    context_tokens=8_192, max_output_tokens=2_000, typical_output_tokens=1_500, tier=1,
    hosted_in="FI", hosting="Previewit's own server, Finland",
)  # fmt: skip
STRONG = card("anthropic/sonnet", tier=3, input_usd=Decimal(2), output_usd=Decimal(10))
STRONG_2 = card("openai/sol", tier=3, input_usd=Decimal(2), output_usd=Decimal(10))
CHEAP = card("mistral/large", tier=2, input_usd=Decimal("0.5"), output_usd=Decimal("1.5"))
CHEAP_SAME_MAKER = card(
    "anthropic/haiku", tier=2, input_usd=Decimal("0.1"), output_usd=Decimal("0.5")
)
LIGHT = card("openai/luna", tier=1, input_usd=Decimal("0.1"), output_usd=Decimal("0.5"))
CATALOGUE = [LOCAL, STRONG, STRONG_2, CHEAP_SAME_MAKER, CHEAP, LIGHT]


# -- the cards ---------------------------------------------------------------------------------


def test_a_card_refuses_nonsense() -> None:
    with pytest.raises(InvalidModelCard):
        card("x/y", input_usd=Decimal(-1))
    with pytest.raises(InvalidModelCard):
        card("x/y", max_output_tokens=300_000)  # more than it can hold
    with pytest.raises(InvalidModelCard):
        card("x/y", tier=4)
    with pytest.raises(InvalidModelCard):
        card("", name="")
    with pytest.raises(InvalidModelCard):
        card("x/y", free=True)  # a free model that charges


def test_flags_are_made_from_the_country_code() -> None:
    assert flag("FI") == "\U0001f1eb\U0001f1ee"
    assert flag("us") == "\U0001f1fa\U0001f1f8"
    assert flag("") == "\U0001f310"  # it varies: a globe
    assert flag("EUR") == "\U0001f310"


# -- tokens and money --------------------------------------------------------------------------


def test_tokens_count_the_work_and_the_instructions() -> None:
    assert tokens_for(0) > 0  # the instructions alone
    assert tokens_for(40_000) == tokens_for(0) + 10_000  # four characters a token


def test_an_estimate_prices_reading_and_writing() -> None:
    found = estimate(STRONG, 10_000, MARGIN)
    # 10,000 tokens read at $2/M, 2,500 written at $10/M: $0.02 + $0.025
    assert found.own_key_usd == Decimal("0.045")
    assert found.at_most_usd == Decimal("0.06")  # 4,000 written at most
    assert found.credit_cents == 6  # 30% on top, in cents rounded up: 5.85
    assert found.credit_at_most_cents == 8  # 7.8
    assert not found.free


def test_a_free_model_costs_nothing_either_way() -> None:
    found = estimate(LOCAL, 5_000, MARGIN)
    assert found.free
    assert found.own_key_usd == found.at_most_usd == 0
    assert found.credit_cents == found.credit_at_most_cents == 0


def test_the_cost_of_a_finished_review_uses_the_real_tokens() -> None:
    assert cost_of(STRONG, 1_000_000, 100_000) == Decimal(3)
    assert cost_of(LOCAL, 1_000_000, 100_000) == 0


@given(st.integers(0, 2_000_000), st.integers(0, 2_000_000))
def test_more_reading_never_costs_less(a: int, b: int) -> None:
    low, high = sorted((a, b))
    assert estimate(STRONG, low, MARGIN).own_key_usd <= estimate(STRONG, high, MARGIN).own_key_usd
    found = estimate(STRONG, low, MARGIN)
    assert found.credit_cents >= found.own_key_usd * 100


# -- suggestions -------------------------------------------------------------------------------


def test_three_suggestions_free_strong_and_good_value_from_different_makers() -> None:
    picks, more = suggest(CATALOGUE, 8_000, MARGIN)
    assert [p.card for p in picks] == [LOCAL, STRONG, CHEAP]
    assert "free" in picks[0].reason.lower()
    assert "strongest" in picks[1].reason.lower()
    assert "value" in picks[2].reason.lower()
    assert [s.card for s in more] == [STRONG_2, CHEAP_SAME_MAKER, LIGHT]  # in catalogue order


def test_a_long_work_leaves_out_models_that_cannot_read_it_whole() -> None:
    picks, more = suggest(CATALOGUE, 4 * 150_000, MARGIN)  # about 150,000 tokens
    shown = [s.card for s in picks + more]
    assert LOCAL not in shown  # 8,192 tokens
    assert all(c.fits(tokens_for(4 * 150_000)) for c in shown)


def test_without_a_free_model_the_third_choice_fills_from_another_maker() -> None:
    picks, _ = suggest([STRONG, STRONG_2, CHEAP, LIGHT], 1_000, MARGIN)
    assert [p.card for p in picks] == [STRONG, CHEAP, STRONG_2]
    assert "another view" in picks[2].reason.lower()


def test_nothing_fits_nothing_is_suggested() -> None:
    assert suggest([LOCAL], 4 * 100_000, MARGIN) == ([], [])


@given(
    st.lists(
        st.builds(
            lambda i, maker, tier, free, ctx: card(
                f"{maker}/m{i}",
                tier=tier,
                context_tokens=ctx,
                **(
                    {"free": True, "input_usd": Decimal(0), "output_usd": Decimal(0)}
                    if free
                    else {}
                ),
            ),
            st.integers(0, 10_000),
            st.sampled_from(["a", "b", "c", "d"]),
            st.integers(1, 3),
            st.booleans(),
            st.integers(8_000, 400_000),
        ),
        max_size=40,
        unique_by=lambda c: c.key,
    ),
    st.integers(0, 1_000_000),
)
def test_suggestions_keep_their_promises(cards: list[ModelCard], chars: int) -> None:
    picks, more = suggest(cards, chars, MARGIN)
    shown = [s.card for s in picks + more]
    assert len(picks) <= MAX_SUGGESTED
    assert len(shown) <= MAX_LISTED
    assert len({c.key for c in shown}) == len(shown)  # each once
    assert len({p.card.maker for p in picks}) == len(picks)  # three different makers
    assert all(c.fits(tokens_for(chars)) for c in shown)
    if any(c.free and c.fits(tokens_for(chars)) for c in cards):
        assert picks and picks[0].card.free  # a free model always leads when one can do it
    if any(c.fits(tokens_for(chars)) for c in cards):
        assert picks
