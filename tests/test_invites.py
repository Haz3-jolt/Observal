# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Private-team invitation links never create accounts or memberships directly."""

from __future__ import annotations

import hashlib
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.deps import get_current_user, get_db
from api.routes.teams import router as teams_router
from models.base import Base
from models.inbox import InboxItem, InboxItemEvent
from models.team import Team, TeamMembership, TeamMembershipRequest, TeamRole
from models.team_invite import TeamInvite
from models.user import User, UserRole

_TABLES = [
    User.__table__,
    Team.__table__,
    TeamMembership.__table__,
    TeamMembershipRequest.__table__,
    TeamInvite.__table__,
    InboxItem.__table__,
    InboxItemEvent.__table__,
]


@pytest_asyncio.fixture()
async def sessions():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all, tables=_TABLES)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def _user(db, role=UserRole.user):
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


async def _seed(sessions, *, private=True):
    async with sessions() as db:
        owner = await _user(db)
        outsider = await _user(db)
        admin = await _user(db, UserRole.admin)
        team = Team(
            id=uuid.uuid4(),
            name="Secret Team",
            handle=f"secret-{uuid.uuid4().hex[:8]}",
            description="Private tools",
            is_private=private,
            created_by=owner.id,
        )
        db.add(team)
        await db.flush()
        db.add(TeamMembership(team_id=team.id, user_id=owner.id, role=TeamRole.owner))
        await db.commit()
        return owner, outsider, admin, team


@asynccontextmanager
async def _client(sessions, actor):
    async with sessions() as session:
        app = FastAPI()
        app.include_router(teams_router)
        app.dependency_overrides[get_db] = lambda: session
        app.dependency_overrides[get_current_user] = lambda: actor
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client


async def _create(client, team_id, **body):
    return await client.post(f"/api/v1/teams/{team_id}/invites", json=body)


@pytest.mark.asyncio
async def test_invite_preview_requires_authentication(sessions):
    async with sessions() as session:
        app = FastAPI()
        app.include_router(teams_router)
        app.dependency_overrides[get_db] = lambda: session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/teams/invites/preview", json={"token": "secret"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_owner_creates_lists_and_revokes_team_invite(sessions):
    owner, _outsider, _admin, team = await _seed(sessions)
    async with _client(sessions, owner) as client:
        created = await _create(client, team.id, name="Hiring email", expires_in_days=7, max_uses=2)
        listed = await client.get(f"/api/v1/teams/{team.id}/invites")
        revoked = await client.post(f"/api/v1/teams/{team.id}/invites/{created.json()['id']}/revoke")

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Hiring email"
    assert body["url"].endswith(f"/team-invites/{body['token']}")
    assert listed.json()[0]["id"] == body["id"]
    assert listed.json()[0]["url"] == body["url"]
    assert revoked.json()["state"] == "revoked"

    async with sessions() as db:
        invite = await db.get(TeamInvite, uuid.UUID(body["id"]))
        assert invite.token_hash == hashlib.sha256(body["token"].encode()).hexdigest()
        assert body["token"] not in invite.token_hash
        assert invite.token_encrypted.startswith("enc:")
        assert body["token"] not in invite.token_encrypted


@pytest.mark.asyncio
async def test_global_admin_can_manage_private_team_invites(sessions):
    _owner, _outsider, admin, team = await _seed(sessions)
    async with _client(sessions, admin) as client:
        response = await _create(client, team.id)
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_team_reviewer_cannot_manage_invites(sessions):
    _owner, reviewer, _admin, team = await _seed(sessions)
    async with sessions() as db:
        db.add(TeamMembership(team_id=team.id, user_id=reviewer.id, role=TeamRole.reviewer))
        await db.commit()
    async with _client(sessions, reviewer) as client:
        response = await _create(client, team.id)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_owner_can_delete_only_unused_invite(sessions):
    owner, _outsider, _admin, team = await _seed(sessions)
    async with _client(sessions, owner) as client:
        created = await _create(client, team.id)
        deleted = await client.delete(f"/api/v1/teams/{team.id}/invites/{created.json()['id']}")
        listed = await client.get(f"/api/v1/teams/{team.id}/invites")
    assert deleted.status_code == 204
    assert listed.json() == []


