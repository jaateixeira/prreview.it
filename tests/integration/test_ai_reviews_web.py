"""AI reviews on the web (ADR 0025): the request form suggests models and asks them; the work's
page shows their reviews to the author and the organizers only. Keys never come back."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from tests.integration.test_quick_review_web import NEW, organizer
from tests.integration.test_request_before_sign_in_web import saved_link
from tests.integration.test_tenancy_web import post, signup
from tests.integration.web_fakes import Harness, csrf_token, make_harness
from tests.unit.test_ai_models import CHEAP, LOCAL
from tests.unit.test_ai_reviews_service import SONNET
from tests.unit.test_reading_text import pdf_with_text
from tests.unit.test_webpage_plugin import ESSAY

KEY = "sk-ant-api-0123456789-secret"


def suggest(client: TestClient, data: dict[str, str], files=None):
    return client.post(
        "/review/ai/suggest", data={"csrf": csrf_token(client, NEW), **data}, files=files
    )


def send(client: TestClient, data: dict[str, str | list[str]], files=None):
    fields = {"csrf": csrf_token(client, NEW), "title": "My essay", "text": "Please read me.",
              "emails": "rita@x.fi"}  # fmt: skip
    return client.post("/review", data={**fields, **data}, files=files)


def submission_of(response) -> str:
    found = re.search(r'href="/submissions/([^"#]+)#ai-reviews"', response.text)
    assert found, response.text
    return found.group(1)


def words(text: str) -> str:
    return " ".join(text.split())


def every_page_and_mail(h: Harness, *pages: str) -> str:
    return "\n".join([*pages, *(m[2] for m in h.outbox.sent), repr(h.ai_repo._rows)])


# -- suggestions -----------------------------------------------------------------------------------


def test_the_form_offers_ai_reviews_and_a_way_for_organizers() -> None:
    h, client = organizer()
    page = client.get(NEW).text
    assert "Feedback from AI models too?" in page and "Yes, suggest AI models" in page
    assert 'href="/spaces">Start here</a>' in page
    assert 'href="/signup?next=%2Fspaces">Start here' in h.new_client().get(NEW).text
    without = make_harness(with_ai=False).new_client().get(NEW).text
    assert "Feedback from AI models too?" not in without


def test_saying_yes_suggests_three_models_with_flags_and_prices() -> None:
    h, client = organizer()
    shown = suggest(client, {"text": "Please read my essay. " * 50})
    assert shown.status_code == 200
    names = re.findall(r'name="ai_model" value="([^"]+)"', shown.text)
    assert names[:3] == [LOCAL.key, SONNET.key, CHEAP.key]
    assert "See more models (1)" in shown.text  # the light one
    assert "Free" in shown.text and "Previewit&#39;s own server, Finland" in shown.text
    assert "\U0001f1eb\U0001f1ee" in shown.text  # Finland's flag
    assert "With your Anthropic API key: <strong>about" in shown.text
    assert "Without a key: <strong>about €0.04</strong> from your credit" in words(shown.text)
    assert "Needs your key: Previewit cannot pay for this one." in words(shown.text)  # Mistral
    assert "Your credit: <strong>€0.00</strong>" in words(shown.text)
    assert 'type="password" name="ai_key_anthropic"' in shown.text
    assert "Leave it empty to pay from your credit." in words(shown.text)
    assert h.ai_writer.calls == []  # suggesting asks no model anything


def test_a_pdf_is_measured_and_a_missing_work_is_asked_for() -> None:
    _, client = organizer()
    pdf = suggest(client, {}, files={"file": ("a.pdf", pdf_with_text("Words"), "application/pdf")})
    assert 'value="local/' in pdf.text
    empty = suggest(client, {})
    assert "Add your work above first" in empty.text and "ai_model" not in empty.text


def test_a_visitors_web_page_is_not_fetched_to_suggest_models() -> None:
    h = make_harness()
    visitor = h.new_client()
    shown = suggest(visitor, {"web_address": ESSAY.address})
    assert "the prices assume a long article" in words(shown.text)
    assert h.pages.read == [] and h.pages.checked == []


# -- asking from the form --------------------------------------------------------------------------


def test_the_author_sends_the_work_to_people_and_to_two_models() -> None:
    h, client = organizer()
    done = send(
        client,
        {"ai_model": [LOCAL.key, SONNET.key], "ai_key_anthropic": KEY, "cover_letter": "Be kind"},
    )
    assert done.status_code == 200, done.text
    assert "Local/Qwen3:8B, Anthropic/Sonnet are reading your work" in words(done.text)
    submission = submission_of(done)
    assert [(model, key) for model, key, _ in h.ai_writer.calls] == [
        (LOCAL.key, ""),
        (SONNET.key, KEY),
    ]
    assert "Be kind" in h.ai_writer.calls[0][2].user
    work = client.get(f"/submissions/{submission}")
    assert 'hx-get="/submissions/' in work.text and 'id="ai-reviews"' in work.text
    section = client.get(f"/submissions/{submission}/ai")
    assert section.status_code == 200 and section.text.count('class="ai-review"') == 2
    assert "A clear essay." in section.text and "Only the author and the organizers" in section.text
    assert KEY not in every_page_and_mail(h, done.text, work.text, section.text)
    assert any("is ready" in subject for _, subject, _ in h.outbox.sent)


def test_a_paid_model_without_a_key_stops_the_form_before_anything_is_made() -> None:
    h, client = organizer()
    refused = send(client, {"ai_model": [SONNET.key]})
    assert refused.status_code == 400
    assert "Your credit is €0.00" in refused.text  # no key, no credit
    assert f'value="{SONNET.key}" checked' in refused.text  # the choice is kept
    assert 'value="My essay"' in refused.text and "Review requested" not in refused.text
    bad = send(client, {"ai_model": [SONNET.key], "ai_key_anthropic": "two words"})
    assert "does not look right" in bad.text and "two words" not in bad.text
    assert h.ai_writer.calls == []


def test_a_visitors_choice_waits_but_their_key_is_dropped() -> None:
    h = make_harness()
    visitor = h.new_client()
    sent = send(visitor, {"ai_model": [LOCAL.key, SONNET.key], "ai_key_anthropic": KEY})
    link = saved_link(sent)
    signup(visitor, "vera@x.fi", "Vera Visitor", next_=link)
    form = visitor.get(link)
    assert "Your choice of models was kept" in form.text
    assert (
        f'value="{LOCAL.key}" checked' in form.text and f'value="{SONNET.key}" checked' in form.text
    )
    assert KEY not in form.text and KEY not in repr(h.prepared_repo._rows)
    token = link.rsplit("/", 1)[1]
    done = post(
        visitor, "/review",
        {"title": "My essay", "text": "Please read me.", "emails": "rita@x.fi", "prepared": token,
         "ai_model": [LOCAL.key]},
        page=link,
    )  # fmt: skip
    assert done.status_code == 200 and "is reading your work" in words(done.text)


# -- the work's page -------------------------------------------------------------------------------


def test_the_author_asks_more_models_from_the_works_page() -> None:
    h, client = organizer()
    submission = submission_of(send(client, {"ai_model": [LOCAL.key]}))
    ask = client.get(f"/submissions/{submission}/ai/ask")
    assert ask.status_code == 200 and "Ask them" in ask.text
    page = f"/submissions/{submission}"
    refused = post(client, f"/submissions/{submission}/ai", {"ai_model": [CHEAP.key]}, page=page)
    assert "Mistral/Large needs your key." in refused.text and "Ask them" in refused.text
    asked = post(
        client, f"/submissions/{submission}/ai",
        {"ai_model": [SONNET.key], "ai_key_anthropic": KEY, "ai_note": "Look at the ending"},
        page=page,
    )  # fmt: skip
    assert asked.status_code == 200 and asked.text.count('class="ai-review"') == 2
    assert "Look at the ending" in h.ai_writer.calls[-1][2].user
    assert KEY not in asked.text


def test_a_review_still_being_written_is_checked_again_every_few_seconds() -> None:
    h, client = organizer()
    h.ai_jobs.hold = True
    submission = submission_of(send(client, {"ai_model": [LOCAL.key]}))
    listing = client.get(f"/submissions/{submission}/ai/list")
    assert "Waiting its turn" in listing.text and 'hx-trigger="every 10s"' in listing.text
    review_id, key, _ = h.ai_jobs.held[0]
    h.ai_jobs.service.run(review_id, key)  # type: ignore[union-attr]
    listing = client.get(f"/submissions/{submission}/ai/list")
    assert "A clear essay." in listing.text and "every 10s" not in listing.text


def test_nobody_else_sees_ai_reviews() -> None:
    h, client = organizer()
    submission = submission_of(send(client, {"ai_model": [LOCAL.key]}))
    stranger = h.new_client()
    signup(stranger, "sid@x.fi", "Sid Stranger")
    assert stranger.get(f"/submissions/{submission}/ai").status_code == 404
    assert stranger.get(f"/submissions/{submission}/ai/list").status_code == 404
    page = "/spaces"
    asked = post(stranger, f"/submissions/{submission}/ai", {"ai_model": [LOCAL.key]}, page=page)
    assert asked.status_code == 404
    assert len(h.ai_writer.calls) == 1
