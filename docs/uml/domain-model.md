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
    Space "*" o-- "*" User : membership with role
    Space "1" *-- "*" Group
    Group "*" o-- "*" User
    Party <|-- UserParty
    Party <|-- GroupParty
    UserParty ..> User
    GroupParty ..> Group
```

- A **Party** is the author of a submission or the writer of a review. Because both sides are a Party, all four directions work: user to user, user to group, group to user, group to group.
- Roles are data (named permission sets), not code. Every tenant-owned row carries `org_id`.
- Organizations as parties are deferred ([ADR 0006](../adr/0006-organizations-as-parties-deferred.md)).

## Calls, rounds and reviews

```mermaid
classDiagram
    direction LR
    class Call {
        assignment or call for papers
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

- **Artifact** content is type-specific (text, PDF) and comes from a plugin. Versions are immutable, so annotations are pinned to a revision and never drift.
- **Annotation selector** is polymorphic: quote and offset for text, page and rectangles for PDF.
- **Cardinality is allocation.** One `ReviewTask` links one reviewer Party to one Submission; 1:1, 1:n, n:1 and n:n are choices of the allocation strategy.
- **Decision** and conflict-of-interest handling belong to the academic-venue preset (year 2).
