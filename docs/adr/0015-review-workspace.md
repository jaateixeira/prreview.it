# 0015. The review workspace

Status: accepted

## Context
Reviewers need to answer the rubric next to the work, keep their progress without pressing buttons, pin comments to the content, and review as a group. Group editing without live co-editing (post-MVP, PLAN section 2) must still never lose anyone's work.

## Decision
- A **Review** answers the rubric for one task: one review per task (unique in the database), answers stored as criterion id to string. Plugins validate and render them (`CriterionType.check_answer`, `score`, `render_html(..., value)`), so the core never looks at what kind of question it is.
- **Drafts may be incomplete; submitting needs every required answer.** A submitted review can still be changed until the round closes, and stays complete: saving it again applies the same required check. A closed round is read-only.
- **Autosave** is HTMX: the form posts changes to `/tasks/<id>/autosave` on change and after two seconds of typing, and the server answers with a status fragment and the new version number (swapped out of band into the form). Save draft and Submit are ordinary form posts, so the page works without JavaScript apart from autosave and text selection.
- **Group reviews are one shared review.** Any member may edit. Each save carries the version the page was loaded with; if someone **else** saved since, the save is refused (`ReviewConflict`) and nothing is overwritten. The page then shows the member's own answers beside a notice, with the current version, so saving again is a deliberate replace. A member's own earlier saves never conflict, which also removes the race between an autosave and pressing Submit. The database does the check-and-set in one `UPDATE ... WHERE version = ?`. Every save is attributed in an append-only trail (`review_edits`) shown on group reviews.
- **Who may open a task:** the reviewer (or any member of the reviewing group), once the round is open and the call published. Staff with `rounds.manage` may read any review, never write it. Everyone else gets 404, as does the author: other people's tasks do not exist for you. Authors seeing the reviews of their work is M6.
- **The artifact is served per task** (`/tasks/<id>/raw`), so reviewers can view a PDF without any access to the submission itself. The task points at the revision that was latest at allocation, so a later revision never moves a review.
- **Annotations are pinned to a revision and described by the artifact plugin**: `annotation_kind` says whether comments can be pinned, `check_selector` validates and normalises the selector. The text type uses quote plus start and end in characters and the server checks that the quote really is at that place, so a stale or forged selector is refused. About 20 lines of JavaScript record the selection. PDF page annotations are a separate release.
- **M4's open point is closed:** a round with reviews cannot be re-allocated or deleted, and a task with a review cannot be removed.

## Consequences
Two people who edit the same group review at the same moment lose nothing silently; the second one is told. Without live co-editing, edits are whole-form saves, so the later of two deliberate replaces wins. Scoring and weighted totals use `CriterionType.score` and arrive with feedback in M6. The anonymity preset recorded per round is not applied yet (M6); until then, reviewers do not see author names on their pages, and authors see no reviews.
