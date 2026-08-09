# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Teamspace visibility and open creation.

Private teamspaces work like private GitHub orgs: hidden from users who are
not members, including global reviewers. Deployment admins retain operational
access. Visibility is changed only by team owners and deployment admins.
Creation is open to every signed-in user, who becomes the new teamspace owner.
The lifecycle matrix covers every global role across public, private, and
personal creation, discovery, join-request, leave, and deletion policies.
"""

from __future__ import annotations

import hashlib
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.deps import get_current_user, get_db
from api.routes.teams import router as teams_router
from models.agent import Agent
from models.base import Base
from models.component_source import ComponentSource
from models.hook import HookListing
from models.inbox import InboxItem, InboxItemEvent, InboxKind, InboxState
from models.mcp import McpListing
from models.prompt import PromptListing
from models.sandbox import SandboxListing
from models.skill import SkillListing
from models.team import Team, TeamJoinRequestStatus, TeamMembership, TeamMembershipRequest, TeamRole
from models.team_invite import TeamInvite
from models.user import User, UserRole

_GLOBAL_ROLES = (UserRole.user, UserRole.reviewer, UserRole.admin, UserRole.super_admin)
_ADMIN_ROLES = (UserRole.admin, UserRole.super_admin)

_TABLES = [
    User.__table__,
    Team.__table__,
    TeamMembership.__table__,
    TeamMembershipRequest.__table__,
    TeamInvite.__table__,
    InboxItem.__table__,
    InboxItemEvent.__table__,
    Agent.__table__,
    McpListing.__table__,
    SkillListing.__table__,
    HookListing.__table__,
    PromptListing.__table__,
    SandboxListing.__table__,
    ComponentSource.__table__,
]


@pytest_asyncio.fixture()
async def sessions():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _user(db, role=UserRole.user) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:8]}@example.test",
        username=uuid.uuid4().hex[:12],
        name="Test User",
        password_hash="x",
        role=role,
    )
    db.add(user)
    await db.flush()
    return user


async def _team(db, owner: User, *, private: bool = False, personal: bool = False) -> Team:
    team = Team(
        id=uuid.uuid4(),
        name="Test Team",
        handle=f"team-{uuid.uuid4().hex[:8]}",
        is_private=private,
        is_personal=personal,
        created_by=owner.id,
    )
    db.add(team)
    await db.flush()
    db.add(TeamMembership(team_id=team.id, user_id=owner.id, role=TeamRole.owner))
    await db.flush()
    return team


@asynccontextmanager
async def _client(sessions, actor: User):
    async with sessions() as session:
        app = FastAPI()
        app.include_router(teams_router)
        app.dependency_overrides[get_db] = lambda: session
        app.dependency_overrides[get_current_user] = lambda: actor
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, session


async def _seed(sessions):
    """A private team with an owner, reviewer, and member, plus bystanders."""
    async with sessions() as db:
        owner = await _user(db)
        team_reviewer = await _user(db)
        member = await _user(db)
        outsider = await _user(db)
        global_reviewer = await _user(db, role=UserRole.reviewer)
        admin = await _user(db, role=UserRole.admin)
        team = await _team(db, owner, private=True)
        db.add(TeamMembership(team_id=team.id, user_id=team_reviewer.id, role=TeamRole.reviewer))
        db.add(TeamMembership(team_id=team.id, user_id=member.id, role=TeamRole.member))
        await db.commit()
        return owner, team_reviewer, member, outsider, global_reviewer, admin, team


# ── Creation is open to everyone ─────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("role", _GLOBAL_ROLES)
@pytest.mark.parametrize("visibility", ["public", "private"])
async def test_any_signed_in_user_creates_a_teamspace_and_owns_it(sessions, role, visibility):
    async with sessions() as db:
        creator = await _user(db, role=role)
        await db.commit()
    async with _client(sessions, creator) as (client, _):
        response = await client.post(
            "/api/v1/teams",
            json={"name": "My Team", "handle": f"my-{uuid.uuid4().hex[:8]}", "visibility": visibility},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["role"] == "owner"
    assert body["visibility"] == "private"
    assert body["visibility_request_status"] == ("pending" if visibility == "public" else None)


@pytest.mark.asyncio
async def test_public_team_creation_is_locked_until_review_and_supports_self_approval(sessions):
    async with sessions() as db:
        reviewer = await _user(db, role=UserRole.reviewer)
        teammate = await _user(db)
        await db.commit()

    async with _client(sessions, reviewer) as (client, _):
        created = await client.post(
            "/api/v1/teams",
            json={"name": "Reviewed Team", "handle": f"reviewed-{uuid.uuid4().hex[:8]}", "visibility": "public"},
        )
        team_id = created.json()["id"]
        locked = await client.post(
            f"/api/v1/teams/{team_id}/members",
            json={"user_id": str(teammate.id), "role": "member"},
        )
        locked_update = await client.put(f"/api/v1/teams/{team_id}", json={"description": "Not yet"})
        queue = await client.get("/api/v1/teams/visibility-requests")
        approved = await client.post(f"/api/v1/teams/{team_id}/visibility-request/approve")

    assert created.json()["visibility_request_status"] == "pending"
    assert locked.status_code == 409
    assert locked_update.status_code == 409
    assert {row["team_id"] for row in queue.json()} == {team_id}
    assert approved.json()["visibility"] == "public"
    assert approved.json()["visibility_request_status"] == "approved"


@pytest.mark.asyncio
async def test_rejected_public_visibility_can_be_requested_again(sessions):
    async with sessions() as db:
        owner = await _user(db)
        reviewer = await _user(db, role=UserRole.reviewer)
        team = await _team(db, owner, private=True)
        await db.commit()

    requested = await _set_visibility(sessions, owner, team.id, "public")
    assert requested.json()["visibility_request_status"] == "pending"
    async with _client(sessions, reviewer) as (client, _):
        rejected = await client.post(
            f"/api/v1/teams/{team.id}/visibility-request/reject",
            json={"reason": "Incomplete profile"},
        )
    assert rejected.json()["visibility_request_status"] == "rejected"
    assert rejected.json()["visibility_rejection_reason"] == "Incomplete profile"

    requested_again = await _set_visibility(sessions, owner, team.id, "public")
    assert requested_again.json()["visibility_request_status"] == "pending"


# ── Private teamspaces are hidden from plain non-members ─────────────


@pytest.mark.asyncio
async def test_private_team_is_hidden_from_plain_non_members_everywhere(sessions):
    _owner, _rev, _member, outsider, _gr, _admin, team = await _seed(sessions)
    async with _client(sessions, outsider) as (client, _):
        listing = await client.get("/api/v1/teams/all")
        by_handle = await client.get(f"/api/v1/teams/by-handle/{team.handle}")
        detail = await client.get(f"/api/v1/teams/{team.id}")
        join = await client.post(f"/api/v1/teams/{team.id}/join-requests", json={})
    assert team.handle not in {row["handle"] for row in listing.json()}
    # Hidden and nonexistent are indistinguishable: 404 everywhere, never 403.
    assert by_handle.status_code == 404
    assert detail.status_code == 404
    assert join.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("role", _GLOBAL_ROLES)
@pytest.mark.parametrize("as_member", [False, True])
async def test_private_team_visibility_respects_global_role_and_membership(sessions, role, as_member):
    async with sessions() as db:
        owner = await _user(db)
        actor = await _user(db, role=role)
        team = await _team(db, owner, private=True)
        if as_member:
            db.add(TeamMembership(team_id=team.id, user_id=actor.id, role=TeamRole.member))
        await db.commit()

    async with _client(sessions, actor) as (client, _):
        listing = await client.get("/api/v1/teams/all")
        by_handle = await client.get(f"/api/v1/teams/by-handle/{team.handle}")
        detail = await client.get(f"/api/v1/teams/{team.id}")

    listed = {row["id"]: row for row in listing.json()}
    can_view = as_member or role in _ADMIN_ROLES
    if not can_view:
        assert str(team.id) not in listed
        assert by_handle.status_code == 404
        assert detail.status_code == 404
        return

    expected_team_role = "member" if as_member else None
    assert listed[str(team.id)]["role"] == expected_team_role
    assert by_handle.status_code == 200
    assert by_handle.json()["role"] == expected_team_role
    assert detail.status_code == 200
    assert detail.json()["role"] == expected_team_role


@pytest.mark.asyncio
@pytest.mark.parametrize("role", _GLOBAL_ROLES)
async def test_public_team_is_visible_to_every_global_role_without_granting_membership(sessions, role):
    async with sessions() as db:
        owner = await _user(db)
        actor = await _user(db, role=role)
        team = await _team(db, owner)
        await db.commit()

    async with _client(sessions, actor) as (client, _):
        listing = await client.get("/api/v1/teams/all")
        by_handle = await client.get(f"/api/v1/teams/by-handle/{team.handle}")
        detail = await client.get(f"/api/v1/teams/{team.id}")

    listed = {row["id"]: row for row in listing.json()}
    assert listed[str(team.id)]["role"] is None
    assert by_handle.status_code == 200
    assert by_handle.json()["role"] is None
    assert detail.status_code == 200
    assert detail.json()["role"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("role", _GLOBAL_ROLES)
async def test_personal_team_visibility_is_creator_or_admin_only(sessions, role):
    async with sessions() as db:
        creator = await _user(db)
        actor = await _user(db, role=role)
        team = await _team(db, creator, private=True, personal=True)
        await db.commit()

    async with _client(sessions, actor) as (client, _):
        listing = await client.get("/api/v1/teams/all")
        by_handle = await client.get(f"/api/v1/teams/by-handle/{team.handle}")
        detail = await client.get(f"/api/v1/teams/{team.id}")

    listed = {row["id"]: row for row in listing.json()}
    if role not in _ADMIN_ROLES:
        assert str(team.id) not in listed
        assert by_handle.status_code == 404
        assert detail.status_code == 404
        return

    assert listed[str(team.id)]["role"] is None
    assert by_handle.status_code == 200
    assert by_handle.json()["role"] is None
    assert detail.status_code == 200
    assert detail.json()["role"] is None


# ── Join requests across visibility and global roles ────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("role", _GLOBAL_ROLES)
async def test_public_team_accepts_join_requests_from_every_nonmember_tier(sessions, role):
    async with sessions() as db:
        owner = await _user(db)
        actor = await _user(db, role=role)
        team = await _team(db, owner)
        await db.commit()

    async with _client(sessions, actor) as (client, _):
        response = await client.post(f"/api/v1/teams/{team.id}/join-requests", json={})

    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert response.json()["invite_id"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("role", _GLOBAL_ROLES)
async def test_private_team_requires_an_invite_except_for_admin_tiers(sessions, role):
    token = f"invite-{uuid.uuid4().hex}"
    async with sessions() as db:
        owner = await _user(db)
        actor = await _user(db, role=role)
        team = await _team(db, owner, private=True)
        invite = TeamInvite(
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            name="Matrix invite",
            team_id=team.id,
            invited_by=owner.id,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        db.add(invite)
        await db.commit()

    async with _client(sessions, actor) as (client, _):
        if role not in _ADMIN_ROLES:
            hidden = await client.post(f"/api/v1/teams/{team.id}/join-requests", json={})
            assert hidden.status_code == 404
            response = await client.post(
                f"/api/v1/teams/{team.id}/join-requests",
                json={"invite_token": token},
            )
        else:
            response = await client.post(f"/api/v1/teams/{team.id}/join-requests", json={})

    assert response.status_code == 201
    assert response.json()["status"] == "pending"
    assert response.json()["invite_id"] == (str(invite.id) if role not in _ADMIN_ROLES else None)
    async with sessions() as db:
        stored_invite = await db.get(TeamInvite, invite.id)
        assert stored_invite.use_count == 0


@pytest.mark.asyncio
async def test_invite_uses_are_consumed_only_by_approved_memberships(sessions):
    token = f"invite-{uuid.uuid4().hex}"
    async with sessions() as db:
        owner = await _user(db)
        requester = await _user(db)
        team = await _team(db, owner, private=True)
        invite = TeamInvite(
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            name="One member invite",
            team_id=team.id,
            invited_by=owner.id,
            max_uses=1,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        db.add(invite)
        await db.commit()

    async with _client(sessions, requester) as (client, _):
        first = await client.post(
            f"/api/v1/teams/{team.id}/join-requests",
            json={"invite_token": token},
        )
        cancelled = await client.delete(f"/api/v1/teams/{team.id}/join-requests/{first.json()['id']}")
        second = await client.post(
            f"/api/v1/teams/{team.id}/join-requests",
            json={"invite_token": token},
        )
    assert cancelled.status_code == 204
    assert second.status_code == 201

    async with _client(sessions, owner) as (client, _):
        rejected = await client.post(
            f"/api/v1/teams/{team.id}/join-requests/{second.json()['id']}/reject",
            json={},
        )
        deleted = await client.delete(f"/api/v1/teams/{team.id}/invites/{invite.id}")
    assert rejected.status_code == 200
    assert deleted.status_code == 409

    async with sessions() as db:
        rows = (
            (await db.execute(select(TeamMembershipRequest).where(TeamMembershipRequest.team_id == team.id)))
            .scalars()
            .all()
        )
        membership_count = await db.scalar(
            select(func.count(TeamMembership.id)).where(
                TeamMembership.team_id == team.id,
                TeamMembership.user_id == requester.id,
            )
        )
        stored_invite = await db.get(TeamInvite, invite.id)
    assert all(row.invite_id == invite.id for row in rows)
    assert stored_invite is not None
    assert membership_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("role", _GLOBAL_ROLES)
async def test_personal_team_rejects_join_requests_from_every_tier(sessions, role):
    async with sessions() as db:
        creator = await _user(db)
        actor = await _user(db, role=role)
        team = await _team(db, creator, private=True, personal=True)
        await db.commit()

    async with _client(sessions, actor) as (client, _):
        response = await client.post(f"/api/v1/teams/{team.id}/join-requests", json={})

    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("role", _GLOBAL_ROLES)
@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("team_role", [TeamRole.member, TeamRole.reviewer, TeamRole.owner])
async def test_existing_members_cannot_request_to_join_again(sessions, role, private, team_role):
    async with sessions() as db:
        owner = await _user(db)
        actor = await _user(db, role=role)
        team = await _team(db, owner, private=private)
        db.add(TeamMembership(team_id=team.id, user_id=actor.id, role=team_role))
        await db.commit()

    async with _client(sessions, actor) as (client, _):
        response = await client.post(f"/api/v1/teams/{team.id}/join-requests", json={})

    assert response.status_code == 409
    assert "already a member" in response.json()["detail"]


# ── Changing visibility ──────────────────────────────────────────────


async def _set_visibility(sessions, actor, team_id, visibility):
    async with _client(sessions, actor) as (client, _):
        return await client.patch(f"/api/v1/teams/{team_id}/visibility", json={"visibility": visibility})


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["owner", "admin"])
async def test_owners_and_admins_request_public_visibility(sessions, who):
    owner, _team_reviewer, _member, _outsider, global_reviewer, admin, team = await _seed(sessions)
    actor = {"owner": owner, "admin": admin}[who]
    response = await _set_visibility(sessions, actor, team.id, "public")
    assert response.status_code == 200
    assert response.json()["visibility"] == "private"
    assert response.json()["visibility_request_status"] == "pending"

    async with _client(sessions, global_reviewer) as (client, _):
        approved = await client.post(f"/api/v1/teams/{team.id}/visibility-request/approve")
    assert approved.status_code == 200
    assert approved.json()["visibility"] == "public"

    unchanged = await _set_visibility(sessions, actor, team.id, "public")
    assert unchanged.status_code == 200
    assert unchanged.json()["visibility"] == "public"
    assert unchanged.json()["visibility_request_status"] == "approved"


@pytest.mark.asyncio
@pytest.mark.parametrize("who", ["team_reviewer", "member"])
async def test_non_owner_members_cannot_change_visibility(sessions, who):
    _owner, team_reviewer, member, _outsider, _gr, _admin, team = await _seed(sessions)
    actor = {"team_reviewer": team_reviewer, "member": member}[who]
    response = await _set_visibility(sessions, actor, team.id, "public")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_global_reviewer_cannot_see_or_change_private_team(sessions):
    _owner, _rev, _member, _outsider, global_reviewer, _admin, team = await _seed(sessions)
    async with _client(sessions, global_reviewer) as (client, _):
        listing = await client.get("/api/v1/teams/all")
        detail = await client.get(f"/api/v1/teams/by-handle/{team.handle}")
    response = await _set_visibility(sessions, global_reviewer, team.id, "public")
    assert team.handle not in {row["handle"] for row in listing.json()}
    assert detail.status_code == 404
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_outsider_gets_404_not_403_on_a_private_team(sessions):
    _owner, _rev, _member, outsider, _gr, _admin, team = await _seed(sessions)
    response = await _set_visibility(sessions, outsider, team.id, "public")
    assert response.status_code == 404


# ── Leaving regular teamspaces ──────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("role", _GLOBAL_ROLES)
@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("team_role", [TeamRole.member, TeamRole.reviewer])
async def test_non_owner_members_can_leave_at_every_tier(sessions, role, private, team_role):
    async with sessions() as db:
        owner = await _user(db)
        actor = await _user(db, role=role)
        team = await _team(db, owner, private=private)
        db.add(TeamMembership(team_id=team.id, user_id=actor.id, role=team_role))
        await db.commit()

    async with _client(sessions, actor) as (client, _):
        response = await client.post(f"/api/v1/teams/{team.id}/leave")

    assert response.status_code == 204
    async with sessions() as db:
        membership = await db.scalar(
            select(TeamMembership).where(
                TeamMembership.team_id == team.id,
                TeamMembership.user_id == actor.id,
            )
        )
        assert membership is None


@pytest.mark.asyncio
@pytest.mark.parametrize("role", _GLOBAL_ROLES)
@pytest.mark.parametrize("private", [False, True])
async def test_nonmembers_cannot_leave_at_any_tier(sessions, role, private):
    async with sessions() as db:
        owner = await _user(db)
        actor = await _user(db, role=role)
        team = await _team(db, owner, private=private)
        await db.commit()

    async with _client(sessions, actor) as (client, _):
        response = await client.post(f"/api/v1/teams/{team.id}/leave")

    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("role", _GLOBAL_ROLES)
@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("has_second_owner", [False, True])
async def test_owner_exit_preserves_a_team_owner_at_every_tier(sessions, role, private, has_second_owner):
    async with sessions() as db:
        actor = await _user(db, role=role)
        team = await _team(db, actor, private=private)
        if has_second_owner:
            second_owner = await _user(db)
            db.add(TeamMembership(team_id=team.id, user_id=second_owner.id, role=TeamRole.owner))
        await db.commit()

    async with _client(sessions, actor) as (client, _):
        response = await client.post(f"/api/v1/teams/{team.id}/leave")

    assert response.status_code == (204 if has_second_owner else 409)
    async with sessions() as db:
        owners = await db.scalar(
            select(func.count(TeamMembership.id)).where(
                TeamMembership.team_id == team.id,
                TeamMembership.role == TeamRole.owner,
            )
        )
        assert owners == 1


# ── Personal private teamspace claim ─────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("role", _GLOBAL_ROLES)
async def test_claim_creates_a_private_owned_teamspace_and_is_idempotent(sessions, role):
    async with sessions() as db:
        user = await _user(db, role=role)
        stranger = await _user(db)
        await db.commit()

    async with _client(sessions, user) as (client, _):
        first = await client.post("/api/v1/teams/claim-personal")
        assert first.status_code == 200, first.text
        body = first.json()
        again = await client.post("/api/v1/teams/claim-personal")
        mine = await client.get("/api/v1/teams")
        visible = await client.get("/api/v1/teams/all")
        by_handle = await client.get(f"/api/v1/teams/by-handle/{body['handle']}")
        leave = await client.post(f"/api/v1/teams/{body['id']}/leave")
    assert body["visibility"] == "private"
    assert body["is_personal"] is True
    assert body["role"] == "owner"
    assert body["handle"].startswith(user.username)
    # Claiming twice hands back the same teamspace, no duplicate.
    assert again.status_code == 200
    assert again.json()["id"] == body["id"]
    assert [team["id"] for team in mine.json() if team["is_personal"]] == [body["id"]]
    assert body["id"] in {team["id"] for team in visible.json()}
    assert by_handle.json()["role"] == "owner"
    assert leave.status_code == 409

    async with sessions() as db:
        count = await db.scalar(
            select(func.count(Team.id)).where(Team.created_by == user.id, Team.is_personal.is_(True))
        )
    assert count == 1

    # Private by default means hidden from other plain users.
    async with _client(sessions, stranger) as (client, _):
        listing = await client.get("/api/v1/teams/all")
    assert body["handle"] not in {t["handle"] for t in listing.json()}


@pytest.mark.asyncio
@pytest.mark.parametrize("role", _GLOBAL_ROLES)
async def test_empty_personal_teamspace_can_be_deleted(sessions, role):
    async with sessions() as db:
        creator = await _user(db, role=role)
        await db.commit()

    async with _client(sessions, creator) as (client, _):
        claimed = await client.post("/api/v1/teams/claim-personal")
        assert claimed.status_code == 200, claimed.text
        team_id = uuid.UUID(claimed.json()["id"])
        deleted = await client.delete(f"/api/v1/teams/{team_id}")

    assert deleted.status_code == 204
    async with sessions() as db:
        assert await db.get(Team, team_id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("role", _ADMIN_ROLES)
async def test_admin_tiers_can_delete_someone_elses_empty_personal_team(sessions, role):
    async with sessions() as db:
        creator = await _user(db)
        actor = await _user(db, role=role)
        team = await _team(db, creator, private=True, personal=True)
        await db.commit()

    async with _client(sessions, actor) as (client, _):
        response = await client.delete(f"/api/v1/teams/{team.id}")

    assert response.status_code == 204
    async with sessions() as db:
        assert await db.get(Team, team.id) is None


@pytest.mark.asyncio
async def test_personal_team_with_registry_items_cannot_be_deleted(sessions):
    async with sessions() as db:
        creator = await _user(db)
        team = await _team(db, creator, private=True, personal=True)
        db.add(
            McpListing(
                id=uuid.uuid4(),
                name="Personal Tool",
                namespace=team.handle,
                slug="personal-tool",
                category="general",
                owner=team.handle,
                submitted_by=creator.id,
                team_id=team.id,
                is_private=True,
            )
        )
        await db.commit()

    async with _client(sessions, creator) as (client, _):
        response = await client.delete(f"/api/v1/teams/{team.id}")

    assert response.status_code == 409
    assert "MCP server" in response.json()["detail"]


@pytest.mark.asyncio
async def test_personal_teamspace_repairs_and_enforces_strict_invariants(sessions):
    async with sessions() as db:
        creator = await _user(db)
        stranger = await _user(db)
        await db.commit()

    async with _client(sessions, creator) as (client, _):
        claimed = await client.post("/api/v1/teams/claim-personal")
    team_id = uuid.UUID(claimed.json()["id"])

    async with sessions() as db:
        creator_membership = await db.scalar(
            select(TeamMembership).where(
                TeamMembership.team_id == team_id,
                TeamMembership.user_id == creator.id,
            )
        )
        creator_membership.role = TeamRole.member
        db.add(TeamMembership(team_id=team_id, user_id=stranger.id, role=TeamRole.owner))
        await db.commit()

    async with _client(sessions, creator) as (client, _):
        repaired = await client.post("/api/v1/teams/claim-personal")

    assert repaired.status_code == 409
    assert "cannot have other members" in repaired.json()["detail"]

    async with sessions() as db:
        memberships = (
            (await db.execute(select(TeamMembership).where(TeamMembership.team_id == team_id))).scalars().all()
        )
    assert {(membership.user_id, membership.role) for membership in memberships} == {
        (creator.id, TeamRole.member),
        (stranger.id, TeamRole.owner),
    }


@pytest.mark.asyncio
async def test_claim_does_not_convert_a_legacy_named_team_with_other_members(sessions):
    async with sessions() as db:
        creator = await _user(db)
        teammate = await _user(db)
        team = Team(
            id=uuid.uuid4(),
            name="Shared Legacy Team",
            handle=f"{creator.username}-team",
            description="Your private teamspace for drafts and personal publishing.",
            is_private=True,
            created_by=creator.id,
        )
        db.add(team)
        await db.flush()
        db.add_all(
            [
                TeamMembership(team_id=team.id, user_id=creator.id, role=TeamRole.owner),
                TeamMembership(team_id=team.id, user_id=teammate.id, role=TeamRole.reviewer),
                McpListing(
                    id=uuid.uuid4(),
                    name="Shared Tool",
                    namespace=team.handle,
                    slug="shared-tool",
                    category="general",
                    owner=team.handle,
                    submitted_by=teammate.id,
                    team_id=team.id,
                    is_private=True,
                ),
            ]
        )
        await db.commit()

    async with _client(sessions, creator) as (client, _):
        claimed = await client.post("/api/v1/teams/claim-personal")

    assert claimed.status_code == 200
    assert claimed.json()["id"] != str(team.id)
    async with sessions() as db:
        original = await db.get(Team, team.id)
        memberships = (
            (await db.execute(select(TeamMembership).where(TeamMembership.team_id == team.id))).scalars().all()
        )
        listing = (
            await db.execute(select(McpListing.submitted_by, McpListing.team_id).where(McpListing.team_id == team.id))
        ).one()
    assert original.is_personal is False
    assert {membership.user_id for membership in memberships} == {creator.id, teammate.id}
    assert listing.submitted_by == teammate.id
    assert listing.team_id == team.id


@pytest.mark.asyncio
async def test_personal_conversion_cannot_approve_a_preexisting_join_request(sessions):
    async with sessions() as db:
        creator = await _user(db)
        requester = await _user(db)
        team = Team(
            id=uuid.uuid4(),
            name="Legacy Personal Team",
            handle=f"{creator.username}-team",
            description="Your private teamspace for drafts and personal publishing.",
            is_private=True,
            created_by=creator.id,
        )
        db.add(team)
        await db.flush()
        db.add(TeamMembership(team_id=team.id, user_id=creator.id, role=TeamRole.owner))
        request = TeamMembershipRequest(team_id=team.id, user_id=requester.id)
        db.add(request)
        await db.commit()

    async with _client(sessions, creator) as (client, _):
        claimed = await client.post("/api/v1/teams/claim-personal")
        approved = await client.post(f"/api/v1/teams/{team.id}/join-requests/{request.id}/approve")

    assert claimed.status_code == 200
    assert claimed.json()["id"] == str(team.id)
    assert approved.status_code == 409
    async with sessions() as db:
        member_count = await db.scalar(select(func.count(TeamMembership.id)).where(TeamMembership.team_id == team.id))
        stored_request = await db.get(TeamMembershipRequest, request.id)
    assert member_count == 1
    assert stored_request.status == TeamJoinRequestStatus.pending


@pytest.mark.asyncio
async def test_claim_does_not_reuse_a_regular_team_owned_by_the_user(sessions):
    async with sessions() as db:
        user = await _user(db)
        regular = Team(
            id=uuid.uuid4(),
            name="Regular Team",
            handle=f"{user.username}-team",
            created_by=user.id,
        )
        db.add(regular)
        await db.flush()
        db.add(TeamMembership(team_id=regular.id, user_id=user.id, role=TeamRole.owner))
        await db.commit()

    async with _client(sessions, user) as (client, _):
        response = await client.post("/api/v1/teams/claim-personal")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] != str(regular.id)
    assert body["is_personal"] is True


@pytest.mark.asyncio
async def test_claim_falls_back_when_the_derived_handle_is_taken(sessions):
    async with sessions() as db:
        user = await _user(db)
        squatter = await _user(db)
        taken = Team(
            id=uuid.uuid4(),
            name="Squatted",
            handle=f"{user.username}-team",
            created_by=squatter.id,
        )
        db.add(taken)
        await db.flush()
        db.add(TeamMembership(team_id=taken.id, user_id=squatter.id, role=TeamRole.owner))
        await db.commit()

    async with _client(sessions, user) as (client, _):
        response = await client.post("/api/v1/teams/claim-personal")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["handle"] != f"{user.username}-team"
    assert body["handle"].startswith(user.username[:20])
    assert body["role"] == "owner"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path_suffix",
    [
        ("get", "/join-requests"),
        ("get", "/members"),
        ("post", "/join-requests"),
    ],
)
async def test_private_team_owner_gated_routes_answer_404_not_403(sessions, method, path_suffix):
    """A non-member holding a private team's UUID must not tell hidden from
    absent: owner/member-gated routes answer 404, exactly like a missing team,
    never a 403 that confirms the team exists."""
    _owner, _rev, _member, outsider, _gr, _admin, team = await _seed(sessions)
    async with _client(sessions, outsider) as (client, _):
        caller = getattr(client, method)
        resp = await (
            caller(f"/api/v1/teams/{team.id}{path_suffix}", json={})
            if method == "post"
            else caller(f"/api/v1/teams/{team.id}{path_suffix}")
        )
    assert resp.status_code == 404, f"{method} {path_suffix} leaked existence with {resp.status_code}"


@pytest.mark.asyncio
async def test_public_team_owner_routes_still_403_for_non_members(sessions):
    """A public team is openly listed, so 403 there is correct and leaks nothing
    — only private teams switch to 404."""
    async with sessions() as db:
        owner = await _user(db)
        outsider = await _user(db)
        team = Team(id=uuid.uuid4(), name="Open", handle=f"open-{uuid.uuid4().hex[:8]}", created_by=owner.id)
        db.add(team)
        await db.flush()
        db.add(TeamMembership(team_id=team.id, user_id=owner.id, role=TeamRole.owner))
        await db.commit()
    async with _client(sessions, outsider) as (client, _):
        members = await client.get(f"/api/v1/teams/{team.id}/members")
        queue = await client.get(f"/api/v1/teams/{team.id}/join-requests")
    assert members.status_code == 403
    assert queue.status_code == 403


@pytest.mark.asyncio
async def test_visibility_review_notifies_reviewers_and_owner(sessions):
    async with sessions() as db:
        owner = await _user(db)
        reviewer = await _user(db, UserRole.reviewer)
        admin = await _user(db, UserRole.admin)
        team = await _team(db, owner, private=True)
        await db.commit()

    requested = await _set_visibility(sessions, owner, team.id, "public")
    assert requested.status_code == 200
    async with sessions() as db:
        pending = (
            (await db.execute(select(InboxItem).where(InboxItem.kind == InboxKind.team_created_pending)))
            .scalars()
            .all()
        )
    assert {item.user_id for item in pending} == {reviewer.id, admin.id}
    assert all(item.action_url == "/review?tab=teamspaces" for item in pending)

    async with _client(sessions, reviewer) as (client, _):
        rejected = await client.post(
            f"/api/v1/teams/{team.id}/visibility-request/reject",
            json={"reason": "More detail needed"},
        )
    assert rejected.status_code == 200
    async with sessions() as db:
        pending = (
            (await db.execute(select(InboxItem).where(InboxItem.kind == InboxKind.team_created_pending)))
            .scalars()
            .all()
        )
        decisions = (
            (await db.execute(select(InboxItem).where(InboxItem.kind == InboxKind.review_rejected))).scalars().all()
        )
    assert all(item.state == InboxState.done for item in pending)
    assert {item.user_id for item in decisions} == {owner.id}
    assert decisions[0].body == "More detail needed"


@pytest.mark.asyncio
async def test_team_cannot_go_private_while_it_owns_public_items(sessions):
    async with sessions() as db:
        owner = await _user(db)
        team = Team(id=uuid.uuid4(), name="Public Owner", handle=f"public-{uuid.uuid4().hex[:8]}", created_by=owner.id)
        db.add(team)
        await db.flush()
        db.add_all(
            [
                TeamMembership(team_id=team.id, user_id=owner.id, role=TeamRole.owner),
                McpListing(
                    id=uuid.uuid4(),
                    name="Public Tool",
                    namespace=team.handle,
                    slug="public-tool",
                    category="general",
                    owner=team.handle,
                    submitted_by=owner.id,
                    team_id=team.id,
                    is_private=False,
                ),
            ]
        )
        await db.commit()

    response = await _set_visibility(sessions, owner, team.id, "private")
    assert response.status_code == 409
    assert "MCP server" in response.json()["detail"]


@pytest.mark.asyncio
async def test_team_cannot_go_private_while_it_owns_a_public_component_source(sessions):
    async with sessions() as db:
        owner = await _user(db)
        team = await _team(db, owner)
        db.add(
            ComponentSource(
                id=uuid.uuid4(),
                url=f"https://github.com/example/{uuid.uuid4().hex}",
                provider="github",
                component_type="mcp",
                is_public=True,
                team_id=team.id,
            )
        )
        await db.commit()

    response = await _set_visibility(sessions, owner, team.id, "private")
    assert response.status_code == 409
    assert "component source" in response.json()["detail"]


@pytest.mark.asyncio
async def test_going_private_rejects_pending_public_join_requests(sessions):
    async with sessions() as db:
        owner = await _user(db)
        outsider = await _user(db)
        team = await _team(db, owner)
        await db.commit()

    async with _client(sessions, outsider) as (client, _):
        requested = await client.post(f"/api/v1/teams/{team.id}/join-requests", json={})
    assert requested.status_code == 201

    response = await _set_visibility(sessions, owner, team.id, "private")
    assert response.status_code == 200
    async with sessions() as db:
        row = await db.scalar(select(TeamMembershipRequest).where(TeamMembershipRequest.team_id == team.id))
    assert row.status == TeamJoinRequestStatus.rejected
    assert row.decision_reason == "Teamspace became private"


@pytest.mark.asyncio
async def test_going_private_then_public_round_trips_discovery(sessions):
    async with sessions() as db:
        owner = await _user(db)
        outsider = await _user(db)
        team = Team(id=uuid.uuid4(), name="Flip", handle=f"flip-{uuid.uuid4().hex[:8]}", created_by=owner.id)
        db.add(team)
        await db.flush()
        db.add(TeamMembership(team_id=team.id, user_id=owner.id, role=TeamRole.owner))
        await db.commit()

    assert (await _set_visibility(sessions, owner, team.id, "private")).status_code == 200
    async with _client(sessions, outsider) as (client, _):
        hidden = await client.get(f"/api/v1/teams/by-handle/{team.handle}")
    assert hidden.status_code == 404

    requested = await _set_visibility(sessions, owner, team.id, "public")
    assert requested.status_code == 200
    assert requested.json()["visibility_request_status"] == "pending"
    async with _client(sessions, owner) as (client, _):
        forbidden = await client.post(f"/api/v1/teams/{team.id}/visibility-request/approve")
    assert forbidden.status_code == 403

    async with sessions() as db:
        reviewer = await _user(db, role=UserRole.reviewer)
        await db.commit()
    async with _client(sessions, reviewer) as (client, _):
        approved = await client.post(f"/api/v1/teams/{team.id}/visibility-request/approve")
    assert approved.status_code == 200
    async with _client(sessions, outsider) as (client, _):
        visible = await client.get(f"/api/v1/teams/by-handle/{team.handle}")
    assert visible.status_code == 200
