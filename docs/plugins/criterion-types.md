# Writing a criterion type

A criterion type is one kind of question in a rubric. The built-ins are `numeric`, `levels`, `yes_no` and `text` (`src/previewit/plugins/criteria.py`). The API is not stable before v0.2.

```python
class CriterionType(Protocol):
    key: str  # stored with every criterion, e.g. "numeric"
    label: str  # shown in the builder
    fields: tuple[Field, ...]  # settings the author fills in

    def parse_config(self, raw: Mapping[str, str]) -> dict[str, Any]: ...
    def to_form(self, config: Mapping[str, Any]) -> dict[str, str]: ...
    def max_score(self, config: Mapping[str, Any]) -> int | None: ...
    def describe(self, config: Mapping[str, Any]) -> str: ...
    def render_html(self, config: Mapping[str, Any], name: str, value: str = "") -> str: ...
    def check_answer(self, config: Mapping[str, Any], raw: str) -> str: ...
    def score(self, config: Mapping[str, Any], value: str) -> int | None: ...
```

- `Field(name, label, kind, default, help)`: `kind` is `"int"` (number input) or `"lines"` (text area). The builder draws these generically.
- `parse_config` receives the submitted strings and returns the stored config (JSON-safe). Raise `CriterionError("a message for the author")` for anything unacceptable.
- `to_form` is the inverse: the config as the strings the form accepts, so editing round-trips.
- `max_score` is the highest score, or `None` when the answer is not a score (free text).
- `render_html` returns trusted HTML for the reviewer's input named `name`, showing `value` (a saved answer) when given. Escape every string that came from the author or the reviewer.
- `check_answer` validates what a reviewer submitted (a string) and returns it normalised, or `""` for no answer. Raise `CriterionError("a message for the reviewer")`. Answers are stored as these strings.
- `score` turns a normalised answer into a number, or `None` when the answer is not a score.
- Register it in `pyproject.toml` under `[project.entry-points."previewit.plugins"]`, for example `mytype = "my_package.module:MyType"`. Restart after installing.
- Plugins may import `previewit.application` and `previewit.domain`, never `previewit.adapters` (checked by `make layers`). The core never branches on a type key.
