# User manual

**Status:** describes version 0.1 as planned. Today (M0) only the landing page exists; each section names the milestone that delivers it. Screens and labels may change.

## 1. What Previewit does

People review each other's work. Reviewers comment directly on a text or PDF and score it against criteria. Individuals and groups can be on either side. An organizer sets the rules; Previewit handles who reviews whom, deadlines and anonymity.

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

Everything in Previewit is done by one of three people. You can be more than one. All you need is a verified email address, wherever you work or study.

| Process | Who | What happens | Milestone |
|---|---|---|---|
| **Organizing a call for authors** | Organizer, Author | The organizer sends a link; authors open it and submit | M2, protected calls MA |
| **Organizing peer review** | Organizer | Rubric, round, allocation, then a personal invitation link to each reviewer | M3, M4, MA |
| **Reviewing by invitation** | Reviewer | Open the link, verify your email, review the work allocated to you | M5, MA |

Calls travel as links. A call for authors is **public** (anyone with the plain link can submit) or **protected** (only the link with its token works; the organizer can revoke it or send a new one). An invitation to review is personal: it belongs to the email address it was sent to.

An auditor, who checks how reviews were done, is planned for later.

### The quickest start: Request a review

Press **Request a review** on the home page. Sign in with Google, Apple or your email, and one page asks for three things:

1. **The work.** Choose a PDF or a text file (`.txt`, `.md`), or paste the text. The title comes from the file name if you leave it empty. Other kinds of file are not reviewed yet: save them as a PDF.
2. **The reviewers.** Type or paste email addresses, separated by commas, spaces or new lines. Previewit checks them as you type and points at any that do not look right. Or import a list from a `.txt`, `.csv`, `.json` or `.xml` file: Previewit picks out the addresses. **See a sample** shows each format and lets you download it.
3. **Send it.** Add a few words for the reviewers and a due date if you like (two weeks otherwise). Leave **Email the invitations for me** ticked and Previewit mails each person their own link in your name (confirm your own email address first). Untick it and you get the links to send yourself.

Previewit makes the review space, the call, the round and one personal invitation per reviewer. The last page lists each reviewer with their link, shown once, and takes you to the round to follow progress.

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
2. **Call for authors:** title, instructions, accepted type (text or PDF), deadline, and who may submit: public or protected. Publish, copy the link and send it. For a protected call, create a link with a token for each group you invite; you can revoke it and send a new one. Anyone who opens the link and verifies their email becomes an author in the space, so give a large public call a space of its own. (M2, MA)
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

1. Open the call link you were sent (public or protected), verify your email, press **Join and submit**, and submit your text or PDF. In a group, one member submits for all.
2. When feedback is released, read comments in place on your work and the scores per criterion.
3. Write a response to each review. If there is another round, submit a revision.

## 7. Reviewer (M5)

1. Open your invitation link and sign up or log in with the address it was sent to. Confirm that address (we mail you a link), open the invitation again and press **Start reviewing**. The link works for that address only. (MA) Then open **My reviews to do**. Each task is a card with its deadline.
2. The work is on the left, criteria on the right.
3. Select text, or an area of a PDF page, to attach a comment.
4. Score each criterion; descriptions of the levels are shown beside it.
5. Everything saves automatically. Submit when done.
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
| Students and reviewers | Always free | Always free |

Usage is shown in your account, with a warning before a limit is reached.

## 10. Your data

- You can export or delete your data. (planned; milestone not set)
- Organizations set how long data is kept.
- Previewit is open source (AGPL-3.0-or-later); every page links to the source code.
- Report security or anonymity problems privately; see `SECURITY.md`.
