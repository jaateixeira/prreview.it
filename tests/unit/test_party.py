import dataclasses

import pytest

from previewit.domain.party import GroupParty, Party, UserParty


def test_equal_ids_make_equal_parties():
    assert UserParty("u1") == UserParty("u1")
    assert GroupParty("g1") == GroupParty("g1")


def test_user_and_group_with_the_same_id_are_different_parties():
    assert UserParty("1") != GroupParty("1")


def test_parties_are_hashable_and_usable_in_sets_and_dicts():
    parties: set[Party] = {UserParty("u1"), UserParty("u1"), GroupParty("g1")}
    assert len(parties) == 2
    assert {UserParty("u1"): "reviewer"}[UserParty("u1")] == "reviewer"


@pytest.mark.parametrize("party", [UserParty("u1"), GroupParty("g1")])
def test_parties_are_immutable(party):
    field = dataclasses.fields(party)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(party, field, "other")


def test_pattern_matching_distinguishes_party_kinds():
    def kind(p: Party) -> str:
        match p:
            case UserParty():
                return "user"
            case GroupParty():
                return "group"

    assert kind(UserParty("u")) == "user"
    assert kind(GroupParty("g")) == "group"
