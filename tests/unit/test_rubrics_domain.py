import pytest

from previewit.application.criteria import CriterionRegistry
from previewit.domain.rubrics import (
    EDUCATION_TEMPLATES,
    InvalidRubric,
    clean_criterion_title,
    clean_guidance,
    clean_rubric_name,
    clean_weight,
    templates_for,
)
from previewit.plugins.criteria import (
    LevelsCriterion,
    NumericCriterion,
    TextCriterion,
    YesNoCriterion,
)


def test_cleaning():
    assert clean_rubric_name("  Essay   rubric ") == "Essay rubric"
    assert clean_criterion_title(" Clarity ") == "Clarity"
    assert clean_guidance("  a\r\nb ") == "a\nb"
    for fn, bad in ((clean_rubric_name, ""), (clean_rubric_name, "x" * 101),
                    (clean_criterion_title, " "), (clean_guidance, "x" * 1001)):  # fmt: skip
        with pytest.raises(InvalidRubric):
            fn(bad)
    assert clean_weight(0) == 0 and clean_weight(100) == 100
    for bad in (-1, 101):
        with pytest.raises(InvalidRubric):
            clean_weight(bad)


def test_every_template_is_valid_for_the_installed_criterion_types():
    registry = CriterionRegistry(
        [NumericCriterion(), LevelsCriterion(), YesNoCriterion(), TextCriterion()]
    )
    assert EDUCATION_TEMPLATES and templates_for("no-such-preset") == ()
    for template in templates_for("education"):
        assert template.criteria
        for item in template.criteria:
            registry.get(item.type_key).parse_config(item.raw_config)  # must not raise
