#!/usr/bin/env python3
"""Exercise the public HTTP login -> upload -> review result flow."""

import json
import os
import time
import urllib.error
import urllib.request
import uuid


BASE_URL = os.getenv("SMOKE_BASE_URL", "http://localhost:5173/api/v1").rstrip("/")


def request(path: str, *, method: str = "GET", data: bytes | None = None, headers: dict[str, str] | None = None):
    req = urllib.request.Request(BASE_URL + path, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


def main() -> None:
    login = request(
        "/auth/login",
        method="POST",
        data=json.dumps({"email": "owner@acme.local", "password": "DemoPass123!"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    token = login["access_token"]
    tenant_id = next(tenant["id"] for tenant in login["tenants"] if tenant["slug"] == "acme-legal")
    boundary = "----review-smoke-" + uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="smoke-contract.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
        "Either party may terminate immediately. Liability is unlimited.\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    auth_headers = {
        "Authorization": f"Bearer {token}",
        "X-Tenant-ID": tenant_id,
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    upload = request("/documents", method="POST", data=body, headers=auth_headers)
    job_id = upload["review_job"]["id"]

    read_headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant_id}
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = request(f"/review-jobs/{job_id}", headers=read_headers)
        if job["status"] == "completed":
            assert job["result"]["issues"], "completed result should contain issues"
            print(f"Smoke test passed: job {job_id} risk={job['risk_level']}")
            return
        if job["status"] == "failed":
            raise RuntimeError(f"review failed: {job.get('error_message')}")
        time.sleep(1)
    raise TimeoutError(f"review job {job_id} did not complete within 30 seconds")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        print(exc.read().decode(errors="replace"))
        raise