@pytest.mark.asyncio
async def test_public_team_uses_share_instead_of_invites(sessions):
    owner, _outsider, _admin, team = await _seed(sessions, private=False)
    async with _client(sessions, owner) as client:
        response = await _create(client, team.id)
    assert response.status_code == 409
    assert "Share" in response.json()["detail"]


@pytest.mark.asyncio
async def test_authenticated_recipient_previews_and_requests_access(sessions):
    owner, outsider, _admin, team = await _seed(sessions)
    async with _client(sessions, owner) as client:
        created = await _create(client, team.id, max_uses=1)
    token = created.json()["token"]

    async with _client(sessions, outsider) as client:
        hidden = await client.get(f"/api/v1/teams/by-handle/{team.handle}")
        preview = await client.post("/api/v1/teams/invites/preview", json={"token": token})
        requested = await client.post(
            f"/api/v1/teams/{team.id}/join-requests",
            json={"invite_token": token},
        )
    assert hidden.status_code == 404
    assert preview.json()["team_handle"] == team.handle
    assert requested.status_code == 201

    async with _client(sessions, owner) as client:
        audit = await client.get(f"/api/v1/teams/{team.id}/invites/{created.json()['id']}/requests")
        delete_used = await client.delete(f"/api/v1/teams/{team.id}/invites/{created.json()['id']}")
    assert audit.status_code == 200
    assert audit.json()[0]["user_id"] == str(outsider.id)
    assert audit.json()[0]["status"] == "pending"
    assert delete_used.status_code == 409

    async with _client(sessions, outsider) as client:
        durable = await client.post("/api/v1/teams/invites/preview", json={"token": token})
    assert durable.json()["valid"] is True
    assert durable.json()["invite_state"] == "active"
    assert durable.json()["team_handle"] == team.handle
    assert durable.json()["request"]["status"] == "pending"

    async with sessions() as db:
        membership = (
            await db.execute(
                select(TeamMembership).where(
                    TeamMembership.team_id == team.id,
                    TeamMembership.user_id == outsider.id,
                )
            )
        ).scalar_one_or_none()
        request = (await db.execute(select(TeamMembershipRequest))).scalar_one()
        invite = (await db.execute(select(TeamInvite))).scalar_one()
        assert membership is None
        assert request.user_id == outsider.id
        assert invite.use_count == 0
        second_outsider = await _user(db)
        await db.commit()

    async with _client(sessions, second_outsider) as client:
        exhausted_preview = await client.post("/api/v1/teams/invites/preview", json={"token": token})
        exhausted_request = await client.post(
            f"/api/v1/teams/{team.id}/join-requests",
            json={"invite_token": token},
        )
    assert exhausted_preview.json()["valid"] is True
    assert exhausted_request.status_code == 201


@pytest.mark.asyncio
async def test_direct_member_add_consumes_invite_quota(sessions):
    owner, first, _admin, team = await _seed(sessions)
    async with sessions() as db:
        second = await _user(db)
        await db.commit()

    async with _client(sessions, owner) as client:
        created = await _create(client, team.id, max_uses=1)
    token = created.json()["token"]

    for requester in (first, second):
        async with _client(sessions, requester) as client:
            response = await client.post(
                f"/api/v1/teams/{team.id}/join-requests",
                json={"invite_token": token},
            )
        assert response.status_code == 201

    async with _client(sessions, owner) as client:
        added_first = await client.post(
            f"/api/v1/teams/{team.id}/members",
            json={"user_id": str(first.id), "role": "member"},
        )
        added_second = await client.post(
            f"/api/v1/teams/{team.id}/members",
            json={"user_id": str(second.id), "role": "member"},
        )
    assert added_first.status_code == 200
    assert added_second.status_code == 409
    assert "no remaining uses" in added_second.json()["detail"]

    async with sessions() as db:
        invite = await db.get(TeamInvite, uuid.UUID(created.json()["id"]))
        requests = (
            (await db.execute(select(TeamMembershipRequest).where(TeamMembershipRequest.team_id == team.id)))
            .scalars()
            .all()
        )
        second_membership = await db.scalar(
            select(TeamMembership.id).where(
                TeamMembership.team_id == team.id,
                TeamMembership.user_id == second.id,
            )
        )
    assert invite.use_count == 1
    assert {request.status.value for request in requests} == {"approved", "pending"}
    assert second_membership is None


