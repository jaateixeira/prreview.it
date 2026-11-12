# UML documentation

Diagrams are Mermaid, rendered by GitHub. They document the design in [`docs/PLAN.md`](../PLAN.md).

| Doc | View | Diagrams |
|---|---|---|
| [use-cases.md](use-cases.md) | Who does what | Use case |
| [domain-model.md](domain-model.md) | Concepts and relations | Class (2) |
| [architecture.md](architecture.md) | Layers, ports, plugins | Component |
| [behaviour.md](behaviour.md) | Flows and lifecycles | Sequence (2), state (2) |
| [../manuals/deployment-manual.md](../manuals/deployment-manual.md) | Runtime nodes | Deployment |
| [../research/review-designs.md](../research/review-designs.md) | Ten review designs from different industries | Class, sequence (3), state (3), activity (3) |

## Built or planned

Most of the system is not built yet. Each diagram marks its elements:

- **built**: in the code today (M0): `UserParty`, `GroupParty`, `AnonymityPolicy`, `RevealAt`, `Viewer`, the web skeleton (`/`, `/fragments/status`, `/healthz`).
- **planned**: designed in `PLAN.md`, with the milestone that delivers it.
- **proposed**: not in `PLAN.md`; a suggestion made in these docs. Confirm before building.

Update the diagram in the same pull request that changes the code it describes.
