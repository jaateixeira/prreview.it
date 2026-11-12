# Use cases

All planned; milestones in the table. Author and Reviewer are **Parties**: a user or a group. One person is often both.

```mermaid
flowchart LR
    ORG([Organizer])
    AUT([Author])
    REV([Reviewer])
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
    end

    ORG --- UC1 & UC2 & UC3 & UC4 & UC5 & UC6
    AUT --- UC7 & UC8 & UC9
    REV --- UC10
    ADM --- UC11
    LMS --- UC12
```

| Use case | Milestone | Notes |
|---|---|---|
| Create space, invite members, form groups | M1 | Education preset: space = course |
| Create call with rubric | M2, M3 | Call = assignment |
| Submit work or a revision | M2 | Text and PDF; individual or group |
| Share a link for review | M2 | Minimal sign-up; counts toward the 100-share free limit |
| Configure round, allocate reviews | M4 | Random, round-robin, manual; never self or own group |
| Review: annotate and score | M5 | One shared review per reviewing group |
| Release feedback, read and respond | M6 | Identities shown only as the anonymity policy allows |
| Export scores | M7 | CSV, for the Moodle gradebook |
| Manage members, usage and data | M1, M8 | Quotas: 50 MB, 100 shares; GDPR export and deletion |
| Launch from a course, return grades | M9 | LTI 1.3 |