@pytest.mark.asyncio
async def test_invite_preview_persists_cancelled_rejected_and_approved_status(sessions):
    owner, outsider, _admin, team = await _seed(sessions)
    async with _client(sessions, owner) as client:
        created = await _create(client, team.id, max_uses=5)
    token = created.json()["token"]

    async with _client(sessions, outsider) as client:
        first = await client.post(f"/api/v1/teams/{team.id}/join-requests", json={"invite_token": token})
        pending = await client.post("/api/v1/teams/invites/preview", json={"token": token})
        cancelled = await client.delete(f"/api/v1/teams/{team.id}/join-requests/{first.json()['id']}")
        cancelled_preview = await client.post("/api/v1/teams/invites/preview", json={"token": token})
        second = await client.post(f"/api/v1/teams/{team.id}/join-requests", json={"invite_token": token})
    assert pending.json()["request"]["status"] == "pending"
    assert cancelled.status_code == 204
    assert cancelled_preview.json()["request"]["status"] == "cancelled"

    async with _client(sessions, owner) as client:
        rejected = await client.post(
            f"/api/v1/teams/{team.id}/join-requests/{second.json()['id']}/reject",
            json={"reason": "Not yet"},
        )
    assert rejected.status_code == 200

    async with _client(sessions, outsider) as client:
        rejected_preview = await client.post("/api/v1/teams/invites/preview", json={"token": token})
        third = await client.post(f"/api/v1/teams/{team.id}/join-requests", json={"invite_token": token})
    assert rejected_preview.json()["request"]["status"] == "rejected"
    assert rejected_preview.json()["request"]["decision_reason"] == "Not yet"

    async with _client(sessions, owner) as client:
        approved = await client.post(f"/api/v1/teams/{team.id}/join-requests/{third.json()['id']}/approve")
    assert approved.status_code == 200

    async with _client(sessions, outsider) as client:
        approved_preview = await client.post("/api/v1/teams/invites/preview", json={"token": token})
    assert approved_preview.json()["request"]["status"] == "approved"
    assert approved_preview.json()["team_handle"] == team.handle


@pytest.mark.asyncio
async def test_approving_public_visibility_revokes_existing_invites(sessions):
    owner, outsider, admin, team = await _seed(sessions)
    async with _client(sessions, owner) as client:
        created = await _create(client, team.id)
        requested = await client.patch(f"/api/v1/teams/{team.id}/visibility", json={"visibility": "public"})
    assert requested.status_code == 200
    assert requested.json()["visibility_request_status"] == "pending"

    async with _client(sessions, admin) as client:
        approved = await client.post(f"/api/v1/teams/{team.id}/visibility-request/approve")
    assert approved.status_code == 200

    async with sessions() as db:
        invite = await db.get(TeamInvite, uuid.UUID(created.json()["id"]))
        assert invite.revoked_at is not None
        stored_team = await db.get(Team, team.id)
        stored_team.is_private = True
        await db.commit()

    async with _client(sessions, outsider) as client:
        preview = await client.post("/api/v1/teams/invites/preview", json={"token": created.json()["token"]})
    assert preview.json()["valid"] is False


@pytest.mark.asyncio
async def test_invalid_exhausted_or_revoked_invite_cannot_reveal_private_team(sessions):
    owner, outsider, _admin, team = await _seed(sessions)
    async with sessions() as db:
        invites = [
            TeamInvite(
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                team_id=team.id,
                invited_by=owner.id,
                max_uses=1 if token == "exhausted" else None,
                use_count=1 if token == "exhausted" else 0,
                expires_at=datetime.now(UTC) - timedelta(days=1)
                if token == "expired"
                else datetime.now(UTC) + timedelta(days=1),
                revoked_at=datetime.now(UTC) if token == "revoked" else None,
            )
            for token in ("exhausted", "expired", "revoked")
        ]
        db.add_all(invites)
        await db.commit()

    async with _client(sessions, outsider) as client:
        for token in ("missing", "exhausted", "expired", "revoked"):
            preview = await client.post("/api/v1/teams/invites/preview", json={"token": token})
            request = await client.post(
                f"/api/v1/teams/{team.id}/join-requests",
                json={"invite_token": token},
            )
            assert preview.json()["valid"] is False
            assert preview.json()["team_id"] is None
            assert preview.json()["request"] is None
            assert preview.json()["invite_state"] == (None if token == "missing" else token)
            assert request.status_code == 404
