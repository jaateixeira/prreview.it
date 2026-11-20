"""Entitlements. Until the hosted plans exist (M8) nothing is limited, except the free AI
reviews: they run on one small server (ADR 0025)."""

from __future__ import annotations

from previewit.domain.identity import UserId

FREE_AI_REVIEWS_PER_DAY = 10


class UnlimitedEntitlements:
    def may_create_share(self, user_id: UserId, shares_so_far: int) -> bool:
        return True

    def may_request_free_ai_review(self, user_id: UserId, free_today: int) -> bool:
        return free_today < FREE_AI_REVIEWS_PER_DAY
