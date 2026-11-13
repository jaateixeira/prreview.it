# 0017. Three actors, two calls, invitation links

Status: accepted

## Context
Previewit grew from the Education preset: roles were data supplied by the preset (teacher, assistant, student, ADR 0009), and the only link was a share link (ADR 0011). That hid the shape of the product. Everything Previewit does is one of three things, done by three kinds of people:

- an **Organizer** calls for authors to submit work and calls for reviewers to review it;
- an **Author** submits work to a call;
- a **Reviewer** reviews work after an invitation from an organizer.

The calls travel as links that carry a token. It should not matter where a person works. A verified email address is enough to take part. Roles other than these three will come (an **Auditor** who audits the review process).

## Decision
- **Fixed roles per Space: organizer, author, reviewer.** They replace the preset-defined roles. A Member holds a set of roles (a participant in a class is both author and reviewer). Presets only rename them (Education: organizer = teacher). Adding a role later (auditor) is a core change with an ADR, not a preset.
- **The Party rule stays.** A Party (user or group) can author a Submission and write a Review. The Author role lets a Member submit; the Reviewer role lets a Member be allocated or invited to review. Authors and reviewers in one Round can be the same people, but nothing requires it.
- **The Organization owner** remains the tenant administrator (billing, data) and acts as organizer in every Space.
- **Two calls, both sent as links.**
  - The **call for authors** is today's `Call`. It has an access mode: **public** (the plain call URL accepts submissions) or **protected** (only a URL carrying the call's token does). The organizer can revoke or replace the token. Neither mode is listed in a directory.
  - The **call for reviewers** is a set of personal **Invitations** for a Round. An Invitation has its own token, belongs to one invited reviewer (an email address) and carries the Submissions that reviewer is to review (their review tasks). The Invitation is bound to the invited address: opening it asks for that verified email, gives the Reviewer role in the Space and lands on the reviewer's tasks.
- **Verified email is the only entry requirement.** No employer, school or domain test unless an organization chooses one in its configuration.
- **Token rules.** At least 128 bits of randomness, one purpose each, revocable, optional expiry. Pages reached by a token send `Referrer-Policy: no-referrer`, and the token is exchanged for a session so that it does not stay in later URLs.
- **Three key processes** are the way the product is explained, designed and tested (user manual, use cases, acceptance scenarios):
  1. **Organizing a call for authors.**
  2. **Organizing peer review of the submitted items.**
  3. **Reviewing work by invitation from an organizer.**
- **Review by link** (ADR 0011) is the same machinery with the author as sender. It is reconciled with Invitations in the step that builds them.
- **Vocabulary.** *Call* alone means the call for authors. The reviewer side is a *call for reviewers* made of *Invitations*. This updates ADR 0016, which called Organizer a permission set and not a role. The glossary carries the new entries.

## Consequences
- **Delivery in steps**, each its own pull request: (A) this ADR and the documentation; (B) fixed roles and a data migration; (C) public or protected access on the call for authors; (D) reviewer invitations and review by invitation.
- **Migration in B.** `teacher` becomes organizer. `assistant` becomes organizer, which is broader than the old assistant: it is the only fixed role that can see all submissions and manage groups. `student` becomes author and reviewer. Preset roles and `can_grant` are replaced by a fixed matrix of role to permissions.
- **Auditor** is reserved: a read-only role over reviews, the allocation and the edit trail. Its rules for anonymity are not decided.
- **Open points.** Whether invitations and protected-call links count toward the 100-share free limit (the organizer pays above it, as with shares). Whether an open reviewer link per Round (anyone may claim reviews) is added later.
