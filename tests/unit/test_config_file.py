import logging
import os
import textwrap
from pathlib import Path

import pytest

from previewit.adapters.settings import ConfigError, load_settings
from previewit.domain.policy import DEFAULT_POLICY, Action


def write(tmp_path: Path, text: str, name: str = "previewit.toml", mode: int = 0o600) -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(text))
    path.chmod(mode)
    return path


def test_no_file_means_environment_only_with_safe_defaults():
    s = load_settings({}, search=[])
    assert s.base_url == "http://localhost:8000" and s.secret_key
    assert s.verification_policy == DEFAULT_POLICY


def test_the_file_sets_everything(tmp_path: Path):
    path = write(
        tmp_path,
        """
        [server]
        base_url = "https://prreview.example"
        secret_key = "s3cret"

        [database]
        url = "postgresql+psycopg://u:p@db/previewit"

        [mail]
        smtp_host = "smtp.example"
        smtp_port = 465
        smtp_security = "ssl"
        from = "Previewit <no-reply@prreview.example>"

        [login.google]
        client_id = "gid"
        client_secret = "gsecret"

        [login.haka]
        entity_id = "https://prreview.example/saml/sp"
        discovery_url = "https://haka.example/ds"

        [policy]
        require_verified_email_for = ["review", "submit"]
        """,
    )
    s = load_settings({"PREVIEWIT_CONFIG": str(path)})
    assert s.base_url == "https://prreview.example" and s.secret_key == "s3cret"
    assert s.database_url.startswith("postgresql+psycopg://")
    assert (s.smtp_host, s.smtp_port, s.smtp_security) == ("smtp.example", 465, "ssl")
    assert s.mail_from == "Previewit <no-reply@prreview.example>"
    assert (s.google_client_id, s.google_client_secret) == ("gid", "gsecret")
    assert s.haka_entity_id == "https://prreview.example/saml/sp"
    assert s.haka_discovery_url == "https://haka.example/ds"
    assert s.verification_policy.required_for == {Action.REVIEW, Action.SUBMIT}


def test_environment_overrides_the_file(tmp_path: Path):
    path = write(tmp_path, '[server]\nbase_url = "http://from-file"\n')
    env = {"PREVIEWIT_CONFIG": str(path), "PREVIEWIT_BASE_URL": "http://from-env"}
    assert load_settings(env).base_url == "http://from-env"


def test_the_policy_can_be_set_to_nothing_or_everything(tmp_path: Path):
    none = write(tmp_path, "[policy]\nrequire_verified_email_for = []\n", "a.toml")
    assert load_settings({"PREVIEWIT_CONFIG": str(none)}).verification_policy.required_for == set()
    env = {"PREVIEWIT_CONFIG": str(none), "PREVIEWIT_REQUIRE_VERIFIED_EMAIL_FOR": "join, invite"}
    assert load_settings(env).verification_policy.required_for == {Action.JOIN, Action.INVITE}
    off = {"PREVIEWIT_REQUIRE_VERIFIED_EMAIL_FOR": ""}
    assert load_settings(off, search=[]).verification_policy.required_for == set()


def test_unknown_keys_sections_and_actions_are_errors(tmp_path: Path):
    typo = write(tmp_path, '[server]\nbase_ulr = "x"\n', "a.toml")
    with pytest.raises(ConfigError, match=r"server\.base_ulr"):
        load_settings({"PREVIEWIT_CONFIG": str(typo)})
    section = write(tmp_path, '[serverr]\nbase_url = "x"\n', "b.toml")
    with pytest.raises(ConfigError, match="serverr"):
        load_settings({"PREVIEWIT_CONFIG": str(section)})
    action = write(tmp_path, '[policy]\nrequire_verified_email_for = ["reveiw"]\n', "c.toml")
    with pytest.raises(ConfigError, match="reveiw"):
        load_settings({"PREVIEWIT_CONFIG": str(action)})
    env_action = {"PREVIEWIT_REQUIRE_VERIFIED_EMAIL_FOR": "reveiw"}
    with pytest.raises(ConfigError, match="reveiw"):
        load_settings(env_action, search=[])


