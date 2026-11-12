import pytest

from previewit.adapters.auth.base import AuthFailed
from previewit.adapters.auth.haka import PERSISTENT, claims_from_haka
from previewit.domain.identity import Email, Provider

IDP = "https://idp.jyu.fi/idp/shibboleth"


def _ava(**kw: list[str]) -> dict[str, list[str]]:
    return {k: v for k, v in kw.items()}


def test_prefers_eduperson_unique_id_and_namespaces_it_by_idp():
    claims = claims_from_haka(
        IDP,
        _ava(
            eduPersonUniqueId=["abc123@jyu.fi"],
            eduPersonPrincipalName=["ann@jyu.fi"],
            mail=["ann@jyu.fi"],
            schacHomeOrganization=["jyu.fi"],
            displayName=["Ann Teacher"],
        ),
        name_id="persistent-id",
        name_id_format=PERSISTENT,
    )
    assert claims.provider is Provider.HAKA
    assert claims.subject == f"{IDP}!abc123@jyu.fi"
    assert claims.email == Email("ann@jyu.fi") and claims.email_verified
    assert claims.display_name == "Ann Teacher"


def test_falls_back_to_persistent_nameid_then_eppn():
    persistent = claims_from_haka(
        IDP, _ava(eduPersonPrincipalName=["ann@jyu.fi"]), "pid-1", PERSISTENT
    )
    assert persistent.subject == f"{IDP}!pid-1"
    transient = claims_from_haka(
        IDP,
        _ava(eduPersonPrincipalName=["ann@jyu.fi"]),
        "tmp-1",
        "urn:oasis:names:tc:SAML:2.0:nameid-format:transient",
    )
    assert transient.subject == f"{IDP}!ann@jyu.fi"


def test_no_stable_identifier_fails():
    with pytest.raises(AuthFailed):
        claims_from_haka(IDP, _ava(mail=["ann@jyu.fi"]), None, None)


def test_same_identifier_at_two_idps_is_two_people():
    ava = _ava(eduPersonUniqueId=["x@y.fi"])
    a = claims_from_haka("https://idp-a", ava, None, None)
    b = claims_from_haka("https://idp-b", ava, None, None)
    assert a.subject != b.subject


@pytest.mark.parametrize(
    ("mail", "home", "verified"),
    [
        ("ann@jyu.fi", "jyu.fi", True),
        ("ann@student.jyu.fi", "jyu.fi", True),  # subdomain of the home organisation
        ("ann@gmail.com", "jyu.fi", False),  # an address the institution cannot vouch for
        ("ann@evil-jyu.fi", "jyu.fi", False),  # suffix match without a dot boundary
        ("ann@jyu.fi", None, False),  # no home organisation released
        ("ANN@JYU.FI", "JYU.fi", True),
    ],
)
def test_email_is_verified_only_within_the_home_organisation(mail, home, verified):
    ava = _ava(eduPersonUniqueId=["u@jyu.fi"], mail=[mail])
    if home:
        ava["schacHomeOrganization"] = [home]
    assert claims_from_haka(IDP, ava, None, None).email_verified is verified


def test_missing_or_bad_mail_means_no_email():
    for mail in ([], ["not an email"]):
        claims = claims_from_haka(IDP, _ava(eduPersonUniqueId=["u@jyu.fi"], mail=mail), None, None)
        assert claims.email is None and not claims.email_verified


def test_display_name_falls_back_to_cn():
    claims = claims_from_haka(IDP, _ava(eduPersonUniqueId=["u"], cn=["Ann T"]), None, None)
    assert claims.display_name == "Ann T"
