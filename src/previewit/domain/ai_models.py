"""AI models that can review a work: what a review by each would cost, and which to suggest
(ADR 0025).

Pure rules, no network. The catalogue of models is data an adapter loads. Money is in US
dollars per million tokens, the way the model services price it. A token is a piece of a word;
four characters make about one token in English, and other languages need a few more.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from previewit.domain.credits import CreditPricing

MILLION = Decimal(1_000_000)
CHARS_PER_TOKEN = 4
PROMPT_TOKENS = 800  # the instructions around the work
MAX_SUGGESTED = 3  # suggested at first
MAX_LISTED = 20  # with "See more"
MAX_PER_REQUEST = 3  # AI reviews asked for at once
TIERS = {1: "light", 2: "strong", 3: "among the strongest"}


class InvalidModelCard(ValueError):
    """A catalogue entry that cannot be right."""


@dataclass(frozen=True)
class ModelCard:
    """One model a person can choose, as the catalogue describes it."""

    key: str  # unique: "anthropic/claude-sonnet-5-5"
    name: str  # "Claude Sonnet 5.5"
    maker: str  # who made the model: "Anthropic"
    service: str  # who runs it and takes the key: "anthropic", "huggingface", "local"
    service_name: str  # "Anthropic", "Hugging Face", "Previewit"
    api_model: str  # the name the service knows it by
    hosted_in: str  # ISO 3166 country code of where it runs ("US", "FR", "FI"); "" if it varies
    hosting: str  # the same in words: "Mistral AI, France"
    input_usd: Decimal  # per million tokens read
    output_usd: Decimal  # per million tokens written
    context_tokens: int  # the most it reads and writes in one go (at the price above)
    max_output_tokens: int  # the most it may write, thinking included
    typical_output_tokens: int  # what a review usually takes, thinking included
    tier: int  # 3: among the strongest; 2: strong; 1: light
    open_weights: bool = False
    free: bool = False  # Previewit runs it on its own server and pays
    key_label: str = ""  # what the service calls its key: "Anthropic API key"
    key_url: str = ""  # where to get one
    checked: date | None = None  # when the price was last checked
    note: str = ""

    def __post_init__(self) -> None:
        if not self.key.strip() or not self.name.strip() or not self.api_model.strip():
            raise InvalidModelCard("a model needs a key, a name and the service's name for it")
        if self.input_usd < 0 or self.output_usd < 0:
            raise InvalidModelCard(f"{self.key}: prices cannot be negative")
        if self.free and (self.input_usd or self.output_usd):
            raise InvalidModelCard(f"{self.key}: a free model has no price")
        if not 0 < self.typical_output_tokens <= self.max_output_tokens < self.context_tokens:
            raise InvalidModelCard(f"{self.key}: the token limits do not add up")
        if self.tier not in TIERS:
            raise InvalidModelCard(f"{self.key}: the tier is 1, 2 or 3")

    def fits(self, input_tokens: int) -> bool:
        """It can read the whole work and still write a full review."""
        return input_tokens + self.max_output_tokens <= self.context_tokens

    @property
    def flag(self) -> str:
        return flag(self.hosted_in)


def flag(country: str) -> str:
    """The flag emoji for a two-letter country code; a globe when the place varies."""
    code = country.strip().upper()
    if len(code) != 2 or not code.isalpha() or not code.isascii():
        return "\U0001f310"
    return "".join(chr(0x1F1E6 + ord(letter) - ord("A")) for letter in code)


def tokens_for(chars: int) -> int:
    """About how many tokens a model reads for a work of `chars` characters."""
    return PROMPT_TOKENS + math.ceil(max(chars, 0) / CHARS_PER_TOKEN)


def cost_of(card: ModelCard, input_tokens: int, output_tokens: int) -> Decimal:
    """What the service charges for a finished review."""
    if card.free:
        return Decimal(0)
    return (card.input_usd * input_tokens + card.output_usd * output_tokens) / MILLION


@dataclass(frozen=True)
class Estimate:
    input_tokens: int
    own_key_usd: Decimal  # about what the service charges the person's own key
    at_most_usd: Decimal  # if the model writes as much as it may
    credit_cents: int  # about what it takes from the person's credit (no key), in euro cents
    credit_at_most_cents: int  # what is held from the credit while it is written (ADR 0026)

    @property
    def free(self) -> bool:
        return self.at_most_usd == 0


def estimate(card: ModelCard, input_tokens: int, pricing: CreditPricing) -> Estimate:
    """About what a review by `card` costs, with the person's own key and from their credit."""
    usual = cost_of(card, input_tokens, card.typical_output_tokens)
    most = cost_of(card, input_tokens, card.max_output_tokens)
    return Estimate(input_tokens, usual, most, pricing.cents(usual), pricing.cents(most))


@dataclass(frozen=True)
class Suggestion:
    card: ModelCard
    estimate: Estimate
    reason: str  # why it is suggested, for the person


def suggest(
    cards: Sequence[ModelCard], chars: int, pricing: CreditPricing
) -> tuple[list[Suggestion], list[Suggestion]]:
    """(up to three suggested models, the others for "See more"), for a work of `chars`
    characters. Only models that can read the whole work appear. The three come from three
    makers: a free model when one can do it, one among the strongest, one good value."""
    tokens = tokens_for(chars)
    fitting = [c for c in cards if c.fits(tokens)]

    def make(card: ModelCard, reason: str) -> Suggestion:
        return Suggestion(card, estimate(card, tokens, pricing), reason)

    picks: list[Suggestion] = []

    def pick(candidates: Sequence[ModelCard], reason: str) -> None:
        makers = {p.card.maker for p in picks}
        for candidate in candidates:
            if candidate.maker not in makers and len(picks) < MAX_SUGGESTED:
                picks.append(make(candidate, reason))
                return

    paid = [c for c in fitting if not c.free]
    free = [c for c in fitting if c.free]
    if free:
        pick(free, "Free: Previewit runs it on its own server and pays for it.")
    pick(
        [c for c in paid if c.tier == 3], "Among the strongest models: careful, detailed feedback."
    )
    by_price = sorted(
        (c for c in paid if c.tier >= 2), key=lambda c: cost_of(c, tokens, c.typical_output_tokens)
    )
    pick(by_price, "Good value: solid feedback for little money.")
    while len(picks) < MAX_SUGGESTED:
        before = len(picks)
        makers = {p.card.maker for p in picks}
        rest = [c for c in fitting if c.maker not in makers]
        if not rest:
            break
        pick(rest, f"Another view, from {rest[0].maker}.")
        if len(picks) == before:
            break

    chosen = {p.card.key for p in picks}
    more = [make(c, TIERS[c.tier].capitalize() + ".") for c in fitting if c.key not in chosen]
    return picks, more[: MAX_LISTED - len(picks)]
