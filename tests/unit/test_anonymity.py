from hypothesis import given
from hypothesis import strategies as st

from previewit.domain.anonymity import AnonymityPolicy, RevealAt, Viewer, is_revealed

policies = st.builds(
    AnonymityPolicy,
    st.booleans(),
    st.booleans(),
    st.booleans(),
    st.sampled_from(RevealAt),
)


def test_open_review_shows_everyone_to_everyone():
    p = AnonymityPolicy.open()
    for v in Viewer:
        assert p.may_see_author(v)
        assert p.may_see_reviewer(v)


def test_double_blind_hides_both_directions_from_participants():
    p = AnonymityPolicy.double_blind()
    assert not p.may_see_author(Viewer.REVIEWER)
    assert not p.may_see_reviewer(Viewer.AUTHOR)
    assert not p.may_see_reviewer(Viewer.OTHER_REVIEWER)


def test_single_blind_reviewers_hidden_only_hides_reviewer_from_author():
    p = AnonymityPolicy.single_blind_reviewers_hidden()
    assert p.may_see_author(Viewer.REVIEWER)
    assert not p.may_see_reviewer(Viewer.AUTHOR)


def test_single_blind_authors_hidden_is_the_opposite_direction():
    p = AnonymityPolicy.single_blind_authors_hidden()
    assert not p.may_see_author(Viewer.REVIEWER)
    assert p.may_see_reviewer(Viewer.AUTHOR)


@given(policies, st.sampled_from(Viewer))
def test_revealed_identities_are_visible_to_all(policy, viewer):
    assert policy.may_see_author(viewer, revealed=True)
    assert policy.may_see_reviewer(viewer, revealed=True)


@given(policies)
def test_organizers_and_own_side_always_see_what_they_must(policy):
    assert policy.may_see_author(Viewer.ORGANIZER) and policy.may_see_reviewer(Viewer.ORGANIZER)
    assert policy.may_see_author(Viewer.AUTHOR)  # authors know their own work
    assert policy.may_see_reviewer(Viewer.REVIEWER)  # reviewers know their own review


def test_reveal_timing():
    assert not is_revealed(RevealAt.NEVER, round_closed=True, decided=True)
    assert is_revealed(RevealAt.ROUND_CLOSE, round_closed=True, decided=False)
    assert not is_revealed(RevealAt.DECISION, round_closed=True, decided=False)
    assert is_revealed(RevealAt.DECISION, round_closed=False, decided=True)
