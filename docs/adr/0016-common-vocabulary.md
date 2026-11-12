# 0016. Common vocabulary

Status: accepted

## Context
Previewit mixes three audiences: education (first), academic venues and engineering teams (later), and a literature that uses many synonyms for the same thing ("work product", "review object", "artifact", "review item"; "assignment" for both homework and reviewer matching; "conflict" for allocation, conflict of interest and a stale save). The code had already drifted: `ReviewConflict` meant a stale save, "conflict" in allocation meant overlapping people, and `double_blind` sat beside the glossary's "double-anonymous". The core must stay domain-neutral (ADR 0004) and presets supply the user-visible words.

## Decision
- **[docs/glossary.md](../glossary.md) is the single source of words.** It covers every concept in the review literature list (types of review, object and scope, instruments, roles, feedback, cognitive and ethical concepts, rounds and lifecycle) and marks each as Core, Planned, Presentation, Deferred or Avoid, with its code name and the Education preset's word.
- **Three layers of names.** The core term is used in code, tests, docs and ADRs. The preset word is shown to users through `Preset.word()`. The code name follows the core term.
- **One word for the thing under review: Submission**, made of numbered **Revisions** whose content is an **Artifact**. We do not say work product, review object or review item. A located comment is an **Annotation**; a response to a criterion is an **Answer**. There is no "finding" type.
- **Anonymous, not blind.** Presets are `reviewers_hidden` (default), `authors_hidden`, `double_anonymous` and `open`. `double_blind` is renamed, with a data migration (`0008`).
- **Allocation, not assignment.** Matching reviewers to Submissions is *allocation*. "Assignment" is only the Education preset's word for a Call and never appears in core code, docs or templates.
- **Three kinds of conflict, three names.** *Conflict* is the allocation overlap. *Conflict of interest* is a declared stake (deferred). `ReviewConflict` becomes **`EditConflict`**, a stale save.
- **Organizer** is a permission set (`calls.manage`, `rounds.manage`, `rubrics.manage`), not a role. Moderator, facilitator and recorder describe live meetings and are not used. Chair is reserved for the academic-venue preset.
- **Feedback** is what an author receives (M6). A reviewer writes a **Review**.
- **Deferred concepts keep a reserved word** (formative/summative `purpose`, coverage, calibration, sign-off, resolution states, latency, turnaround) so a later milestone does not invent a second one.
- **The rule is tested.** `tests/unit/test_vocabulary.py` fails when *course*, *student*, *teacher*, *assignment* or *blind* appear in `domain/`, `application/`, `plugins/` or templates, except the two preset files `domain/tenancy.py` and `domain/rubrics.py`.

## Consequences
- Renames in this change: `AnonymityPolicy.single_blind_reviewers_hidden`, `single_blind_authors_hidden` and `double_blind` become `reviewers_hidden`, `authors_hidden` and `double_anonymous`; `ReviewConflict` becomes `EditConflict`; the workspace no longer hard-codes "assignment"; the stored anonymity key `double_blind` is migrated.
- Older ADRs (0004 and others) and the market analysis keep their original wording. They are a record, and the glossary says which word wins.
- New concepts must be added to the glossary in the same pull request. A new preset adds its words to `Preset.vocabulary` and nowhere else.
- The Resolution words (addressed, disputed, deferred, withdrawn) are fixed for M6.
- Open: the Education preset does not yet supply words for round, review or reviewer. The core words are used until a preset needs different ones.
