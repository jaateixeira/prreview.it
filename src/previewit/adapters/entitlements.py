"""Entitlements. Until the hosted plans exist (M8) nothing is limited."""

from __future__ import annotations

from previewit.domain.identity import UserId


class UnlimitedEntitlements:
    def may_create_share(self, user_id: UserId, shares_so_far: int) -> bool:
        return True
