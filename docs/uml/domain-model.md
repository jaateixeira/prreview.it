# Domain model

Source: `PLAN.md` section 2. Classes marked `built` exist in `src/previewit/domain/`; the rest are planned.

## Tenancy and parties

```mermaid
classDiagram
    direction LR
    class Organization {
        tenant
    }
    class User
    class Space {
        course, venue or team
    }
    class Group
    class Party {
        <<union>>
    }
    class UserParty {
        <<built>>
        +user_id: str
    }
    class GroupParty {
        <<built>>
        +group_id: str
    }
    Organization "1" o-- "*" User : member with org role
    Organization "1" *-- "*" Space
    Space "*" o-- "*" User : membership with roles
    Space "1" *-- "*" Group
    Group "*" o-- "*" User
    Party <|-- UserParty
    Party <|-- GroupParty
    UserParty ..> User
    GroupParty ..> Group
```

- A **Party** is the author of a submission or the writer of a review. Because both sides are a Party, all four directions work: user to user, user to group, group to user, group to group.
- There are three fixed roles in a Space, **organizer**, **author** and **reviewer**, and a Member holds a set of them ([ADR 0017](../adr/0017-actors-calls-and-invitations.md)). Presets only rename them. An auditor role is reserved. Every tenant-owned row carries `org_id`.
- Organizations as parties are deferred ([ADR 0006](../adr/0006-organizations-as-parties-deferred.md)).

## Calls, rounds and reviews

```mermaid
classDiagram
    direction LR
    class Call {
        call for authors
        +access: public or protected
    }
    class Invitation {
        call for reviewers
        +email
        +token hash
        +expires
        +revoked
        +accepted by
    }
    class Rubric
    class Criterion {
        +scale
        +weight
    }
    class Submission
    class Revision {
        +n: int
        +artifact_version
    }
    class ReviewRound {
        +n: int
        +opens
        +closes
        +targets_revision
        +allocation_strategy
    }
    class AnonymityPolicy {
        <<built>>
        +author_visible_to_reviewer: bool
        +reviewer_visible_to_author: bool
        +reviewer_visible_to_other_reviewers: bool
        +reveal_at: RevealAt
        +may_see_author(viewer, revealed) bool
        +may_see_reviewer(viewer, revealed) bool
    }
    class RevealAt {
        <<built>>
        NEVER
        ROUND_CLOSE
        DECISION
    }
    class ReviewTask
    class Review
    class CriterionScore {
        +score
        +comment
    }
    class Annotation {
        +selector
        +body
    }
    class AuthorResponse
    class Decision {
        +outcome
    }
    class Party

    Call "1" --> "1" Rubric
    Rubric "1" *-- "*" Criterion
    Call "1" *-- "*" Submission
    Submission "*" --> "1" Party : author
    Submission "1" *-- "1..*" Revision
    Call "1" *-- "1..*" ReviewRound
    ReviewRound "1" *-- "*" Invitation
    Invitation "*" --> "*" ReviewTask : carries
    ReviewRound "1" --> "1" AnonymityPolicy
    AnonymityPolicy --> RevealAt
    ReviewRound "1" *-- "*" ReviewTask
    ReviewTask "*" --> "1" Party : reviewer
    ReviewTask "*" --> "1" Submission : target
    ReviewTask "1" --> "0..1" Review
    Review "1" *-- "*" CriterionScore
    CriterionScore "*" --> "1" Criterion
    Review "1" *-- "*" Annotation
    Submission "1" *-- "*" AuthorResponse
    Call "1" *-- "*" Decision
    Decision "*" --> "1" Submission
```

- **Call** is the call for authors. Its link is public (the plain URL) or protected (the URL with the token). An **Invitation** is one personal link of the call for reviewers: bound to an email, with its own token, carrying the review tasks of that reviewer. `Call.access` exists (step C): a protected call's token is a share link. `Invitation` exists (step D): its tasks are created when the invited person opens it.
- **Artifact** content is type-specific (text, PDF) and comes from a plugin. Versions are immutable, so annotations are pinned to a revision and never drift.
- **Annotation selector** is polymorphic: quote and offset for text, page and rectangles for PDF.
- **Cardinality is allocation.** One `ReviewTask` links one reviewer Party to one Submission; 1:1, 1:n, n:1 and n:n are choices of the allocation strategy.
- **Decision** and conflict-of-interest handling belong to the academic-venue preset (year 2).
