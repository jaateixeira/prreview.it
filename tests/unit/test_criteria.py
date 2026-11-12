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
