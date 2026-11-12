# Glossary: the words Previewit uses

One concept, one word. Use these words in code, tests, docs, ADRs, issues and commit messages. The reasoning is in [ADR 0016](adr/0016-common-vocabulary.md). The list of review concepts it starts from is the standard literature vocabulary of peer, code and inspection review.

## How to use it

Every concept has up to three names:

| Layer | Where | Rule |
|---|---|---|
| **Core term** | code, tests, docs, ADRs | Domain-neutral. Always the word in the *Core term* column. |
| **Preset word** | what a user sees | Comes from the organization's preset (`Preset.word(concept)`). Education says *course* for Space and *assignment* for Call. Never hard-code it in a template or in `domain/`, `application/`, `plugins/`. |
| **Code name** | identifiers | The class or field in the *Code* column. Rename the code if the word changes. |

Status column:

- **Core**: built and in the code today.
- **Planned (Mn)**: designed, delivered by that milestone in [PLAN.md](PLAN.md).
- **Presentation**: shapes help text, templates and rubric templates. Not modelled.
- **Deferred**: out of year-1 scope (Education, text and PDF). The word is reserved so nobody invents another.
- **Avoid**: do not use for this concept, for the reason given.

## 1. Core nouns

| Core term | Meaning | Status | Code | Education says | Avoid |
|---|---|---|---|---|---|
| **Organization** | The tenant. Owns every row (`org_id`), the preset and billing. | Core | `Organization`, `OrgId` | school | tenant (in UI), account |
| **Space** | A place where a set of Members reviews each other's work. | Core | `Space`, `SpaceId` | course | project, class, workspace |
| **Member** | A user with one or more roles in a Space. A verified email is enough to be one. | Core | `SpaceMember` | participant | participant (outside Education), user (when a role matters) |
| **Party** | Someone or something that can author a Submission or write a Review: a user or a group. | Core | `Party`, `UserParty`, `GroupParty` | (none) | actor, principal |
| **Group** | A named set of Members in a Space that acts as one Party. | Core | `Group`, `GroupId` | (none) | team (reserved for the engineering preset's Space) |
| **Role** | One of the fixed roles in a Space: **organizer**, **author**, **reviewer**. A Member holds a set of them. **Auditor** is reserved (Deferred). Presets only rename them. | Core | `Role` | teacher, author, reviewer | preset-defined roles, assistant |
| **Organizer** | The role that calls for authors and calls for reviewers, builds rubrics, runs Rounds and reads everything. The Organization owner is organizer in every Space. | Core | `Role.ORGANIZER`, `Permission` | teacher | moderator, facilitator, chair (see section 5) |
| **Call** (for authors) | The Organizer's invitation to submit work, with a deadline, an artifact type and optionally a Rubric. Sent as a link. Access is **public** (plain URL) or **protected** (URL with a token). *Call* alone always means this one. | Core (access modes done) | `Call`, `CallId` | assignment | task, activity |
| **Call for reviewers** | The Organizer's invitation to review the submitted work of a Round: a set of Invitations. | Planned (step D) | (a set of `Invitation`) | (none) | review assignment |
| **Invitation** | One personal link with a token for one invited reviewer (an email address), bound to that address, carrying the Submissions to review. | Planned (step D) | `Invitation` | (none) | invite (an invite adds a Member) |
| **Token** | The random secret in a link. At least 128 bits, one purpose, revocable. | Core (share links), Planned (C, D) | | | key, password |
| **Submission** | What a Party hands in to a Call. It is the **review unit**: one Submission is reviewed as a whole. | Core | `Submission` | (none) | work product, review object, review item, deliverable |
| **Revision** | A numbered, immutable version of a Submission. Reviews and Annotations are pinned to one Revision. | Core | `Revision` | (none) | version (ambiguous with `version` on a Review) |
| **Artifact** | The content of a Revision, of a type supplied by a plugin (text, PDF). | Core | `Artifact`, `ArtifactType` | (none) | attachment |
| **Review** | The reviewer Party's response to one Submission: answers to the Rubric plus Annotations. | Core | `Review` | (none) | feedback (that is what an author *receives*), evaluation |
| **Reviewer** / **Author** | Two roles (above) and, per task, two *relations* a Party has to a Submission. The same Party can be author of one Submission and reviewer of another. | Core | `ReviewTask.reviewer`, `Submission.author` | (none) | grader, evaluator, student author |
| **Share link** | A link that gives access to one Call or Submission with minimal sign-up. The author is the sender; reconciled with Invitations in step D. | Core | `ShareLink` | (none) | invite (an invite adds a Member) |
| **Preset** | A bundle of vocabulary, roles, rubric templates and defaults for a kind of organization. | Core | `Preset` | (Education) | mode, template (a template is a Rubric template) |

**The three processes** are the way to explain Previewit. Each is a flow between the three roles:

1. **Organizing a call for authors**: the Organizer creates and sends a Call; Authors submit.
2. **Organizing peer review**: the Organizer builds a Rubric and a Round, allocates, sends a call for reviewers and follows progress.
3. **Reviewing by invitation**: a Reviewer opens an Invitation, verifies an email and reviews.

An **Auditor** (Deferred) will audit the review process: read-only over reviews, allocation and the edit trail.

## 2. Models of review (source section A)

| Core term | Meaning | Status | Code | Notes |
|---|---|---|---|---|
| **Formative** / **Summative** | The *purpose* of a Round: help the author improve, or judge against a standard. | Deferred | (a future `purpose` on `ReviewRound`) | Education defaults to formative. Do not use as an anonymity or allocation setting. |
| **Anonymity** | Who may see whose identity, per direction, with a reveal time. | Core | `AnonymityPolicy`, `RevealAt` | Say *anonymous*, never *blind*. The literature has moved to *anonymous*, and *blind* is a disability metaphor. |
| **Single-anonymous** | One side is hidden. Two directions exist, so we name the hidden side: **reviewers hidden** (default) and **authors hidden**. | Core | preset keys `reviewers_hidden`, `authors_hidden` | Plain "single-anonymous" is ambiguous in a system where authors can also review. |
| **Double-anonymous** | Neither side sees the other. | Core | preset key `double_anonymous` | Was `double_blind` before ADR 0016. |
| **Open review** | Everyone sees everyone. | Core | preset key `open` | |
| **Inspection** (formal review) | Structured review with roles, checklist, prescribed process and defect log. | Deferred | | Year 2, engineering and academic presets. Do not use "inspection" for ordinary review. |
| **Walkthrough**, **over-the-shoulder**, **pair review** | Synchronous, informal modes. | Avoid | | Out of scope. Previewit is asynchronous. |

## 3. The object and scope of review (source section B)

| Core term | Meaning | Status | Code | Notes |
|---|---|---|---|---|
| **Submission** | See section 1. The thing under review. | Core | `Submission` | Prose may say "the work" informally. Never "work product", "review object" or "review item". |
| **Review unit** | The bounded slice a Round examines: one Submission. | Core | `Submission` | Not a separate entity. Smaller units give better feedback; advise organizers in help text. |
| **Scope** | What is in and out of bounds for reviewers, written by the organizer. | Core | `Call.description` | Free text for now. |
| **Coverage** | How much of the Submission the reviewer says they examined. | Deferred | (a future criterion type) | Needed so an author knows silence is not approval. |
| **Changeset size** | Size of a code change. | Deferred | | Code-review plugin, year 2. |
| **Entry criteria** / **reviewability** | When a Submission may be reviewed. | Core (partial) | `Call.published`, `Call.closes_at` | A Call must be published, and a Submission needs at least one Revision. |
| **Finding** | A single issue a reviewer raises. | Avoid as a type | | Use **Annotation** (located) or an **Answer** to a criterion (general). *Review item* is avoided for the same reason: it could mean either. |
| **Annotation** | A comment pinned to a place in one Revision. The selector is defined by the artifact type (quote and offsets for text, page and rectangle for PDF). | Core (text), Planned (M5b, PDF) | `Annotation` | |

## 4. Standards and instruments (source section C)

| Core term | Meaning | Status | Code | Notes |
|---|---|---|---|---|
| **Rubric** | The list of Criteria a Call's reviewers answer. | Core | `Rubric` | **Analytic** = several Criteria. **Holistic** = one Criterion with levels. Same entity. |
| **Criterion** | One question in a Rubric, of a type supplied by a plugin (numeric, levels, yes/no, text). | Core | `Criterion`, `CriterionType` | |
| **Answer** | A reviewer's response to one Criterion. | Core | `Review.answers` | |
| **Checklist** | A Rubric made of yes/no Criteria. | Presentation | rubric template "Quick check" | A template name, not a type. |
| **Calibration** | Aligning reviewers before they review. | Deferred | | Year 2 academic preset. |

## 5. Roles and process discipline (source section D)

| Core term | Meaning | Status | Code | Notes |
|---|---|---|---|---|
| **Organizer** | See section 1. Leads the process: opens Rounds, allocates, reads everything. | Core | `Permission.ROUNDS_MANAGE` | *Moderator* and *facilitator* describe live meetings and are not used. *Chair* is reserved for the academic-venue preset. |
| **Recorder** (scribe) | One person who writes the group's response. | Deferred | | Today any Member of a reviewing Group may edit the shared Review, and `ReviewEdit` records who did. |
| **Author-as-observer** | The author listens and does not defend the work. | Presentation | | A norm for help text. In an asynchronous system it is enforced by release rules (M6): authors see Reviews only when released. |
| **Re-review** | A later Round on a newer Revision, which checks that earlier feedback was dealt with. | Core | `ReviewRound` (round 2 allocates against the then-latest Revisions) | Say *re-review*, not *reinspection* or *follow-up*. |

## 6. Feedback principles (source section E)

These are guidance for the words we write (help text, rubric templates, empty states), not entities in the model.

| Principle | Status | How it shows up |
|---|---|---|
| **Constructive feedback** | Presentation | Criterion prompts ask what to change, not only how good the work is. |
| **Specificity and actionability** | Presentation | Prefer Annotations (pinned to a place) over general comments. |
| **Focus on the work, not the author** | Presentation | Write prompts about the work ("Is it easy to follow?"), never about the person. Anonymity reinforces it. |
| **Balance of positive and negative** | Presentation | The Essay feedback template includes "What worked well?" next to the improvement prompts. |
| **Feedback sandwich** | Presentation | Not enforced. Mechanical praise is worse than none, so there is no required "positive" field. |

**Feedback** as a noun means what an author *receives*: the Reviews and Annotations released to them (the "feedback received" page, M6). A reviewer writes a **Review**, never "gives feedback" in code.

## 7. Cognitive, social and ethical concepts (source section F)

| Core term | Meaning | Status | Code | Notes |
|---|---|---|---|---|
| **Conflict** | Two Slots whose sets of people overlap, so they may not be paired. Covers self-review and own-group review. | Core | `domain/allocation.py` | Only about allocation. |
| **Conflict of interest** (COI) | A *declared* stake in the outcome. Disclosure and recusal. | Deferred | | Year 2. When built it feeds allocation Conflicts. |
| **Edit conflict** | Two people saved the same Review from the same version. | Core | `EditConflict` | Was `ReviewConflict` before ADR 0016. Never plain "conflict". |
| **Reviewer bias** | Confirmation, preference and territorial bias. | Not modelled | | Mitigated by anonymity, rubrics and (later) calibration. |
| **Anonymity and accountability** | Anonymity protects candor, but the organizer can always see who wrote what. | Core | `AnonymityPolicy.reveal_at`, `ReviewEdit` | Every display of a name goes through `IdentityMask` (M6). |
| **Psychological safety**, **group accountability** | Honest feedback without fear, and visible participation. | Presentation | `ReviewEdit` shows who edited a group Review | Help text only. |

## 8. Rounds, loops and lifecycle (source section G)

| Core term | Meaning | Status | Code | Notes |
|---|---|---|---|---|
| **Round** | One cycle of review on a Call: reviewers write Reviews. Numbered 1, 2, 3 per Call. Status (scheduled, open, closed) is computed from the clock. | Core | `ReviewRound`, `RoundStatus` | Say *Round*, not *iteration* or *cycle*. |
| **Review task** | One reviewer Party paired with one Submission, at a given Revision. | Core | `ReviewTask` | "Task" alone is not used. Users see "My reviews". |
| **Allocation** | Deciding which reviewers get which Submissions, honouring Conflicts and balancing load. | Core | `AllocationStrategy`, `Allocation`, `Slot` | Strategies: random, round-robin, manual. **Never "assignment"**: Education calls a Call an *assignment*, and "assigning reviewers" would be ambiguous. The Education button reads "Allocate reviewers". |
| **Load balancing** | A property of an Allocation: loads differ by at most one when only authorship Conflicts exist. | Core | `balanced_assign`, `rebalance` | Not a feature name. |
| **Review loop** | Submit, review, revise, resubmit, re-review. | Presentation | | It is just consecutive Rounds on new Revisions. The stopping rule is the **Sign-off**. |
| **Resolution** | The author's response to an Annotation: *addressed*, *disputed*, *deferred* or *withdrawn*. | Planned (M6) | | Use these four words exactly. Ensures feedback is never silently ignored. |
| **Latency** / **turnaround** | Time from a Round opening to the first saved Review (latency) and to the Round closing (turnaround). | Deferred | | Analytics. Names fixed now. |
| **False positive** (noise) | A flagged non-issue. | Avoid as a field | | If measured, it will be a rating authors give a Review. No term chosen until then. |
| **Consensus review** | Reconciling divergent judgments before a decision. | Deferred | | Year 2. |
| **Sign-off** | Formally closing a Round and authorizing the next stage. Includes the academic **Decision**. | Deferred | | *Approval gate* is a synonym we do not use. |
| **Audit trail** | Who reviewed what, when, with what changes. | Core | `ReviewEdit` (table `review_edits`), append-only | |

## 9. Words that mean two things (read before you name anything)

| Word | In Previewit | Not |
|---|---|---|
| **assignment** | Only the Education preset's word for a Call, shown to users. | Never in core code, docs or ADRs. Reviewer matching is **allocation**. |
| **conflict** | Allocation overlap (section 7). | An edit conflict is `EditConflict`. A conflict of interest is COI. |
| **version** | The counter on a Review used for edit conflicts. | Use **Revision** for versions of a Submission. |
| **review** | The noun: a Review entity. The verb *to review* is the activity. | *Round* is the cycle, *task* is the pairing. |
| **feedback** | What an author receives. | What a reviewer writes is a Review. |
| **item** | Nothing. | Avoid *review item* (finding or artifact?). |
| **blind** | Nothing. | Say anonymous. |
| **member** / **participant** | Member in core, *participant* in Education. | |

## 10. Adding or changing a word

1. Check this page. If the concept exists, use its word.
2. If it is new, add it here in the same pull request, with a status and a code name.
3. If you rename something, rename code, tests and docs together. Record a notable rename in an ADR.
4. `tests/unit/test_vocabulary.py` fails the build when education words or *blind* appear in `domain/`, `application/`, `plugins/` or templates outside the preset files.
