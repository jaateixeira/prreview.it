# 0018. Request a review in one step

Status: accepted

## Context
The three processes of ADR 0017 are right for a school or a journal, but a person who only wants feedback on a file faces a long road: make an organization, make a space, create a call, submit, make a round, create invitations, send them. The product promise is "sign-up to first review round in under ten minutes" (ADR 0005, business plan). The product owner asked for something easier and more fun: a few clicks to create a review space, upload a file and send it out for review, starting from a Google, Apple or other federated account, with the typed email addresses validated, or imported from a `.json`, `.xml`, `.csv` or `.txt` file, and a sample to look at.

## Decision
- **One page, one submit.** `/review/new` asks for three things on one screen: the work (a PDF or text file, or pasted text), the reviewers (typed, or imported from a file) and the send (an optional cover letter and due date, and whether Previewit should email the invitations). One request makes the organization if the person has none, a Review space, a published protected call for authors, the Submission, a manual Round and one Invitation per reviewer. The page is the fast path through the same processes; it adds no new concept or rule.
- **Sign in first, with what the person already has.** A visitor reaches the page through the usual login redirect (`next`), so Google, Apple, HAKA, or email and password all work, and they land back on the page.
- **A service composes the existing services.** `QuickReviewService` (application layer) checks everything that can be checked first (title, reviewers, due date, the file, and a verified sender when mail is requested), so a refusal leaves nothing behind. Failures after creation, such as the sharing limit or a mail server that is down, are reported per reviewer and never undone: the personal link is always shown to copy.
- **Email lists are read safely.** `domain/email_list.py` is pure Python. It reads typed text and `.txt`, `.csv`, `.json` and `.xml` files, and picks out the email addresses (CSV header detection; JSON and XML are walked iteratively, with attributes and elements). XML with a `DOCTYPE` or entities is refused (no entity expansion), as are NUL bytes. Limits: 100 addresses per request and 200 kB per file. Invalid entries are listed, never dropped silently; repeats are counted and left out.
- **Live feedback, no JSON.** The textarea asks the server for an HTML fragment after a short pause (`hx-trigger="input changed delay:400ms"`). Choosing a list file swaps the addresses box with the merged result. The sample files (`/review/samples/{name}`) can be read on the page and downloaded. Without JavaScript the same form still works: the main submit reads the typed text and the file together.
- **A `general` preset** (words: *review space*) is used for the organization made on the way, so a person is not shown school words. It is a small, separate preset; Education stays the first and default preset for organizations created by hand. Preset words only rename, as before.
- **Year-1 file types.** PDF and plain text (`.txt`, `.md`, or pasted) only. Any other file is refused with the advice to save it as a PDF or paste the text. More types are plugins and come later (CLAUDE.md, year-1 scope).
- **Links are shown once.** Only the hash of each token is stored (ADR 0017), so the result page is the one place to copy a personal link. The page is the response to the POST, not a redirect.
- **Fun, cheaply.** A numbered three-step layout, friendly wording, a confetti burst made of CSS only (hidden for people who prefer reduced motion), and one click on the home page. No new JavaScript beyond the htmx attributes already used.

## Consequences
- The person who requests a review is the organizer and also an author of the Review space. Reviewers who open their link become reviewer members, as in ADR 0017. A person with an organization already gets the new space in their first organization.
- Each invitation counts toward the 100-share limit, as before (ADR 0017). Reviewers beyond the limit are listed as not invited; nothing is charged to them.
- Verification: Previewit mails in the organizer's name, so the page switches the mailing off, with the reason, until their address is confirmed. They can still create the review and send the links themselves. After confirming an email, the person returns to the page by hand; resuming a half-filled form is not built.
- Invitations are mailed once (ADR 0017). The result page cannot mail them again.
- Tests: unit tests for the parsers (including hypothesis properties) and the service; 30 web tests; two Playwright scenarios (sign up from the home page to the reviewer finding the work, and a refused file type).
