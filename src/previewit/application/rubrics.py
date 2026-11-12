"""Rubrics and their criteria: building, reusing and attaching them to calls."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from previewit.application.criteria import CriterionRegistry, CriterionType
from previewit.application.ports import CallRepository, RubricRepository
from previewit.application.tenancy import Forbidden, NotFound, SpaceView, TenancyService
from previewit.domain.calls import CallId
from previewit.domain.identity import UserId
from previewit.domain.rubrics import (
    MAX_CRITERIA,
    Criterion,
    CriterionId,
    InvalidRubric,
    Rubric,
    RubricId,
    RubricTemplate,
    clean_criterion_title,
    clean_guidance,
    clean_rubric_name,
    clean_weight,
    templates_for,
)
from previewit.domain.tenancy import Permission, SpaceId


class RubricInUse(Exception):
    """A call uses this rubric; detach it first."""


@dataclass(frozen=True)
class CriterionView:
    criterion: Criterion
    type_label: str
    summary: str  # for example "1 to 5"
    max_score: int | None
    input_html: str  # the reviewer's input, rendered by the criterion plugin
    form_values: dict[str, str]  # the settings, as strings, to prefill the edit form


@dataclass(frozen=True)
class RubricView:
    rubric: Rubric
    space: SpaceView
    criteria: list[CriterionView]
    can_manage: bool
    total_weight: int
    used_by: int  # number of calls that use it


class RubricsService:
    def __init__(
        self,
        repo: RubricRepository,
        calls_repo: CallRepository,
        tenancy: TenancyService,
        registry: CriterionRegistry,
        new_id: Callable[[], str],
    ) -> None:
        self._repo = repo
        self._calls = calls_repo
        self._tenancy = tenancy
        self._registry = registry
        self._new_id = new_id

    # -- catalogue --------------------------------------------------------

    def criterion_types(self) -> list[CriterionType]:
        return self._registry.all()

    def templates(self, actor: UserId, space_id: SpaceId) -> tuple[RubricTemplate, ...]:
        view = self._manage_view(actor, space_id)
        return templates_for(view.organization.preset_key)

    # -- rubrics ----------------------------------------------------------

    def rubrics(self, actor: UserId, space_id: SpaceId) -> list[Rubric]:
        self._manage_view(actor, space_id)
        return self._repo.rubrics_in_space(space_id)

    def create_rubric(
        self,
        actor: UserId,
        space_id: SpaceId,
        name: str,
        description: str = "",
        template_key: str | None = None,
    ) -> Rubric:
        view = self._manage_view(actor, space_id)
        rubric = Rubric(
            RubricId(self._new_id()),
            view.space.org_id,
            space_id,
            clean_rubric_name(name),
            clean_guidance(description),
            actor,
        )
        criteria: list[Criterion] = []
        if template_key:
            template = next(
                (t for t in templates_for(view.organization.preset_key) if t.key == template_key),
                None,
            )
            if template is None:
                raise InvalidRubric("That template does not exist.")
            for position, item in enumerate(template.criteria):
                kind = self._registry.get(item.type_key)
                criteria.append(
                    Criterion(
                        CriterionId(self._new_id()),
                        rubric.org_id,
                        rubric.id,
                        position,
                        item.title,
                        item.guidance,
                        item.type_key,
                        kind.parse_config(item.raw_config),
                        item.weight,
                        item.required,
                    )
                )
        self._repo.add_rubric(rubric, criteria)
        return rubric

    def rubric_view(self, actor: UserId, rubric_id: RubricId) -> RubricView:
        rubric = self._repo.get_rubric(rubric_id)
        if rubric is None:
            raise NotFound
        view = self._tenancy.space_view(actor, rubric.space_id)
        manage = Permission.RUBRICS_MANAGE in view.permissions
        using = self._calls.calls_using_rubric(rubric.id)
        if not manage and not any(c.published for c in using):
            raise NotFound  # unpublished work-in-progress is the managers' business
        return self._build_view(rubric, view, manage, len(using))

    def update_rubric(
        self, actor: UserId, rubric_id: RubricId, name: str, description: str
    ) -> Rubric:
        rubric = self._managed(actor, rubric_id)
        updated = replace(
            rubric, name=clean_rubric_name(name), description=clean_guidance(description)
        )
        self._repo.update_rubric(updated)
        return updated

    def delete_rubric(self, actor: UserId, rubric_id: RubricId) -> None:
        rubric = self._managed(actor, rubric_id)
        if self._calls.calls_using_rubric(rubric.id):
            raise RubricInUse
        self._repo.delete_rubric(rubric.id)

    def duplicate_rubric(
        self,
        actor: UserId,
        rubric_id: RubricId,
        *,
        into_space: SpaceId | None = None,
        name: str | None = None,
    ) -> Rubric:
        """Copy a rubric, in this space or another you also manage (reuse across courses)."""
        source = self._managed(actor, rubric_id)
        target = into_space or source.space_id
        view = self._manage_view(actor, target)
        if view.space.org_id != source.org_id:
            raise NotFound  # never across organizations
        copy = Rubric(
            RubricId(self._new_id()),
            source.org_id,
            target,
            clean_rubric_name(name or f"{source.name} (copy)"),
            source.description,
            actor,
        )
        criteria = [
            replace(c, id=CriterionId(self._new_id()), rubric_id=copy.id)
            for c in self._repo.criteria_of(source.id)
        ]
        self._repo.add_rubric(copy, criteria)
        return copy

    # -- criteria ---------------------------------------------------------

    def add_criterion(
        self,
        actor: UserId,
        rubric_id: RubricId,
        *,
        type_key: str,
        title: str,
        guidance: str = "",
        raw_config: Mapping[str, str] | None = None,
        weight: int = 1,
        required: bool = True,
    ) -> Criterion:
        rubric = self._managed(actor, rubric_id)
        existing = self._repo.criteria_of(rubric.id)
        if len(existing) >= MAX_CRITERIA:
            raise InvalidRubric(f"A rubric may have at most {MAX_CRITERIA} criteria.")
        kind = self._registry.get(type_key)
        criterion = Criterion(
            CriterionId(self._new_id()),
            rubric.org_id,
            rubric.id,
            len(existing),
            clean_criterion_title(title),
            clean_guidance(guidance),
            type_key,
            kind.parse_config(raw_config or {}),
            clean_weight(weight),
            required,
        )
        self._repo.add_criterion(criterion)
        return criterion

    def update_criterion(
        self,
        actor: UserId,
        rubric_id: RubricId,
        criterion_id: CriterionId,
        *,
        title: str,
        guidance: str,
        raw_config: Mapping[str, str],
        weight: int,
        required: bool,
    ) -> Criterion:
        rubric = self._managed(actor, rubric_id)
        current = self._criterion_of(rubric, criterion_id)
        kind = self._registry.get(current.type_key)  # the type itself cannot change
        updated = replace(
            current,
            title=clean_criterion_title(title),
            guidance=clean_guidance(guidance),
            config=kind.parse_config(raw_config),
            weight=clean_weight(weight),
            required=required,
        )
        self._repo.update_criterion(updated)
        return updated

    def delete_criterion(
        self, actor: UserId, rubric_id: RubricId, criterion_id: CriterionId
    ) -> None:
        rubric = self._managed(actor, rubric_id)
        self._criterion_of(rubric, criterion_id)
        self._repo.delete_criterion(criterion_id)
        self._repo.set_positions(rubric.id, [c.id for c in self._repo.criteria_of(rubric.id)])

    def move_criterion(
        self, actor: UserId, rubric_id: RubricId, criterion_id: CriterionId, step: int
    ) -> None:
        """Move one place up (step -1) or down (step +1); the ends stay put."""
        rubric = self._managed(actor, rubric_id)
        self._criterion_of(rubric, criterion_id)
        order = [c.id for c in self._repo.criteria_of(rubric.id)]
        i = order.index(criterion_id)
        j = i + (1 if step > 0 else -1)
        if 0 <= j < len(order):
            order[i], order[j] = order[j], order[i]
        self._repo.set_positions(rubric.id, order)

    # -- calls ------------------------------------------------------------

    def attach(self, actor: UserId, call_id: CallId, rubric_id: RubricId | None) -> None:
        """Choose the rubric reviewers answer for a call (None detaches it)."""
        call = self._calls.get_call(call_id)
        if call is None:
            raise NotFound
        view = self._tenancy.space_view(actor, call.space_id)
        if Permission.CALLS_MANAGE not in view.permissions:
            raise Forbidden
        if rubric_id is not None:
            rubric = self._repo.get_rubric(rubric_id)
            if rubric is None or rubric.space_id != call.space_id:
                raise NotFound  # only this space's own rubrics; duplicate to reuse elsewhere
        self._calls.update_call(replace(call, rubric_id=rubric_id))

    def rubric_for_call(self, actor: UserId, call_id: CallId) -> RubricView | None:
        """The call's rubric as members see it, or None."""
        call = self._calls.get_call(call_id)
        if call is None or call.rubric_id is None:
            return None
        try:
            view = self._tenancy.space_view(actor, call.space_id)
        except NotFound:
            return None  # guests of a share link do not see the rubric
        manage = Permission.RUBRICS_MANAGE in view.permissions
        if not call.published and not manage:
            return None
        rubric = self._repo.get_rubric(call.rubric_id)
        if rubric is None:
            return None
        return self._build_view(rubric, view, False, len(self._calls.calls_using_rubric(rubric.id)))

    # -- helpers ----------------------------------------------------------

    def _manage_view(self, actor: UserId, space_id: SpaceId) -> SpaceView:
        view = self._tenancy.space_view(actor, space_id)
        if Permission.RUBRICS_MANAGE not in view.permissions:
            raise Forbidden
        return view

    def _managed(self, actor: UserId, rubric_id: RubricId) -> Rubric:
        rubric = self._repo.get_rubric(rubric_id)
        if rubric is None:
            raise NotFound
        self._manage_view(actor, rubric.space_id)
        return rubric

    def _criterion_of(self, rubric: Rubric, criterion_id: CriterionId) -> Criterion:
        criterion = self._repo.get_criterion(criterion_id)
        if criterion is None or criterion.rubric_id != rubric.id:
            raise NotFound
        return criterion

    def _build_view(
        self, rubric: Rubric, space: SpaceView, manage: bool, used_by: int
    ) -> RubricView:
        items: list[CriterionView] = []
        for c in self._repo.criteria_of(rubric.id):
            kind = self._registry.get(c.type_key)
            items.append(
                CriterionView(
                    c,
                    kind.label,
                    kind.describe(c.config),
                    kind.max_score(c.config),
                    kind.render_html(c.config, f"criterion-{c.id}"),
                    kind.to_form(c.config),
                )
            )
        total = sum(i.criterion.weight for i in items)
        return RubricView(rubric, space, items, manage, total, used_by)
