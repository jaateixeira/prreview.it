# 0013. Rubrics and criterion-type plugins

Status: accepted

## Context
Reviewers need a structured form. Organizers want to build one once and reuse it, and different kinds of question (a 1 to 5 scale, named levels, yes/no, free text) must not be hard-coded into the core (CLAUDE.md: plugins, never `if kind == ...`).

## Decision
- A **Rubric** belongs to a Space and holds ordered **Criteria**. A criterion has a title, guidance, a type key, a type-specific config (JSON), a weight (0 to 100, 0 means feedback only) and a required flag. Both carry `org_id`; the criterion's foreign key to its rubric is composite `(rubric_id, org_id)`.
- **CriterionType** is a plugin API in the same entry-point group as artifact types (`previewit.plugins`): `fields` (settings the author fills in), `parse_config`, `to_form` (prefill the edit form), `max_score`, `describe`, `render_html`. The builder page renders the settings form from `fields`, so a new type needs no template change. Built-ins: `numeric`, `levels`, `yes_no`, `text`.
- A criterion's type cannot change after creation; delete and add instead. This keeps configs consistent with their type.
- New permission `rubrics.manage`, given to the roles that already manage calls with full rights (owner, teacher) but not to assistants or students. Non-managers get 404 on the builder, so rubrics do not leak.
- `Call.rubric_id` is nullable with a composite FK and no cascade: the database itself refuses deleting a rubric that a call uses, and the service reports it first. A call can only use a rubric of its own space; **duplicate** copies a rubric within the organization (also into another space) for reuse across courses.
- Templates per preset (`EDUCATION_TEMPLATES`) start a rubric in one click, since the target is a first review round in under 10 minutes.
- Members see a read-only preview of the call's rubric (drafts are hidden from non-managers); the inputs are inert until reviews exist (M5).

## Consequences
Reviews (M5) will store answers per criterion. **Open:** once reviews exist, editing a rubric would change what past answers mean. M5 must either freeze a rubric when its first review is saved or snapshot it per round. Until then rubrics are freely editable because nothing depends on their content.
