# Behaviour

All flows are planned. Messages are written in plain words, not as function names; names are chosen when the code is written.

## Process 1: organizing a call for authors (M2, step C)

```mermaid
sequenceDiagram
    actor O as Organizer
    actor A as Author
    participant P as Previewit

    O->>P: Create call (instructions, artifact type, deadline, access mode)
    O->>P: Publish
    P-->>O: Link (plain URL if public, URL with token if protected)
    O-)A: Sends the link
    A->>P: Open link
    alt Protected call
        P->>P: Check token (revoked or wrong: refuse)
    end
    P-->>A: Verify email, then the submission page
    A->>P: Submit work (revision 1)
    O->>P: Follow who has submitted
    O->>P: Revoke or replace the token (protected calls)
```

## Process 2: organizing peer review (M3, M4, step D done)

```mermaid
sequenceDiagram
    actor O as Organizer
    actor R as Reviewer
    participant P as Previewit

    O->>P: Build rubric, configure round (reviews each, anonymity, allocation)
    O->>P: Choose reviewers and allocate
    P->>P: Allocation: no conflicts, balanced load
    O->>P: Send call for reviewers
    P-->>O: One invitation link per reviewer
    alt Previewit sends it
        O->>P: Yes, with a cover letter
        P-)R: Email: cover letter and link
    else Organizer sends it
        O-)R: Sends the reviewer their link
    end
    Note over P: Round open: see process 3
    O->>P: Follow progress
    O->>P: Release feedback, open the next round
```

## Process 3: reviewing by invitation (M5, step D done)

```mermaid
sequenceDiagram
    actor R as Reviewer
    participant P as Previewit

    R->>P: Open invitation link
    P->>P: Check token (revoked, expired, closed round or wrong: refuse)
    P-->>R: Sign up or log in with the invited email, confirm it
    R->>P: Open the link again, press Start reviewing
    P->>P: Check the verified email is the invited one
    P->>P: Give the reviewer role, create the review tasks, drop the token from the URL
    P-->>R: My reviews: the allocated work
    loop For each task
        R->>P: Annotate and score (autosave)
    end
    R->>P: Submit review
```

## Review by link (M2, M5, M6)

The growth flow: one person asks another for a review with a link.

```mermaid
sequenceDiagram
    actor A as Author
    actor R as Reviewer
    participant W as Web adapter
    participant U as Use cases
    participant E as Entitlements
    participant D as Domain
    participant S as Database and storage

    A->>W: Upload work, ask for a review
    W->>U: Create share
    U->>E: May this user share and store this?
    E-->>U: Allowed (under 100 shares, under 50 MB)
    U->>D: Build submission, revision, review task
    U->>S: Save
    W-->>A: Link
    A-)R: Sends the link
    R->>W: Open link
    W-->>R: Minimal sign-up, then review workspace
    loop While reviewing
        R->>W: Annotate, score (HTMX autosave)
        W->>U: Save draft review
    end
    R->>W: Submit review
    U->>D: Apply anonymity policy through IdentityMask
    W-->>A: Feedback, names shown or hidden by policy
```

## Organized round (M2 to M6)

```mermaid
sequenceDiagram
    actor O as Organizer
    actor A as Authors
    actor R as Reviewers
    participant P as Previewit

    O->>P: Create call, rubric and round
    A->>P: Submit work
    Note over P: Round opens
    P->>P: Allocate: pure function of submissions, reviewers, constraints
    P-->>R: Review tasks
    R->>P: Annotate, score, submit
    Note over P: Round closes
    O->>P: Release feedback (or automatic release rule)
    P-->>A: Feedback
    A->>P: Respond, submit revision
    Note over P: Next round targets the new revision
```

Allocation invariants (property-tested): no self-review, no review of own group, exact number of reviews, balanced load.

## Review round lifecycle (proposed)

`PLAN.md` defines deadlines, release rules and rounds, but no named states. These are a proposal.

```mermaid
stateDiagram-v2
    [*] --> Draft
    Draft --> Scheduled: organizer confirms settings
    Scheduled --> Open: opens, tasks allocated
    Open --> Closed: closes (deadline)
    Closed --> Released: release rule or organizer
    Released --> [*]
```

A later round is a new `ReviewRound` that targets a later revision.

## Review task lifecycle (proposed)

```mermaid
stateDiagram-v2
    [*] --> Assigned
    Assigned --> InProgress: reviewer saves a draft
    InProgress --> Submitted: reviewer submits
    Assigned --> Missed: round closes
    InProgress --> Missed: round closes
    Submitted --> Released: round released
    Released --> [*]
    Missed --> [*]
```
