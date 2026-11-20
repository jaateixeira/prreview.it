# Applying to Paddle: the checklist

Paddle sells Previewit's credit as merchant of record ([ADR 0026](../adr/0026-credit-and-paddle.md)). Paddle verifies a seller in three steps: domain review, business verification and identity verification. Business verification is skipped for individuals and sole traders. Work through this list in order.

## 1. Before you apply (on your side)
- [ ] Decide how you sell: as an individual, or as a registered sole trader (toiminimi). Ask an accountant or Verohallinto about registering and about income tax on what Paddle pays you. Paddle handles the VAT on every sale.
- [ ] Open a bank account for the payouts (yours, or the business's).
- [ ] Fill in `[seller]` in `/etc/previewit/previewit.toml`: your **legal name** (Paddle prefers it to a brand), address, email and **phone** (Paddle's seller handbook asks for buyer support details), and the companies that process data for you (`processors`, e.g. Brevo for email). Restart, then check that `/terms`, `/privacy` and `/contact` show no "not set".
- [ ] Read the pages as a buyer would: `/pricing`, `/terms`, `/refunds`, `/privacy`, `/contact`. Have someone who knows Finnish consumer and privacy law look at them. Make sure the privacy notice is true: who hosts the site, how long the server logs are kept (it says 90 days).

## 2. Sandbox (test money)
1. Sign up at sandbox-vendors.paddle.com.
2. **Catalog → Products:** one product, "Previewit credit" (tax category: standard digital goods). Add three one-time **prices** in EUR, tax **included**: €5, €10, €25. Copy their ids (`pri_…`).
3. **Developer tools → Authentication:** create a client-side token (`test_…`).
4. **Developer tools → Notifications:** a destination `https://peerview.it/paddle/webhook` with the events `transaction.completed`, `adjustment.created` and `adjustment.updated`. Copy its secret key.
5. **Checkout → Checkout settings:** set the default payment link to `https://peerview.it/pricing`.
6. In `previewit.toml`:
   ```toml
   [paddle]
   environment = "sandbox"
   client_token = "test_…"
   webhook_secret_file = "paddle.secret"      # chmod 600, owned by previewit
   packs = { pri_aaa = 5, pri_bbb = 10, pri_ccc = 25 }

   [ai]
   keys_file = "ai-keys.toml"                 # Previewit's own keys: anthropic = "sk-ant-…"
   ```
7. Restart. Buy €5 on `/credit` with Paddle's test card (4242 4242 4242 4242, any future date, CVC 100). The balance shows €5.00 within a minute. Ask an AI review without a key and watch it take a few cents. Refund the purchase in Paddle's sandbox: within ten minutes the credit is taken back.

## 3. Live account and review
1. Sign up at vendors.paddle.com as an individual (or as your toiminimi) and complete identity verification.
2. **Checkout → Website approval:** submit `peerview.it`. Paddle checks that the site is live on HTTPS, describes the product, shows prices, and links the terms, refund policy and privacy notice from its navigation (the footer of every page). The terms must name the seller and Paddle as merchant of record. Most reviews are automatic; a manual one takes about 5 to 7 business days. Answer any question from Paddle quickly.
3. If Paddle asks what is sold: "Prepaid credit for AI-written feedback on documents in Previewit, an open-source peer-review service. People pay from credit for reviews by third-party AI language models (text only: no images, voice or likenesses)."
4. Once approved, repeat steps 2 to 5 of the sandbox in the live account, then set `environment = "production"`, the `live_…` token, the live secret and the live price ids. Restart, and buy €5 yourself to see it work end to end; refund it.

## 4. After going live
- Check the model prices in `src/previewit/adapters/ai/models.toml` every month, and `usd_to_eur` with them.
- Paddle pays out monthly; keep its statements for bookkeeping.
