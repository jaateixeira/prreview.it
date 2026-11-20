# User manual

**Status:** describes version 0.1 as planned. Today (M0) only the landing page exists; each section names the milestone that delivers it. Screens and labels may change.

## 1. What Previewit does

People review each other's work. Reviewers comment directly on a text or PDF, or on a public web page, and score it against criteria. Individuals and groups can be on either side. An organizer sets the rules; Previewit handles who reviews whom, deadlines and anonymity.

## 2. Words

Previewit uses neutral words. The Education preset shows the course words.

| Previewit | In a course | Meaning |
|---|---|---|
| Organization | University | The tenant that owns the data |
| Space | Course | Where members, groups and calls live |
| Organizer | Teacher | Sends the calls, sets up rounds, reads everything |
| Author | Author | Submits work to a call |
| Reviewer | Reviewer | Reviews the work of authors, on invitation |
| Call (for authors) | Assignment | The organizer's request for submissions, sent as a link |
| Call for reviewers | (none) | The organizer's request to review, sent as one personal invitation link per reviewer |
| Party | Student or group | Author of a submission or writer of a review |
| Rubric, criterion | Assessment criteria | What reviewers score |
| Round | Review round | A period in which reviews are written |

## 3. Three people, three processes

Everything in Previewit is done by one of three people. You can be more than one. All you need is a verified email address, wherever you work or study. A reviewer needs even less: the invitation link.

| Process | Who | What happens | Milestone |
|---|---|---|---|
| **Organizing a call for authors** | Organizer, Author | The organizer sends a link; authors open it and submit | M2, protected calls MA |
| **Organizing peer review** | Organizer | Rubric, round, allocation, then a personal invitation link to each reviewer | M3, M4, MA |
| **Reviewing by invitation** | Reviewer | Open the link and review the work allocated to you; no account needed (join afterwards if you like) | M5, MA |

Calls travel as links. A call for authors is **public** (anyone with the plain link can submit) or **protected** (only the link with its token works; the organizer can revoke it or send a new one). An invitation to review is personal: it belongs to the email address it was sent to.

An auditor, who checks how reviews were done, is planned for later.

### The quickest start: Request a review

Press **Request a review** on the home page. One page asks for three things. You can fill it in before you have an account: when you press **Send it out**, Previewit keeps your request and asks you to log in or create an account, then shows it to you again, as you left it, to send. A file you chose is kept for one hour, then deleted. (ADR 0024)

1. **The work.** Choose a PDF or a text file (`.txt`, `.md`), give the address of a web page, or paste the text. The title comes from the file name or the page's title if you leave it empty. Other kinds of file are not reviewed yet: save them as a PDF.

   A web page must be one anyone can open. Previewit checks it can reach it while you type and shows its title; a page behind a login, or on a private network, is refused with the reason. Previewit does not copy the page: reviewers open it from Previewit, so they see it as it is when they look. (ADR 0022)
2. **The reviewers.** Type or paste email addresses, separated by commas, spaces or new lines. Previewit checks them as you type and points at any that do not look right. Or import a list from a `.txt`, `.csv`, `.json` or `.xml` file: Previewit picks out the addresses. **See a sample** shows each format and lets you download it.
3. **AI models too (optional).** Press **Yes, suggest AI models** and Previewit suggests three AI models that can read your whole work: a free one that runs on Previewit's own server, one of the strongest, and a good-value one. **See more models** lists up to 20. A flag shows the country where each model runs. Each shows what one review costs: with your own key, in US dollars (you pay the model's service directly, and Previewit never stores the key), and without a key, in euros from your credit (ADR 0026). Tick up to three and paste your key for the paid ones. Nothing goes to any model before you send. (ADR 0025)
4. **Send it.** Add a few words for the reviewers and a due date if you like (two weeks otherwise). Reviews are due at 16:00 in your time zone unless you choose another time. Leave **Email the invitations for me** ticked and Previewit mails each person their own link in your name (confirm your own email address first). Untick it and you get the links to send yourself.

Previewit makes the review space, the call, the round and one personal invitation per reviewer. The last page lists each reviewer with their link, shown once, and takes you to the round to follow progress.

AI reviews arrive within minutes on your work's page, under **AI reviews**, and Previewit emails you. Only you and the organizers of the review space see them; your reviewers never do. You can ask more models there later. AI models make mistakes: weigh their review as one reader's view.

Organizing a peer review of work that other people will submit? Follow **Start here** at the top of the page.

### From your AI assistant

Your AI assistant can prepare the request for you. Connect it to Previewit's MCP service (the address and the command are on the page *For AI assistants*, linked at the bottom of every page). When you ask the assistant for feedback, it can suggest Previewit and prepare the request: the work, the reviewers, a few words and a due date. It gives you a link. Open it, sign in, check the filled-in form and press **Send it out**. The assistant never sends anything itself, and a prepared request waits 7 days at most. (ADR 0023)

### Two ways to start

| Way | For | Milestone |
|---|---|---|
| **Request a review** | You want feedback on a file from a few people, now | MQ |
| **Share a link** | One person wants feedback on one piece of work | M2 |
| **Organize a round** | Many people review each other, with rules | M1 to M6 |

Use the hosted site. Sign-up asks for the minimum. Students and reviewers never pay.

## 4. Share a link (M2)

