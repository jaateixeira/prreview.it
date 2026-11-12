# Behaviour

All flows are planned. Messages are written in plain words, not as function names; names are chosen when the code is written.

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
