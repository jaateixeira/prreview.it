"""Exhaustive truth tables for AnonymityPolicy.

Expected values are written out by hand (not derived from the implementation), so a change
in who can see whom shows up as a deliberate, reviewable edit to this file.
"""

import dataclasses

import pytest

from previewit.domain.anonymity import AnonymityPolicy, RevealAt, Viewer, is_revealed

ORG, A, R, X = Viewer.ORGANIZER, Viewer.AUTHOR, Viewer.REVIEWER, Viewer.OTHER_REVIEWER

PRESETS = {
    "open": AnonymityPolicy.open,
    "single_blind_reviewers_hidden": AnonymityPolicy.single_blind_reviewers_hidden,
    "single_blind_authors_hidden": AnonymityPolicy.single_blind_authors_hidden,
    "double_blind": AnonymityPolicy.double_blind,
}

# preset -> {viewer: may that viewer see the AUTHOR's identity?}
SEES_AUTHOR = {
    "open": {ORG: True, A: True, R: True, X: True},
    "single_blind_reviewers_hidden": {ORG: True, A: True, R: True, X: True},
    "single_blind_authors_hidden": {ORG: True, A: True, R: False, X: False},
    "double_blind": {ORG: True, A: True, R: False, X: False},
}

# preset -> {viewer: may that viewer see the REVIEWER's identity?}
SEES_REVIEWER = {
    "open": {ORG: True, A: True, R: True, X: True},
    "single_blind_reviewers_hidden": {ORG: True, A: False, R: True, X: True},
    "single_blind_authors_hidden": {ORG: True, A: True, R: True, X: True},
    "double_blind": {ORG: True, A: False, R: True, X: False},
}


def _cases(table):
    return [(p, v, expected) for p, row in table.items() for v, expected in row.items()]


@pytest.mark.parametrize(("preset", "viewer", "expected"), _cases(SEES_AUTHOR))
def test_who_can_see_the_author(preset, viewer, expected):
    assert PRESETS[preset]().may_see_author(viewer) is expected


@pytest.mark.parametrize(("preset", "viewer", "expected"), _cases(SEES_REVIEWER))
def test_who_can_see_the_reviewer(preset, viewer, expected):
    assert PRESETS[preset]().may_see_reviewer(viewer) is expected


@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("viewer", list(Viewer))
def test_reveal_lifts_every_restriction(preset, viewer):
    policy = PRESETS[preset]()
    assert policy.may_see_author(viewer, revealed=True)
    assert policy.may_see_reviewer(viewer, revealed=True)


def test_single_blind_presets_are_mirror_images():
    rh = AnonymityPolicy.single_blind_reviewers_hidden()
    ah = AnonymityPolicy.single_blind_authors_hidden()
    assert rh.author_visible_to_reviewer and not rh.reviewer_visible_to_author
    assert ah.reviewer_visible_to_author and not ah.author_visible_to_reviewer


def test_presets_are_all_distinct():
    assert len({factory() for factory in PRESETS.values()}) == len(PRESETS)


def test_default_reveal_is_never():
    assert all(factory().reveal_at is RevealAt.NEVER for factory in PRESETS.values())


def test_policy_is_immutable():
    policy = AnonymityPolicy.double_blind()
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.author_visible_to_reviewer = True  # type: ignore[misc]


def test_policy_equality_and_replace():
    custom = dataclasses.replace(AnonymityPolicy.double_blind(), reviewer_visible_to_author=True)
    assert custom == AnonymityPolicy(False, True, False, RevealAt.NEVER)
    assert custom != AnonymityPolicy.double_blind()


@pytest.mark.parametrize(
    ("reveal_at", "round_closed", "decided", "expected"),
    [
        (RevealAt.NEVER, False, False, False),
        (RevealAt.NEVER, True, False, False),
        (RevealAt.NEVER, False, True, False),
        (RevealAt.NEVER, True, True, False),
        (RevealAt.ROUND_CLOSE, False, False, False),
        (RevealAt.ROUND_CLOSE, True, False, True),
        (RevealAt.ROUND_CLOSE, False, True, False),
        (RevealAt.ROUND_CLOSE, True, True, True),
        (RevealAt.DECISION, False, False, False),
        (RevealAt.DECISION, True, False, False),
        (RevealAt.DECISION, False, True, True),
        (RevealAt.DECISION, True, True, True),
    ],
)
def test_is_revealed_truth_table(reveal_at, round_closed, decided, expected):
    assert is_revealed(reveal_at, round_closed=round_closed, decided=decided) is expected


def test_enum_values_are_stable_because_they_will_be_persisted():
    assert {m.value for m in RevealAt} == {"never", "round_close", "decision"}
    assert RevealAt("round_close") is RevealAt.ROUND_CLOSE
    assert {m.value for m in Viewer} == {"organizer", "author", "reviewer", "other_reviewer"}
