"""Organizations, spaces, invite links, members and groups."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from previewit.adapters.web.kit import WebKit
from previewit.application.tenancy import (
    InvalidInvite,
    NotAMember,
    TenancyService,
)
from previewit.domain.identity import User, UserId
from previewit.domain.tenancy import (
    DEFAULT_ROLES,
    PRESETS,
    GroupId,
    InvalidName,
    OrgId,
    OrgRole,
    Permission,
    Role,
    SpaceId,
    get_preset,
)


class LoginRequired(Exception):
    pass


def current_user(request: Request) -> User:
    user: User | None = request.state.user
    if user is None:
        raise LoginRequired
    return user


def build_tenancy_router(*, tenancy: TenancyService, kit: WebKit) -> APIRouter:
    router = APIRouter()
    run = run_in_threadpool

    def space_page(
        request: Request,
        user: User,
        space_id: str,
        *,
        error: str | None = None,
        new_link: str | None = None,
        status: int = 200,
    ) -> Response:
        sid = SpaceId(space_id)
        view = tenancy.space_view(user.id, sid)
        members = tenancy.members(user.id, sid)
        perms = {p.value for p in view.permissions}
        invites = (
            tenancy.invites(user.id, sid) if Permission.MEMBERS_INVITE in view.permissions else []
        )
        names = {m.user_id: m.display_name for m in members}
        groups = tenancy.groups(user.id, sid)
        return kit.render(
            request,
            "space.html",
            {
                "page_title": view.space.name,
                "view": view,
                "word": view.preset.word,
                "role_options": [(r.value, view.preset.word(r.value).capitalize()) for r in Role],
                "default_roles": {r.value for r in DEFAULT_ROLES},
                "role_label": lambda roles: view.preset.role_label(roles).capitalize(),
                "members": members,
                "names": names,
                "perms": perms,
                "invites": invites,
                "groups": groups,
                "error": error,
                "new_link": new_link,
                "me": user.id,
            },
            status,
        )

    async def form_action(request: Request, space_id: str, action) -> Response:
        """CSRF check, login check, run `action(user, SpaceId)`, redirect back to the space."""
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        user = current_user(request)
        try:
            await run(action, user.id, SpaceId(space_id), form)
        except InvalidName:
            return await run(
                lambda: space_page(
                    request, user, space_id, error="Names must be 1-100 characters.", status=400
                )
            )
        except NotAMember:
            return await run(
                lambda: space_page(
                    request, user, space_id, error="That person is not a member here.", status=400
                )
            )
        return RedirectResponse(f"/spaces/{space_id}", status_code=303)

    # -- organizations ------------------------------------------------------------------

    def dashboard_response(
        request: Request, user: User, error: str | None = None, status: int = 200
    ) -> Response:
        orgs = tenancy.my_organizations(user.id)
        return kit.render(
            request,
            "spaces.html",
            {
                "page_title": "Your spaces",
                "spaces": tenancy.my_spaces(user.id),
                "orgs": [(o, r is OrgRole.OWNER) for o, r in orgs],
                "presets": [(p.key, p.label) for p in PRESETS.values()],
                "error": error,
            },
            status,
        )

    def org_response(
        request: Request, user: User, org_id: str, error: str | None = None, status: int = 200
    ) -> Response:
        spaces = tenancy.org_spaces(user.id, OrgId(org_id))  # NotFound for outsiders
        org, role = next((o, r) for o, r in tenancy.my_organizations(user.id) if o.id == org_id)
        preset = get_preset(org.preset_key)
        assert preset is not None
        return kit.render(
            request,
            "org.html",
            {
                "page_title": org.name,
                "org": org,
                "spaces": spaces,
                "is_owner": role is OrgRole.OWNER,
                "word": preset.word,
                "error": error,
            },
            status,
        )

    @router.get("/spaces", response_class=HTMLResponse)
    async def dashboard(request: Request) -> Response:
        return await run(dashboard_response, request, current_user(request))

    @router.post("/orgs")
    async def create_org(request: Request) -> Response:
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        user = current_user(request)
        try:
            org = await run(
                tenancy.create_organization,
                user.id,
                kit.text(form, "name"),
                kit.text(form, "preset"),
            )
        except (InvalidName, ValueError):
            message = "Give the organization a name (1-100 characters)."
            return await run(dashboard_response, request, user, message, 400)
        return RedirectResponse(f"/orgs/{org.id}", status_code=303)

    @router.get("/orgs/{org_id}", response_class=HTMLResponse)
    async def org_page(request: Request, org_id: str) -> Response:
        return await run(org_response, request, current_user(request), org_id)

    @router.post("/orgs/{org_id}/spaces")
    async def create_space(request: Request, org_id: str) -> Response:
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        user = current_user(request)
        try:
            space = await run(tenancy.create_space, user.id, OrgId(org_id), kit.text(form, "name"))
        except InvalidName:
            message = "Names must be 1-100 characters."
            return await run(org_response, request, user, org_id, message, 400)
        return RedirectResponse(f"/spaces/{space.id}", status_code=303)

    # -- a space ----------------------------------------------------------------------------

    @router.get("/spaces/{space_id}", response_class=HTMLResponse)
    async def space(request: Request, space_id: str) -> Response:
        user = current_user(request)
        return await run(space_page, request, user, space_id)

    # invites
    @router.post("/spaces/{space_id}/invites")
    async def create_invite(request: Request, space_id: str) -> Response:
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        user = current_user(request)
        roles = kit.texts(form, "roles")
        if not roles:
            return await run(
                lambda: space_page(
                    request, user, space_id, error="Choose at least one role.", status=400
                )
            )
        try:
            days = min(max(int(kit.text(form, "days") or "7"), 1), 90)
            raw_uses = kit.text(form, "max_uses").strip()
            max_uses = max(int(raw_uses), 1) if raw_uses else None
        except ValueError:
            return await run(
                lambda: space_page(
                    request,
                    user,
                    space_id,
                    error="Days and uses must be whole numbers.",
                    status=400,
                )
            )
        _, token = await run(
            lambda: tenancy.create_invite(
                user.id,
                SpaceId(space_id),
                roles=roles,
                ttl=timedelta(days=days),
                max_uses=max_uses,
            )
        )
        link = f"{kit.settings.origin}/join/{token}"
        return await run(lambda: space_page(request, user, space_id, new_link=link))

    @router.post("/spaces/{space_id}/invites/{invite_id}/revoke")
    async def revoke_invite(request: Request, space_id: str, invite_id: str) -> Response:
        return await form_action(
            request, space_id, lambda uid, sid, _f: tenancy.revoke_invite(uid, sid, invite_id)
        )

    # members
    @router.post("/spaces/{space_id}/members/{user_id}/role")
    async def change_roles(request: Request, space_id: str, user_id: str) -> Response:
        return await form_action(
            request,
            space_id,
            lambda uid, sid, f: tenancy.change_roles(
                uid, sid, UserId(user_id), kit.texts(f, "roles")
            ),
        )

    @router.post("/spaces/{space_id}/members/{user_id}/remove")
    async def remove_member(request: Request, space_id: str, user_id: str) -> Response:
        return await form_action(
            request, space_id, lambda uid, sid, _f: tenancy.remove_member(uid, sid, UserId(user_id))
        )

    # groups
    @router.post("/spaces/{space_id}/groups")
    async def create_group(request: Request, space_id: str) -> Response:
        return await form_action(
            request,
            space_id,
            lambda uid, sid, f: tenancy.create_group(uid, sid, kit.text(f, "name")),
        )

    @router.post("/spaces/{space_id}/groups/{group_id}/rename")
    async def rename_group(request: Request, space_id: str, group_id: str) -> Response:
        return await form_action(
            request,
            space_id,
            lambda uid, sid, f: tenancy.rename_group(
                uid, sid, GroupId(group_id), kit.text(f, "name")
            ),
        )

    @router.post("/spaces/{space_id}/groups/{group_id}/delete")
    async def delete_group(request: Request, space_id: str, group_id: str) -> Response:
        return await form_action(
            request,
            space_id,
            lambda uid, sid, _f: tenancy.delete_group(uid, sid, GroupId(group_id)),
        )

    @router.post("/spaces/{space_id}/groups/{group_id}/members")
    async def add_to_group(request: Request, space_id: str, group_id: str) -> Response:
        return await form_action(
            request,
            space_id,
            lambda uid, sid, f: tenancy.add_to_group(
                uid, sid, GroupId(group_id), UserId(kit.text(f, "user_id"))
            ),
        )

    @router.post("/spaces/{space_id}/groups/{group_id}/members/{user_id}/remove")
    async def remove_from_group(
        request: Request, space_id: str, group_id: str, user_id: str
    ) -> Response:
        return await form_action(
            request,
            space_id,
            lambda uid, sid, _f: tenancy.remove_from_group(
                uid, sid, GroupId(group_id), UserId(user_id)
            ),
        )

    # -- joining by link ---------------------------------------------------------------------

    @router.get("/join/{token}", response_class=HTMLResponse)
    async def join_page(request: Request, token: str) -> Response:
        preview = await run(tenancy.preview_invite, token)
        if preview is None:
            raise InvalidInvite
        return kit.render(
            request,
            "join.html",
            {"page_title": f"Join {preview.space_name}", "preview": preview, "token": token},
        )

    @router.post("/join/{token}")
    async def join(request: Request, token: str) -> Response:
        form = await kit.checked_form(request)
        if form is None:
            return kit.forbidden()
        user = current_user(request)
        space = await run(tenancy.accept_invite, user.id, token)
        return RedirectResponse(f"/spaces/{space.id}", status_code=303)

    return router
