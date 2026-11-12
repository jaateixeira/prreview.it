"""SAML round trip against a local pysaml2 IdP (no network, no real Haka).

Proves: the SP builds a valid AuthnRequest, accepts a correctly signed assertion for
that request, and rejects unsolicited, replayed and tampered responses.
"""

import base64
import datetime
import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("saml2")
if shutil.which("xmlsec1") is None:
    pytest.skip("xmlsec1 binary not installed", allow_module_level=True)

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from saml2 import BINDING_HTTP_POST, BINDING_HTTP_REDIRECT
from saml2.config import IdPConfig
from saml2.metadata import create_metadata_string
from saml2.response import SignatureError, UnsolicitedResponse
from saml2.server import Server

from previewit.adapters.auth.haka import HakaConfig, HakaProvider
from previewit.domain.identity import Email, Provider

SP_ID = "https://prreview.example/saml/sp"
ACS = "https://prreview.example/auth/haka/callback"
IDP_ID = "https://idp.jyu.example/idp/shibboleth"
SSO = "https://idp.jyu.example/idp/profile/SAML2/Redirect/SSO"


def _keypair(directory: Path, name: str) -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    key_path, cert_path = directory / f"{name}.key", directory / f"{name}.crt"
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return str(key_path), str(cert_path)


class Federation:
    """A local IdP and an SP that has loaded each other's metadata."""

    def __init__(self, tmp_path: Path) -> None:
        sp_key, sp_cert = _keypair(tmp_path, "sp")
        idp_key, idp_cert = _keypair(tmp_path, "idp")
        xmlsec = shutil.which("xmlsec1")
        idp_dict = {
            "entityid": IDP_ID,
            "xmlsec_binary": xmlsec,
            "key_file": idp_key,
            "cert_file": idp_cert,
            "service": {
                "idp": {
                    "endpoints": {"single_sign_on_service": [(SSO, BINDING_HTTP_REDIRECT)]},
                }
            },
        }
        idp_conf = IdPConfig()
        idp_conf.load(idp_dict)
        idp_metadata = tmp_path / "idp-metadata.xml"
        idp_metadata.write_bytes(_as_bytes(create_metadata_string(None, config=idp_conf)))

        sp_config = HakaConfig(
            sp_entity_id=SP_ID,
            acs_url=ACS,
            cert_file=sp_cert,
            key_file=sp_key,
            metadata_file=str(idp_metadata),
            idp_entity_id=IDP_ID,
        )
        self.provider = HakaProvider(sp_config)
        sp_metadata = tmp_path / "sp-metadata.xml"
        sp_metadata.write_bytes(self.provider.metadata_xml())
        idp_with_sp = IdPConfig()
        idp_with_sp.load({**idp_dict, "metadata": {"local": [str(sp_metadata)]}})
        self.idp = Server(config=idp_with_sp)

    def login(self, identity: dict[str, list[str]], *, sign: bool = True) -> tuple[str, str]:
        """Do the SP -> IdP leg, answer as the IdP, and return (request_id, SAMLResponse)."""
        location, request_id = self.provider._authn_request(IDP_ID)  # type: ignore[reportPrivateUsage]
        query = parse_qs(urlparse(location).query)
        req = self.idp.parse_authn_request(query["SAMLRequest"][0], BINDING_HTTP_REDIRECT)
        assert req is not None
        response = self.idp.create_authn_response(
            identity=identity,
            in_response_to=req.message.id,
            destination=ACS,
            sp_entity_id=SP_ID,
            name_id_policy=req.message.name_id_policy,
            userid="ignored",
            authn={
                "class_ref": "urn:oasis:names:tc:SAML:2.0:ac:classes:Password",
                "authn_auth": IDP_ID,
            },
            sign_assertion=sign,
            sign_response=False,
        )
        return request_id, base64.b64encode(str(response).encode()).decode()


def _as_bytes(value: str | bytes) -> bytes:
    return value.encode() if isinstance(value, str) else value


IDENTITY = {
    "eduPersonUniqueId": ["abc123@jyu.example"],
    "mail": ["ann@jyu.example"],
    "schacHomeOrganization": ["jyu.example"],
    "displayName": ["Ann Teacher"],
}


@pytest.fixture
def federation(tmp_path: Path) -> Federation:
    return Federation(tmp_path)


def test_signed_assertion_for_our_request_logs_the_user_in(federation: Federation):
    request_id, saml = federation.login(IDENTITY)
    claims, used = federation.provider._parse(saml, {request_id: "/"})  # type: ignore[reportPrivateUsage]
    assert used == request_id
    assert claims.provider is Provider.HAKA
    assert claims.subject == f"{IDP_ID}!abc123@jyu.example"
    assert claims.email == Email("ann@jyu.example") and claims.email_verified
    assert claims.display_name == "Ann Teacher"


def test_response_to_a_request_we_never_made_is_rejected(federation: Federation):
    _, saml = federation.login(IDENTITY)
    with pytest.raises(UnsolicitedResponse):
        federation.provider._parse(saml, {"some-other-id": "/"})  # type: ignore[reportPrivateUsage]


def test_unsolicited_response_is_rejected(federation: Federation):
    _, saml = federation.login(IDENTITY)
    with pytest.raises(UnsolicitedResponse):
        federation.provider._parse(saml, {})  # type: ignore[reportPrivateUsage]


def test_unsigned_assertion_is_rejected(federation: Federation):
    request_id, saml = federation.login(IDENTITY, sign=False)
    with pytest.raises(SignatureError):
        federation.provider._parse(saml, {request_id: "/"})  # type: ignore[reportPrivateUsage]


def test_tampered_assertion_is_rejected(federation: Federation):
    request_id, saml = federation.login(IDENTITY)
    xml = base64.b64decode(saml).decode().replace("ann@jyu.example", "boss@jyu.example")
    forged = base64.b64encode(xml.encode()).decode()
    with pytest.raises(SignatureError):
        federation.provider._parse(forged, {request_id: "/"})  # type: ignore[reportPrivateUsage]


def test_sp_metadata_names_our_acs_endpoint(federation: Federation):
    xml = federation.provider.metadata_xml().decode()
    assert SP_ID in xml and ACS in xml and BINDING_HTTP_POST in xml
