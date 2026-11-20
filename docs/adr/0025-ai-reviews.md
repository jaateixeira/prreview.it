# 0025. AI reviews: ask AI models to review a work, alongside people

Status: accepted (step 1 of 2: payments come with the plans, M8)

## Context
People who request a review wait days for their reviewers. AI models can read the same work in minutes and give a first round of feedback. The founder asked for this as a core feature: when someone requests a review, Previewit asks whether they want AI models suggested for their work; if they say yes, it suggests up to three that could review it, shows what each would cost with and without their own key, and lets them give a key to pay less.

Decisions taken with the founder:

- **Who pays.** Previewit pays only for small open models it runs itself: an Ollama server on its own hardware (a BC-250 today, without a GPU; more later). For any other model the person gives their own key, used for one request and never stored. A person without a key will be able to let Previewit pay and charge them; that needs payments (M8) and is step 2.
- **Which models.** The well-known services (Anthropic, OpenAI, Google, Mistral, xAI, DeepSeek) and small open models on Hugging Face's partners, paid with the person's Hugging Face token. Previewit suggests three; *See more* lists up to twenty. A flag shows where each model runs.
- **Who sees AI reviews.** The author and the organizers. Human reviewers never do. Someone who organizes a review of their own work is its author too, so they see everything.
- **The first screen** assumes a single author who wants a review, with a link for people organizing a peer review of work others will submit.

## Decision
- **An AI review is not a Review.** It is its own record, `AiReview`, on one Revision of a Submission: the model, where it ran, who paid, its status (waiting, writing, done, failed), the text, the tokens used and the cost. No Party writes it, it has no Rubric and no Round, and no reviewer's view lists it. `SubmissionView.sees_ai_reviews` is true for the author and for members who manage calls (the organizers); for everyone else AI reviews do not exist (404).
- **Consent first.** The request form has an optional step, *Feedback from AI models too?* Nothing is suggested until the person clicks *Yes, suggest AI models*, and nothing goes to any model until they send the request. Suggesting reads the work only to count its characters: a pasted text, a file's text (PDFs through pypdf), or a web page's text for people signed in. A visitor's web page is not fetched (ADR 0022); a typical length is assumed and the page says so.
- **Suggestions are rules, not a model.** `domain/ai_models.py`: only models that can read the whole work and still write a full review are listed. The three suggestions come from three makers: a free model on Previewit's server when one can read the work, one of the strongest models, and the best value among the strong ones; then other makers in catalogue order. *See more* lists the rest, up to 20 in all.
- **Prices.** Each model shows what one review costs, in US dollars: *with your key* (about, and at most) and *without a key* (about, with Previewit's margin, 30% by default, configurable). The second cannot be chosen until payments exist; it says so. Estimates use four characters a token, plus the instructions, plus what a review usually takes.
- **The catalogue is data.** `adapters/ai/models.toml` lists the services (API style, address, key name, where they run, the price page) and the models (price per million tokens read and written, how much they read at that price, tier, the date the price was checked). Prices change often: the file is checked monthly. The free models are whatever is installed on the configured Ollama server, looked up every five minutes, optionally narrowed to a list.
- **Keys are used once and never kept.** A key travels from a password field to the job queue in memory and from there in one request header to the service. It is never written to the database, a log line, an error message, a page or an email; the tests look for it in all of them. A visitor's chosen models wait with their form (ADR 0024); their keys do not, and the form says so.
- **Background work.** Reviews are written by a small pool of daemon threads: four for the services, one for Previewit's own server, which reads one work at a time. The page polls every ten seconds while a review is waiting or being written, and the person is emailed when it is ready or has failed. After a restart, free reviews go back in the queue; keyed ones fail with "ask again", because their key was never kept.
- **Three API styles over plain HTTP**, without the services' SDKs: Anthropic's Messages API; OpenAI-style chat completions (OpenAI, Google's OpenAI-compatible endpoint, Mistral, xAI, DeepSeek, the Hugging Face router with `:cheapest`); Ollama's `/api/chat`. Error messages are Previewit's own words, never the service's reply, which might quote the key.
- **The prompt** asks for a careful, kind and honest review in the work's own language, under four headings, and puts the work between markers it cannot close, with the instruction that everything inside is the work, never instructions. The output is shown as escaped plain text.
- **Limits.** Up to three models a request. Free reviews: ten a person a day, through the `Entitlements` port (they run on one small server). Suggesting is limited per client address for visitors.
- **Configuration.** A new `[ai]` section: `enabled`, `ollama_url`, `local_place`, `local_country`, `local_context`, `local_models`, `margin_percent`.
- **Scope.** This extends the year-1 scope in CLAUDE.md (text, PDF and web pages) with AI reviews of those same kinds of work.

## Consequences
- An author gets feedback within minutes, at no cost from the free models or at the services' own price with their key.
- The catalogue's prices go stale. They are shown as estimates with the date checked, and must be reviewed monthly and before Previewit charges for anything (step 2).
- Prompt injection inside a work can at worst change the AI review its own author reads; it cannot reach other people or Previewit's data.
- Work goes to the services the person chose, in the countries shown by the flags. The free models keep it on Previewit's own server.
- Step 2 (M8): credits and payments, so a person without a key can let Previewit pay. Still open: the payment provider (a merchant of record such as Paddle or Lemon Squeezy, or Stripe) and the margin.
- Not yet: AI reviews from the MCP service (ADR 0023); live Hugging Face prices from the router's model list; AI reviews without any human reviewer.
