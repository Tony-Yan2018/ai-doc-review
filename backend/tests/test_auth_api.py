import pytest


DEMO_PASSWORD = "DemoPass123!"
REFRESH_COOKIE = "review_refresh_token"


def login(client, email: str, password: str = DEMO_PASSWORD):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )


def bearer_headers(client, email: str) -> dict[str, str]:
    response = login(client, email)
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_seeded_user_can_log_in_and_receives_only_their_memberships(client):
    response = login(client, "owner@acme.local")

    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert isinstance(payload["access_token"], str)
    assert payload["access_token"]
    assert payload["user"]["email"] == "owner@acme.local"
    assert {
        (tenant["slug"], tenant["role"])
        for tenant in payload["tenants"]
    } == {
        ("acme-legal", "owner"),
        ("northwind-policy", "viewer"),
    }


def test_wrong_password_is_rejected_without_revealing_account_details(client):
    wrong_password = login(client, "owner@acme.local", "not-the-password")
    unknown_account = login(client, "missing@example.invalid", "not-the-password")

    assert wrong_password.status_code == 401
    assert wrong_password.json() == {"detail": "Invalid email or password"}
    assert unknown_account.status_code == 401
    assert unknown_account.json() == wrong_password.json()


def test_authenticated_user_can_read_their_profile(client):
    response = client.get(
        "/api/v1/auth/me",
        headers=bearer_headers(client, "reviewer@acme.local"),
    )

    assert response.status_code == 200
    assert response.json()["email"] == "reviewer@acme.local"
    assert "password" not in response.json()
    assert "password_hash" not in response.json()


def test_tenant_list_requires_authentication(client):
    response = client.get("/api/v1/tenants")

    assert response.status_code == 401


def test_cross_tenant_user_sees_both_memberships(client):
    response = client.get(
        "/api/v1/tenants",
        headers=bearer_headers(client, "owner@acme.local"),
    )

    assert response.status_code == 200
    assert {
        (tenant["slug"], tenant["role"])
        for tenant in response.json()
    } == {
        ("acme-legal", "owner"),
        ("northwind-policy", "viewer"),
    }


@pytest.mark.parametrize(
    ("email", "expected_membership"),
    [
        ("reviewer@acme.local", ("acme-legal", "reviewer")),
        ("viewer@northwind.local", ("northwind-policy", "viewer")),
    ],
)
def test_single_tenant_user_sees_only_their_membership(
    client,
    email: str,
    expected_membership: tuple[str, str],
):
    response = client.get(
        "/api/v1/tenants",
        headers=bearer_headers(client, email),
    )

    assert response.status_code == 200
    assert [
        (tenant["slug"], tenant["role"])
        for tenant in response.json()
    ] == [expected_membership]


def test_login_sets_a_protected_refresh_cookie_and_refresh_rotates_it(client):
    authenticated = login(client, "owner@acme.local")

    assert authenticated.status_code == 200
    first_refresh_token = authenticated.cookies.get(REFRESH_COOKIE)
    assert first_refresh_token
    set_cookie = authenticated.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie

    refreshed = client.post("/api/v1/auth/refresh")

    assert refreshed.status_code == 200
    rotated_refresh_token = refreshed.cookies.get(REFRESH_COOKIE)
    assert rotated_refresh_token
    assert rotated_refresh_token != first_refresh_token

    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE, first_refresh_token)
    rejected_replay = client.post("/api/v1/auth/refresh")
    assert rejected_replay.status_code == 401


def test_logout_revokes_the_current_refresh_cookie(client):
    authenticated = login(client, "reviewer@acme.local")
    assert authenticated.status_code == 200
    refresh_token = authenticated.cookies.get(REFRESH_COOKIE)
    assert refresh_token

    logout = client.post("/api/v1/auth/logout")

    assert logout.status_code == 204
    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE, refresh_token)
    assert client.post("/api/v1/auth/refresh").status_code == 401
