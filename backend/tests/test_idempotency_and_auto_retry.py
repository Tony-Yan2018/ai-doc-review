DEMO_PASSWORD = "DemoPass123!"


def reviewer_headers(client) -> dict[str, str]:
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "reviewer@acme.local", "password": DEMO_PASSWORD},
    )
    assert login.status_code == 200
    tenant = next(tenant for tenant in login.json()["tenants"] if tenant["slug"] == "acme-legal")
    return {
        "Authorization": f"Bearer {login.json()['access_token']}",
        "X-Tenant-ID": tenant["id"],
    }


def upload(
    client,
    headers: dict[str, str],
    content: bytes,
    filename: str = "contract.txt",
    idempotency_key: str | None = None,
):
    request_headers = dict(headers)
    if idempotency_key:
        request_headers["Idempotency-Key"] = idempotency_key
    return client.post(
        "/api/v1/documents",
        headers=request_headers,
        files={"file": (filename, content, "text/plain")},
    )


def job_history(client, headers: dict[str, str]):
    response = client.get("/api/v1/review-jobs?page_size=50", headers=headers)
    assert response.status_code == 200
    return response.json()


def test_replaying_an_identical_upload_with_an_idempotency_key_returns_the_original_job(client):
    headers = reviewer_headers(client)
    key = "11111111-1111-4111-8111-111111111111"
    content = b"The agreement lasts for one year."

    first = upload(client, headers, content, idempotency_key=key)
    replay = upload(client, headers, content, idempotency_key=key)

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json()["document"]["id"] == first.json()["document"]["id"]
    assert replay.json()["review_job"]["id"] == first.json()["review_job"]["id"]
    history = job_history(client, headers)
    assert history["total"] == 1
    assert [job["id"] for job in history["items"]] == [first.json()["review_job"]["id"]]


def test_reusing_an_idempotency_key_for_different_content_is_rejected(client):
    headers = reviewer_headers(client)
    key = "22222222-2222-4222-8222-222222222222"
    first = upload(client, headers, b"Original contract text", idempotency_key=key)
    assert first.status_code == 201

    conflict = upload(client, headers, b"Materially different contract text", idempotency_key=key)

    assert conflict.status_code == 409
    assert job_history(client, headers)["total"] == 1


def test_transient_worker_failure_creates_a_bounded_auditable_retry_chain(client):
    from app.worker import run_once

    headers = reviewer_headers(client)
    created = upload(client, headers, b"[[TRANSIENT_FAIL]] temporary provider outage", "transient.txt")
    assert created.status_code == 201
    original_id = created.json()["review_job"]["id"]
    max_attempts = created.json()["review_job"]["max_attempts"]
    assert max_attempts == 3

    assert run_once() is True
    after_first = job_history(client, headers)["items"]
    assert len(after_first) == 2
    original = next(job for job in after_first if job["id"] == original_id)
    first_retry = next(job for job in after_first if job["id"] != original_id)
    assert original["status"] == "failed"
    assert first_retry["status"] == "pending"
    assert first_retry["retry_of_job_id"] == original_id
    assert first_retry["root_job_id"] == original_id

    assert run_once() is True
    after_second = job_history(client, headers)["items"]
    assert len(after_second) == 3
    second_retry = next(
        job
        for job in after_second
        if job["id"] not in {original_id, first_retry["id"]}
    )
    assert second_retry["status"] == "pending"
    assert second_retry["retry_of_job_id"] == first_retry["id"]
    assert second_retry["root_job_id"] == original_id

    assert run_once() is True
    final_history = job_history(client, headers)
    assert final_history["total"] == max_attempts
    assert {job["status"] for job in final_history["items"]} == {"failed"}
    assert {job["root_job_id"] for job in final_history["items"]} == {original_id}
    assert {job["attempts"] for job in final_history["items"]} == set(range(1, max_attempts + 1))
    assert run_once() is False
    assert job_history(client, headers)["total"] == max_attempts


def test_permanent_extraction_failure_does_not_create_an_automatic_retry(client):
    from app.worker import run_once

    headers = reviewer_headers(client)
    created = upload(client, headers, b"   \n\t", "empty.txt")
    assert created.status_code == 201
    original_id = created.json()["review_job"]["id"]

    assert run_once() is True

    history = job_history(client, headers)
    assert history["total"] == 1
    assert history["items"][0]["id"] == original_id
    assert history["items"][0]["status"] == "failed"
    assert run_once() is False
