import httpx

from tests.conftest import ClientFactory, SignedIn, create_workspace, signup


async def test_create_workspace_makes_creator_owner(client: httpx.AsyncClient) -> None:
    await signup(client, "owner@example.com")
    ws = await create_workspace(client, "DC Engineering")
    assert ws["role"] == "owner"

    me = (await client.get("/api/auth/me")).json()
    assert [w["name"] for w in me["workspaces"]] == ["DC Engineering"]

    members = (await client.get(f"/api/w/{ws['id']}/members")).json()
    assert [(m["email"], m["role"]) for m in members] == [("owner@example.com", "owner")]


async def test_rename_requires_admin(signed_in: SignedIn, make_client: ClientFactory) -> None:
    owner, ws = await signed_in("owner@example.com")
    resp = await owner.patch(f"/api/w/{ws['id']}", json={"name": "DC Engg"})
    assert resp.status_code == 200 and resp.json()["name"] == "DC Engg"

    member = await _join(owner, ws, make_client, "sales@example.com", "member")
    assert (await member.patch(f"/api/w/{ws['id']}", json={"name": "x"})).status_code == 403


async def _join(
    owner: httpx.AsyncClient, ws: dict, make_client: ClientFactory, email: str, role: str
) -> httpx.AsyncClient:
    invite = await owner.post(f"/api/w/{ws['id']}/invites", json={"email": email, "role": role})
    assert invite.status_code == 201, invite.text
    token = invite.json()["accept_url"].rsplit("/", 1)[-1]
    client = make_client()
    await signup(client, email)
    accepted = await client.post(f"/api/invites/{token}/accept")
    assert accepted.status_code == 200, accepted.text
    return client


async def test_invite_flow(signed_in: SignedIn, make_client: ClientFactory) -> None:
    owner, ws = await signed_in("owner@example.com", workspace="DC Engineering")
    created = await owner.post(f"/api/w/{ws['id']}/invites", json={"email": "Sales@Example.com"})
    assert created.status_code == 201
    body = created.json()
    assert body["invite"]["email"] == "sales@example.com"
    assert body["invite"]["role"] == "member"
    token = body["accept_url"].rsplit("/", 1)[-1]

    pending = (await owner.get(f"/api/w/{ws['id']}/invites")).json()
    assert [i["email"] for i in pending] == ["sales@example.com"]

    anon = make_client()
    preview = (await anon.get(f"/api/invites/{token}")).json()
    assert preview == {
        "workspace_name": "DC Engineering",
        "email": "sales@example.com",
        "role": "member",
        "invited_by": "Test User",
        "valid": True,
        "reason": None,
    }
    assert (await anon.post(f"/api/invites/{token}/accept")).status_code == 401

    sales = make_client()
    await signup(sales, "sales@example.com")
    accepted = await sales.post(f"/api/invites/{token}/accept")
    assert accepted.status_code == 200
    assert accepted.json()["role"] == "member"
    assert (await sales.get(f"/api/w/{ws['id']}")).status_code == 200

    again = await sales.post(f"/api/invites/{token}/accept")
    assert again.status_code == 410
    assert (await owner.get(f"/api/w/{ws['id']}/invites")).json() == []


async def test_invite_must_be_accepted_by_the_invited_email(
    signed_in: SignedIn, make_client: ClientFactory
) -> None:
    owner, ws = await signed_in()
    token = (
        (await owner.post(f"/api/w/{ws['id']}/invites", json={"email": "sales@example.com"}))
        .json()["accept_url"]
        .rsplit("/", 1)[-1]
    )
    other = make_client()
    await signup(other, "someone-else@example.com")
    resp = await other.post(f"/api/invites/{token}/accept")
    assert resp.status_code == 403
    assert (await other.get(f"/api/w/{ws['id']}")).status_code == 404


async def test_revoked_invite_cannot_be_used(signed_in: SignedIn, make_client: ClientFactory) -> None:
    owner, ws = await signed_in()
    created = (await owner.post(f"/api/w/{ws['id']}/invites", json={"email": "sales@example.com"})).json()
    token = created["accept_url"].rsplit("/", 1)[-1]
    assert (await owner.delete(f"/api/w/{ws['id']}/invites/{created['invite']['id']}")).status_code == 204

    sales = make_client()
    await signup(sales, "sales@example.com")
    assert (await sales.post(f"/api/invites/{token}/accept")).status_code == 410
    assert (await sales.get(f"/api/invites/{token}")).json()["valid"] is False


async def test_bad_invite_token(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/invites/not-a-token")).status_code == 404


async def test_members_cannot_invite_and_admins_cannot_make_owners(
    signed_in: SignedIn, make_client: ClientFactory
) -> None:
    owner, ws = await signed_in("owner@example.com")
    member = await _join(owner, ws, make_client, "m@example.com", "member")
    admin = await _join(owner, ws, make_client, "a@example.com", "admin")

    assert (
        await member.post(f"/api/w/{ws['id']}/invites", json={"email": "x@example.com"})
    ).status_code == 403
    assert (await member.get(f"/api/w/{ws['id']}/invites")).status_code == 403
    resp = await admin.post(f"/api/w/{ws['id']}/invites", json={"email": "x@example.com", "role": "owner"})
    assert resp.status_code == 403
    assert (
        await admin.post(f"/api/w/{ws['id']}/invites", json={"email": "x@example.com"})
    ).status_code == 201


async def test_duplicate_member_invite_is_rejected(signed_in: SignedIn) -> None:
    owner, ws = await signed_in("owner@example.com")
    resp = await owner.post(f"/api/w/{ws['id']}/invites", json={"email": "owner@example.com"})
    assert resp.status_code == 409


async def test_last_owner_cannot_leave_or_be_demoted(signed_in: SignedIn, make_client: ClientFactory) -> None:
    owner, ws = await signed_in("owner@example.com")
    me = (await owner.get("/api/auth/me")).json()["user"]
    assert (await owner.delete(f"/api/w/{ws['id']}/members/{me['id']}")).status_code == 409
    resp = await owner.patch(f"/api/w/{ws['id']}/members/{me['id']}", json={"role": "admin"})
    assert resp.status_code == 409


async def test_role_changes_and_removal(signed_in: SignedIn, make_client: ClientFactory) -> None:
    owner, ws = await signed_in("owner@example.com")
    member = await _join(owner, ws, make_client, "m@example.com", "member")
    admin = await _join(owner, ws, make_client, "a@example.com", "admin")
    members = {m["email"]: m for m in (await owner.get(f"/api/w/{ws['id']}/members")).json()}

    # Admin can't promote to owner; owner can.
    resp = await admin.patch(
        f"/api/w/{ws['id']}/members/{members['m@example.com']['user_id']}", json={"role": "owner"}
    )
    assert resp.status_code == 403
    resp = await owner.patch(
        f"/api/w/{ws['id']}/members/{members['m@example.com']['user_id']}", json={"role": "admin"}
    )
    assert resp.status_code == 200 and resp.json()["role"] == "admin"

    # Admin can't remove the owner; a member can leave by themselves.
    owner_id = members["owner@example.com"]["user_id"]
    assert (await admin.delete(f"/api/w/{ws['id']}/members/{owner_id}")).status_code == 403
    me = (await member.get("/api/auth/me")).json()["user"]
    assert (await member.delete(f"/api/w/{ws['id']}/members/{me['id']}")).status_code == 204
    assert (await member.get(f"/api/w/{ws['id']}")).status_code == 404
