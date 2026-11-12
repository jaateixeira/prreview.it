# Use cases

Three actors with fixed roles ([ADR 0017](../adr/0017-actors-calls-and-invitations.md)): **Organizer**, **Author**, **Reviewer**. A Member can hold several roles, and a verified email is enough. Author and Reviewer work as **Parties**: a user or a group. An **Auditor** is reserved for later. Use cases are grouped into the three key processes.

```mermaid
flowchart LR
    ORG([Organizer])
    AUT([Author])
    REV([Reviewer])
    AUD([Auditor, later])
    ADM([Organization admin])
    LMS([Moodle or other LMS])

    subgraph Previewit
        UC1("Create space, invite members, form groups")
        UC2("Create call with rubric")
        UC3("Configure round: deadline, anonymity, allocation")
        UC4("Allocate reviews")
        UC5("Release feedback")
        UC6("Export scores")
        UC7("Submit work or a revision")
        UC8("Share a link for review")
        UC9("Read feedback and respond")
        UC10("Review: annotate and score")
        UC11("Manage members, usage and data")
        UC12("Launch from a course, return grades")
        UC13("Send call for authors: public or token link")
        UC14("Send call for reviewers: personal invitations")
        UC15("Open invitation, verify email")
        UC16("Audit the review process")
    end

    ORG --- UC1 & UC2 & UC3 & UC4 & UC5 & UC6 & UC13 & UC14
    AUT --- UC7 & UC8 & UC9
    REV --- UC10 & UC15
    AUD -.- UC16
    ADM --- UC11
    LMS --- UC12
```

## The three key processes

| Process | Actors | Use cases |
|---|---|---|
| **1. Organizing a call for authors** | Organizer, Author | Create space, create call, send call for authors, submit work or a revision |
| **2. Organizing peer review of the items** | Organizer | Create rubric, configure round, allocate, send call for reviewers, follow progress, release feedback, export scores |
| **3. Reviewing work by invitation** | Reviewer, Organizer | Send call for reviewers, open invitation and verify email, review, read feedback (if also an author) |

## Use cases

| Use case | Milestone | Notes |
|---|---|---|
| Create space, invite members, form groups | M1 | Education preset: space = course. Roles are organizer, author, reviewer (step B of ADR 0017) |
| Create call with rubric | M2, M3 | Call = assignment in Education |
| Send call for authors | M2, MA step C (done) | Public (plain URL) or protected (URL with token); revoke or replace the token |
| Send call for reviewers | MA step D (done) | One personal invitation per reviewer, bound to an email, carrying the work to review |
| Open invitation, verify email | MA step D (done) | A verified email is the only requirement |
| Audit the review process | Deferred | Auditor: read-only over reviews, allocation and the edit trail |
| Submit work or a revision | M2 | Text and PDF; individual or group |
| Share a link for review | M2 | Minimal sign-up; counts toward the 100-share free limit |
| Configure round, allocate reviews | M4 | Random, round-robin, manual; never self or own group |
| Review: annotate and score | M5 | One shared review per reviewing group |
| Release feedback, read and respond | M6 | Identities shown only as the anonymity policy allows |
| Export scores | M7 | CSV, for the Moodle gradebook |
| Manage members, usage and data | M1, M8 | Quotas: 50 MB, 100 shares; GDPR export and deletion |
| Launch from a course, return grades | M9 | LTI 1.3 |
