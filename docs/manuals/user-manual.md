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
| Organizer | Teacher | Sets up calls and rounds |
| Call | Assignment | A request for submissions and reviews |
| Party | Student or group | Author of a submission or writer of a review |
| Rubric, criterion | Assessment criteria | What reviewers score |
| Round | Review round | A period in which reviews are written |

## 3. Two ways to start

| Way | For | Milestone |
|---|---|---|
| **Share a link** | One person wants feedback on one piece of work | M2 |
| **Organize a round** | Many people review each other, with rules | M1 to M6 |

Use the hosted site. Sign-up asks for the minimum. Students and reviewers never pay.

## 4. Share a link (M2)

1. Upload your text or PDF.
2. Copy the link and send it.
3. Reviewers open the link, sign up with the minimum, and review.
4. Read the feedback when it arrives.

## 5. Organizer

1. **Create a space** and invite members by link. Form groups if groups submit or review. (M1)
2. **Create a call:** title, instructions, accepted type (text or PDF), deadline. (M2)
3. **Build a rubric:** criteria with a scale (numeric, levels with descriptions, yes/no, free text) and optional weights. Rubrics are reusable. (M3)
4. **Configure the round:** opening and closing time, anonymity, reviews per submission, allocation (random, round-robin or manual). (M4)
5. **Allocate.** Previewit never assigns a party its own work or its own group's work, and balances the load. Adjust by hand if needed. (M4)
6. **Follow progress:** who has submitted, who has reviewed. (M5)
7. **Release feedback** by hand or by rule (for example when the round closes). (M6)
8. **Further rounds:** authors revise; the next round targets the new revision, and reviewers see the earlier reviews and the author's response. (M6)
9. **Export scores** as CSV, for example for the Moodle gradebook. (M7)

In Moodle, paste the space or call link into the course. Launch from Moodle with grades returned arrives with LTI 1.3 (M9).

## 6. Author (M2, M6)

1. Open the call and submit your text or PDF. In a group, one member submits for all.
2. When feedback is released, read comments in place on your work and the scores per criterion.
3. Write a response to each review. If there is another round, submit a revision.

## 7. Reviewer (M5)

1. Open **My reviews to do**. Each task is a card with its deadline.
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
