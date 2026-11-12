from urllib.parse import parse_qs, urlparse

from previewit.adapters.auth.haka import HakaConfig, HakaProvider
from previewit.domain.identity import Provider
from tests.integration.web_fakes import FakeProvider, csrf_token, make_client

PASSWORD = "correct horse battery"


def _signup(client, email="ann@x.fi", password=PASSWORD, name="Ann", next_="/account"):
    token = csrf_token(client, "/signup")
    return client.post(
        "/signup",
        data={"csrf": token, "email": email, "password": password, "name": name, "next": next_},
    )


# --- pages ---------------------------------------------------------------------


def test_login_page_offers_only_configured_providers():
    client, _ = make_client({Provider.GOOGLE: FakeProvider()})
    page = client.get("/login").text
    assert "/auth/google/login" in page
    assert "/auth/apple/login" not in page and "/auth/haka/login" not in page
    assert "/auth/google/login" not in make_client()[0].get("/login").text


def test_nav_reflects_login_state():
    client, _ = make_client()
    assert 'href="/login"' in client.get("/").text
    _signup(client)
    home = client.get("/").text
    assert 'href="/account"' in home and 'href="/login"' not in home


# --- password flow ---------------------------------------------------------------


def test_signup_logs_in_and_the_session_cookie_is_locked_down():
    client, _ = make_client()
    r = _signup(client)
    assert r.status_code == 303 and r.headers["location"] == "/account"
    cookie = next(c for c in r.headers.get_list("set-cookie") if c.startswith("pv_session="))
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Secure" not in cookie
    assert "ann@x.fi" in client.get("/account").text


def test_session_cookie_is_secure_on_https_deployments():
    client, _ = make_client(base_url="https://prreview.example")
    r = _signup(client)
    cookie = next(c for c in r.headers.get_list("set-cookie") if c.startswith("pv_session="))
    assert "Secure" in cookie


def test_account_requires_login():
    client, _ = make_client()
    r = client.get("/account")
    assert r.status_code == 303 and r.headers["location"] == "/login?next=%2Faccount"


def test_logout_ends_the_session():
    client, _ = make_client()
    _signup(client)
    token = csrf_token(client, "/account")
    r = client.post("/logout", data={"csrf": token})
    assert r.status_code == 303
    assert client.get("/account").status_code == 303


def test_login_with_right_and_wrong_password():
    client, _ = make_client()
    _signup(client)
    client.cookies.clear()
    token = csrf_token(client, "/login")
    bad = client.post(
        "/login", data={"csrf": token, "email": "ann@x.fi", "password": "nope-nope-nope"}
    )
    assert bad.status_code == 400 and "Wrong email or password" in bad.text
    unknown = client.post("/login", data={"csrf": token, "email": "x@y.fi", "password": PASSWORD})
    assert unknown.status_code == 400 and "Wrong email or password" in unknown.text
    ok = client.post("/login", data={"csrf": token, "email": "ann@x.fi", "password": PASSWORD})
    assert ok.status_code == 303 and ok.headers["location"] == "/"


def test_signup_errors_are_reported_in_the_page():
    client, _ = make_client()
    weak = _signup(client, password="short")
    assert weak.status_code == 400 and "at least 10" in weak.text
    assert _signup(client, email="not-an-email").status_code == 400
    assert _signup(client).status_code == 303
    client.cookies.clear()
    taken = _signup(client)
    assert taken.status_code == 400 and "already exists" in taken.text


def test_next_only_follows_local_paths():
    client, _ = make_client()
    for evil in (
        "//evil.example",
        "https://evil.example",
        "/\\evil.example",
        "javascript:alert(1)",
    ):
        client.cookies.clear()
        r = _signup(client, email=f"{abs(hash(evil))}@x.fi", next_=evil)
        assert r.headers["location"] == "/", evil


# --- CSRF and cookies -----------------------------------------------------------------


def test_posts_without_a_valid_csrf_token_are_refused():
    client, _ = make_client()
    csrf_token(client, "/login")  # establishes the cookie
    form = {"email": "a@x.fi", "password": PASSWORD}
    assert client.post("/login", data=form).status_code == 403
    assert client.post("/login", data={**form, "csrf": "forged"}).status_code == 403
    assert client.post("/logout", data={}).status_code == 403


def test_posts_from_another_origin_are_refused():
    client, _ = make_client()
    token = csrf_token(client, "/login")
    r = client.post(
        "/login",
        data={"csrf": token, "email": "a@x.fi", "password": PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403


def test_a_tampered_session_cookie_means_anonymous():
    client, _ = make_client()
    _signup(client)
    client.cookies.set("pv_session", "u1.forged.signature")
    assert client.get("/account").status_code == 303


# --- external provider flow -----------------------------------------------------------------


def test_external_login_round_trip_creates_then_reuses_the_account():
    client, auth = make_client({Provider.GOOGLE: FakeProvider()})
    start = client.get("/auth/google/login?next=/account")
    assert start.status_code == 303
    callback = client.get(start.headers["location"].replace("http://testserver", ""))
    assert callback.status_code == 303 and callback.headers["location"] == "/account"
    assert "ann@x.fi" in client.get("/account").text
    client.cookies.clear()
    again = client.get(
        client.get("/auth/google/login").headers["location"].replace("http://testserver", "")
    )
    assert again.status_code == 303
    account = client.get("/account").text
    assert "ann@x.fi" in account and "Google" in account
    user = auth.login_with_external(FakeProvider().claims)
    assert user.id == "u1"  # same account both times


def test_callback_with_a_bad_state_is_an_error_page_not_a_login():
    client, _ = make_client({Provider.GOOGLE: FakeProvider()})
    client.get("/auth/google/login")
    r = client.get("/auth/google/callback?state=forged")
    assert r.status_code == 400 and "could not be completed" in r.text
    assert client.get("/account").status_code == 303


def test_unconfigured_or_unknown_providers_are_404():
    client, _ = make_client({Provider.GOOGLE: FakeProvider()})
    assert client.get("/auth/apple/login").status_code == 404
    assert client.get("/auth/nonsense/login").status_code == 404
    assert client.get("/auth/apple/callback").status_code == 404


def test_haka_without_a_chosen_idp_goes_to_the_discovery_service_and_back():
    haka = HakaProvider(
        HakaConfig(
            sp_entity_id="https://prreview.example/saml/sp",
            acs_url="http://testserver/auth/haka/callback",
            cert_file="c",
            key_file="k",
            metadata_file="m.xml",
            discovery_url="https://wayf.example/ds",
        )
    )
    client, _ = make_client({Provider.HAKA: haka})
    r = client.get("/auth/haka/login?next=/account")
    assert r.status_code == 303
    location = urlparse(r.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == "https://wayf.example/ds"
    query = parse_qs(location.query)
    assert query["entityID"] == ["https://prreview.example/saml/sp"]
    assert query["return"] == ["http://testserver/auth/haka/login?next=%2Faccount"]


def test_only_providers_that_publish_metadata_have_a_metadata_page():
    client, _ = make_client({Provider.GOOGLE: FakeProvider()})
    assert client.get("/auth/google/metadata").status_code == 404
