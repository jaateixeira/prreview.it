"""Built-in criterion types: numeric scale, named levels, yes/no, free text."""

from __future__ import annotations

from collections.abc import Mapping
from html import escape
from typing import Any

from previewit.application.criteria import CriterionError, Field

MAX_LEVELS = 8
MAX_SCALE = 100


def _int(raw: Mapping[str, str], name: str, label: str) -> int:
    try:
        return int((raw.get(name) or "").strip())
    except ValueError:
        raise CriterionError(f"{label} must be a whole number.") from None


class NumericCriterion:
    key = "numeric"
    label = "Number scale"
    fields = (
        Field("min", "Lowest value", "int", "1"),
        Field("max", "Highest value", "int", "5"),
    )

    def parse_config(self, raw: Mapping[str, str]) -> dict[str, Any]:
        low, high = _int(raw, "min", "The lowest value"), _int(raw, "max", "The highest value")
        if low < 0 or high <= low:
            raise CriterionError("The highest value must be larger than the lowest, from 0 up.")
        if high - low + 1 > MAX_SCALE:
            raise CriterionError(f"A scale may have at most {MAX_SCALE} steps.")
        return {"min": low, "max": high}

    def to_form(self, config: Mapping[str, Any]) -> dict[str, str]:
        return {"min": str(config["min"]), "max": str(config["max"])}

    def max_score(self, config: Mapping[str, Any]) -> int | None:
        return int(config["max"])

    def describe(self, config: Mapping[str, Any]) -> str:
        return f"{config['min']} to {config['max']}"

    def render_html(self, config: Mapping[str, Any], name: str, value: str = "") -> str:
        shown = f' value="{escape(value, quote=True)}"' if value else ""
        return (
            f'<input type="number" name="{escape(name, quote=True)}" '
            f'min="{int(config["min"])}" max="{int(config["max"])}" step="1"{shown}>'
        )

    def check_answer(self, config: Mapping[str, Any], raw: str) -> str:
        raw = raw.strip()
        if not raw:
            return ""
        try:
            number = int(raw)
        except ValueError:
            raise CriterionError("Answer with a whole number.") from None
        if not int(config["min"]) <= number <= int(config["max"]):
            raise CriterionError(f"Answer between {config['min']} and {config['max']}.")
        return str(number)

    def score(self, config: Mapping[str, Any], value: str) -> int | None:
        return int(value)


class LevelsCriterion:
    key = "levels"
    label = "Levels with descriptions"
    fields = (
        Field(
            "levels",
            "Levels, lowest first",
            "lines",
            "Low | What low looks like\nHigh | What high looks like",
            "One level per line: name | description. 2 to 8 levels.",
        ),
    )

    def parse_config(self, raw: Mapping[str, str]) -> dict[str, Any]:
        levels: list[dict[str, str]] = []
        for line in (raw.get("levels") or "").replace("\r\n", "\n").split("\n"):
            if not line.strip():
                continue
            label, _, descriptor = line.partition("|")
            label, descriptor = " ".join(label.split()), " ".join(descriptor.split())
            if not label or len(label) > 60 or len(descriptor) > 300:
                raise CriterionError("Each level needs a short name, then | and a description.")
            levels.append({"label": label, "descriptor": descriptor})
        if not 2 <= len(levels) <= MAX_LEVELS:
            raise CriterionError(f"Give between 2 and {MAX_LEVELS} levels.")
        return {"levels": levels}

    def to_form(self, config: Mapping[str, Any]) -> dict[str, str]:
        lines = (f"{lv['label']} | {lv['descriptor']}" for lv in config["levels"])
        return {"levels": "\n".join(lines)}

    def max_score(self, config: Mapping[str, Any]) -> int | None:
        return len(config["levels"])

    def describe(self, config: Mapping[str, Any]) -> str:
        return " / ".join(level["label"] for level in config["levels"])

    def render_html(self, config: Mapping[str, Any], name: str, value: str = "") -> str:
        field = escape(name, quote=True)
        items = []
        for i, level in enumerate(config["levels"], start=1):
            checked = " checked" if value == str(i) else ""
            items.append(
                f'<label class="level"><input type="radio" name="{field}" value="{i}"{checked}> '
                f"<strong>{escape(level['label'])}</strong> "
                f"<small>{escape(level['descriptor'])}</small></label>"
            )
        return '<div class="levels">' + "".join(items) + "</div>"

    def check_answer(self, config: Mapping[str, Any], raw: str) -> str:
        raw = raw.strip()
        if not raw:
            return ""
        if not raw.isdigit() or not 1 <= int(raw) <= len(config["levels"]):
            raise CriterionError("Choose one of the levels.")
        return str(int(raw))

    def score(self, config: Mapping[str, Any], value: str) -> int | None:
        return int(value)


class YesNoCriterion:
    key = "yes_no"
    label = "Yes or no"
    fields = ()

    def parse_config(self, raw: Mapping[str, str]) -> dict[str, Any]:
        return {}

    def to_form(self, config: Mapping[str, Any]) -> dict[str, str]:
        return {}

    def max_score(self, config: Mapping[str, Any]) -> int | None:
        return 1

    def describe(self, config: Mapping[str, Any]) -> str:
        return "yes / no"

    def render_html(self, config: Mapping[str, Any], name: str, value: str = "") -> str:
        field = escape(name, quote=True)
        yes, no = (" checked" if value == "1" else ""), (" checked" if value == "0" else "")
        return (
            f'<label><input type="radio" name="{field}" value="1"{yes}> Yes</label> '
            f'<label><input type="radio" name="{field}" value="0"{no}> No</label>'
        )

    def check_answer(self, config: Mapping[str, Any], raw: str) -> str:
        raw = raw.strip()
        if raw not in ("", "0", "1"):
            raise CriterionError("Answer yes or no.")
        return raw

    def score(self, config: Mapping[str, Any], value: str) -> int | None:
        return int(value)


class TextCriterion:
    key = "text"
    label = "Free text"
    fields = (Field("max_length", "Longest answer (characters)", "int", "2000"),)

    def parse_config(self, raw: Mapping[str, str]) -> dict[str, Any]:
        value = (raw.get("max_length") or "2000").strip()
        try:
            length = int(value)
        except ValueError:
            raise CriterionError("The longest answer must be a whole number.") from None
        if not 1 <= length <= 10_000:
            raise CriterionError("The longest answer must be between 1 and 10000 characters.")
        return {"max_length": length}

    def to_form(self, config: Mapping[str, Any]) -> dict[str, str]:
        return {"max_length": str(config["max_length"])}

    def max_score(self, config: Mapping[str, Any]) -> int | None:
        return None

    def describe(self, config: Mapping[str, Any]) -> str:
        return f"up to {config['max_length']} characters"

    def render_html(self, config: Mapping[str, Any], name: str, value: str = "") -> str:
        return (
            f'<textarea name="{escape(name, quote=True)}" rows="4" '
            f'maxlength="{int(config["max_length"])}">{escape(value)}</textarea>'
        )

    def check_answer(self, config: Mapping[str, Any], raw: str) -> str:
        text = raw.replace("\r\n", "\n").strip()
        if len(text) > int(config["max_length"]):
            raise CriterionError(f"Keep the answer under {config['max_length']} characters.")
        return text

    def score(self, config: Mapping[str, Any], value: str) -> int | None:
        return None