def test_wrong_types_and_broken_toml_are_errors(tmp_path: Path):
    bad_type = write(tmp_path, '[mail]\nsmtp_port = "many"\n', "a.toml")
    with pytest.raises(ConfigError, match=r"smtp_port"):
        load_settings({"PREVIEWIT_CONFIG": str(bad_type)})
    not_list = write(tmp_path, '[policy]\nrequire_verified_email_for = "review"\n', "b.toml")
    with pytest.raises(ConfigError, match="require_verified_email_for"):
        load_settings({"PREVIEWIT_CONFIG": str(not_list)})
    broken = write(tmp_path, "[server\n", "c.toml")
    with pytest.raises(ConfigError, match=r"c\.toml"):
        load_settings({"PREVIEWIT_CONFIG": str(broken)})


def test_an_explicit_missing_file_is_an_error_but_a_missing_default_is_not(tmp_path: Path):
    with pytest.raises(ConfigError, match=r"nope\.toml"):
        load_settings({"PREVIEWIT_CONFIG": str(tmp_path / "nope.toml")})
    assert load_settings({}, search=[tmp_path / "absent.toml"]).secret_key


def test_the_default_search_path_is_used(tmp_path: Path):
    path = write(tmp_path, '[server]\nbase_url = "http://found"\n')
    assert load_settings({}, search=[tmp_path / "nothing.toml", path]).base_url == "http://found"


def test_relative_paths_are_relative_to_the_config_file(tmp_path: Path):
    path = write(
        tmp_path,
        """
        [login.haka]
        cert_file = "keys/sp.crt"
        key_file = "/abs/sp.key"
        metadata_file = "idp.xml"
        """,
    )
    s = load_settings({"PREVIEWIT_CONFIG": str(path)})
    assert s.haka_cert_file == str(tmp_path / "keys/sp.crt")
    assert s.haka_key_file == "/abs/sp.key"
    assert s.haka_metadata_file == str(tmp_path / "idp.xml")


def test_secrets_can_live_in_separate_files(tmp_path: Path):
    (tmp_path / "secret").write_text("from-a-file\n")
    (tmp_path / "AuthKey.p8").write_text("-----BEGIN PRIVATE KEY-----\nabc\n")
    path = write(
        tmp_path,
        """
        [server]
        secret_key_file = "secret"
        [login.apple]
        client_id = "c"
        team_id = "t"
        key_id = "k"
        private_key_file = "AuthKey.p8"
        """,
    )
    s = load_settings({"PREVIEWIT_CONFIG": str(path)})
    assert s.secret_key == "from-a-file"
    assert s.apple_private_key is not None and "BEGIN PRIVATE KEY" in s.apple_private_key


def test_both_inline_and_file_for_one_secret_is_an_error(tmp_path: Path):
    path = write(tmp_path, '[server]\nsecret_key = "a"\nsecret_key_file = "b"\n')
    with pytest.raises(ConfigError, match="secret_key"):
        load_settings({"PREVIEWIT_CONFIG": str(path)})


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_a_world_readable_file_with_secrets_is_warned_about(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    path = write(tmp_path, '[server]\nsecret_key = "x"\n', mode=0o644)
    with caplog.at_level(logging.WARNING):
        load_settings({"PREVIEWIT_CONFIG": str(path)})
    assert "chmod 600" in caplog.text
    caplog.clear()
    quiet = write(tmp_path, '[server]\nbase_url = "http://x"\n', "q.toml", mode=0o644)
    with caplog.at_level(logging.WARNING):
        load_settings({"PREVIEWIT_CONFIG": str(quiet)})
    assert "chmod" not in caplog.text  # nothing secret inside, nothing to warn about