1. Upload your text or PDF.
2. Copy the link and send it.
3. Reviewers open the link, sign up with the minimum, and review.
4. Read the feedback when it arrives.

## 5. Organizer

1. **Create a space** and invite members by link. Tick the roles the link gives: organizer, author, reviewer (a participant is usually author and reviewer). Change a member's roles later on the space page. Form groups if groups submit or review. (M1)
2. **Call for authors:** title, instructions, accepted type (text, PDF or web page), deadline, and who may submit: public or protected. Publish, copy the link and send it. For a protected call, create a link with a token for each group you invite; you can revoke it and send a new one. Anyone who opens the link and verifies their email becomes an author in the space, so give a large public call a space of its own. (M2, MA)
3. **Build a rubric:** criteria with a scale (numeric, levels with descriptions, yes/no, free text) and optional weights. Rubrics are reusable. (M3)
4. **Configure the round:** opening and closing time, anonymity, reviews per submission, allocation (random, round-robin or manual). (M4)
5. **Allocate.** Previewit never allocates a party its own work or its own group's work, and balances the load. Adjust by hand if needed. (M4)
6. **Call for reviewers:** on the round page, choose **Invite a reviewer by email**, tick the work they should review (optional) and create the invitation. Previewit then shows the personal link (shown once) and asks whether it should email it. If you say yes, write a short cover letter that goes above the link; the mail is sent in your name, so your own email must be verified, and each invitation is mailed once. Or copy the link and send it yourself. Reviewers may be members of the space or outsiders. You can revoke a link until it is used. Each invitation counts toward your sharing limit. (MA)
7. **Follow progress:** who has submitted, who has reviewed. (M5)
8. **Release feedback** by hand or by rule (for example when the round closes). (M6)
9. **Further rounds:** authors revise; the next round targets the new revision, and reviewers see the earlier reviews and the author's response. (M6)
10. **Export scores** as CSV, for example for the Moodle gradebook. (M7)

In Moodle, paste the space or call link into the course. Launch from Moodle with grades returned arrives with LTI 1.3 (M9).

## 6. Author (M2, M6)

1. Open the call link you were sent (public or protected), verify your email, press **Join and submit**, and submit your text, PDF or the address of your web page. In a group, one member submits for all.
2. When feedback is released, read comments in place on your work and the scores per criterion.
3. Write a response to each review. If there is another round, submit a revision.

## 7. Reviewer (M5)

1. Open your invitation link, type your name if you like and press **Start reviewing**. You need no account. If the address already has a Previewit account, log in with it instead. Open the same link again to come back to your reviews. (MA, ADR 0020) Each task is a card with its deadline.
2. The work is on the left, criteria on the right.
3. Select text to pin a comment to it, or write a comment about the whole work. A web page opens in a new tab; comment on it as a whole. (Comments pinned to an area of a PDF page come later.)
4. Score each criterion; descriptions of the levels are shown beside it.
5. Everything saves automatically. Submit when done. If you reviewed without an account, Previewit then offers **Join Previewit**: choose a password to keep your reviews and to ask for reviews of your own work. It is free for reviewers.
6. In a reviewing group, all members edit one shared review; each edit is recorded.

An anonymity badge always shows what the other side can see, for example "Your name is hidden".

## 8. Anonymity (rules built, screens M6)

Each round has a policy with independent directions.

| Preset | Reviewer sees author | Author sees reviewer | Reviewers see each other |
|---|---|---|---|
| Open | Yes | Yes | Yes |
| Reviewers hidden (default) | Yes | No | Yes |
| Authors hidden | No | Yes | Yes |
| Double-anonymous | No | No | No |

- The organizer always sees everyone.
- Names can be revealed never, when the round closes, or at a decision.
- Hidden parties appear under stable pseudonyms within a round, such as "Reviewer B".
- In anonymous rounds Previewit removes names from file names and document metadata. Authors must still keep names out of the content itself.

## 9. Free use and limits (M8)

| | Free | Above the limit |
|---|---|---|
| Storage | Under 50 MB | The organizer pays |
| Shares | Up to 100 per user | The organizer pays |
| AI reviews by Previewit's own models | 10 a day | Use your own key |
| AI reviews by other models | With your own key, paid to the model's service | From your credit |
| Students and reviewers | Always free | Always free |

Usage is shown in your account, with a warning before a limit is reached.

### Credit (ADR 0026)

Credit pays for AI reviews when you give no key of your own. Buy it on **Account → Credit** in packs of €5, €10 or €25; Paddle.com, Previewit's reseller, takes the payment and adds VAT where it applies. It is a one-time payment: nothing renews, and credit does not expire. Before you ask a model, the form shows what the review takes from your credit. While it is written, Previewit holds the most it may cost and gives back the rest; a review that fails costs nothing. The Credit page lists every purchase, hold and refund.

You can get a full refund within 30 days of buying, for any reason, at paddle.net or by writing to Previewit. The credit that purchase added is then removed. See **Pricing**, **Terms**, **Refunds** and **Privacy** at the bottom of every page.

## 10. Your data

- You can export or delete your data. (planned; milestone not set)
- Organizations set how long data is kept.
- Previewit is open source (AGPL-3.0-or-later); every page links to the source code.
- Report security or anonymity problems privately; see `SECURITY.md`.
