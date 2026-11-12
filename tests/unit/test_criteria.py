import pytest

from previewit.application.criteria import (
    CriterionError,
    CriterionRegistry,
    CriterionType,
    UnknownCriterionType,
)
from previewit.plugins.criteria import (
    LevelsCriterion,
    NumericCriterion,
    TextCriterion,
    YesNoCriterion,
)

ALL = (NumericCriterion, LevelsCriterion, YesNoCriterion, TextCriterion)


@pytest.mark.parametrize("cls", ALL)
def test_every_builtin_satisfies_the_plugin_api(cls):
    assert isinstance(cls(), CriterionType)


def test_numeric():
    n = NumericCriterion()
    cfg = n.parse_config({"min": "1", "max": "5"})
    assert cfg == {"min": 1, "max": 5} and n.max_score(cfg) == 5 and n.describe(cfg) == "1 to 5"
    assert 'min="1"' in n.render_html(cfg, "x") and 'max="5"' in n.render_html(cfg, "x")
    for bad in ({"min": "a", "max": "5"}, {"min": "5", "max": "5"}, {"min": "-1", "max": "5"},
                {"min": "0", "max": "100"}, {}):  # fmt: skip
        with pytest.raises(CriterionError):
            n.parse_config(bad)


def test_levels():
    lv = LevelsCriterion()
    cfg = lv.parse_config({"levels": "Low | weak\r\n\nHigh | strong <b>\nMid"})
    assert [x["label"] for x in cfg["levels"]] == ["Low", "High", "Mid"]
    assert cfg["levels"][2]["descriptor"] == "" and lv.max_score(cfg) == 3
    assert lv.describe(cfg) == "Low / High / Mid"
    html = lv.render_html(cfg, "c")
    assert html.count('type="radio"') == 3 and "&lt;b&gt;" in html and "<b>" not in html
    for bad in ("", "One | only", "\n".join(f"L{i}" for i in range(9)), "| no name"):
        with pytest.raises(CriterionError):
            lv.parse_config({"levels": bad})


def test_yes_no_and_text():
    yn = YesNoCriterion()
    assert yn.parse_config({}) == {} and yn.max_score({}) == 1
    assert yn.render_html({}, "c").count("radio") == 2
    t = TextCriterion()
    assert t.parse_config({}) == {"max_length": 2000} and t.max_score({"max_length": 5}) is None
    assert 'maxlength="50"' in t.render_html({"max_length": 50}, "c")
    for bad in ("0", "10001", "many"):
        with pytest.raises(CriterionError):
            t.parse_config({"max_length": bad})


def test_the_input_name_is_escaped():
    assert '"><script>' not in NumericCriterion().render_html({"min": 1, "max": 2}, '"><script>')


def test_registry():
    reg = CriterionRegistry([NumericCriterion(), TextCriterion()])
    assert [t.key for t in reg.all()] == ["numeric", "text"]
    with pytest.raises(UnknownCriterionType):
        reg.get("nope")
    with pytest.raises(ValueError, match="twice"):
        reg.register(NumericCriterion())


# --- answers -----------------------------------------------------------------------------------


def test_numeric_answers_are_checked_and_scored():
    n, cfg = NumericCriterion(), {"min": 1, "max": 5}
    assert n.check_answer(cfg, " 3 ") == "3" and n.check_answer(cfg, "") == ""
    for bad in ("0", "6", "x", "2.5"):
        with pytest.raises(CriterionError):
            n.check_answer(cfg, bad)
    assert n.score(cfg, "3") == 3
    assert 'value="3"' in n.render_html(cfg, "c", "3") and "value=" not in n.render_html(cfg, "c")


def test_level_answers_are_checked_and_shown_checked():
    lv = LevelsCriterion()
    cfg = lv.parse_config({"levels": "Low | a\nHigh | b"})
    assert lv.check_answer(cfg, "2") == "2" and lv.check_answer(cfg, " ") == ""
    for bad in ("0", "3", "high", "-1"):
        with pytest.raises(CriterionError):
            lv.check_answer(cfg, bad)
    assert lv.score(cfg, "2") == 2
    assert lv.render_html(cfg, "c", "2").count("checked") == 1


def test_yes_no_answers():
    yn = YesNoCriterion()
    assert [yn.check_answer({}, v) for v in ("1", "0", "")] == ["1", "0", ""]
    with pytest.raises(CriterionError):
        yn.check_answer({}, "maybe")
    assert yn.score({}, "0") == 0
    assert yn.render_html({}, "c", "0").count("checked") == 1


def test_text_answers_are_trimmed_limited_escaped_and_not_scored():
    t, cfg = TextCriterion(), {"max_length": 10}
    assert t.check_answer(cfg, "  hi  ") == "hi"
    with pytest.raises(CriterionError):
        t.check_answer(cfg, "x" * 11)
    assert t.score(cfg, "hi") is None
    assert "&lt;b&gt;" in t.render_html(cfg, "c", "<b>")
