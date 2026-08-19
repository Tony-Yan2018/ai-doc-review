from datetime import datetime
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app.worker import run_once


DEMO_PASSWORD = "DemoPass123!"


def auth_headers(client, email: str, tenant_slug: str) -> dict[str, str]:
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": DEMO_PASSWORD},
    )
    assert login.status_code == 200
    tenant = next(tenant for tenant in login.json()["tenants"] if tenant["slug"] == tenant_slug)
    return {
        "Authorization": f"Bearer {login.json()['access_token']}",
        "X-Tenant-ID": tenant["id"],
    }


@pytest.fixture
def reviewer_headers(client) -> dict[str, str]:
    return auth_headers(client, "reviewer@acme.local", "acme-legal")


@pytest.fixture
def northwind_viewer_headers(client) -> dict[str, str]:
    return auth_headers(client, "viewer@northwind.local", "northwind-policy")


def upload_text(client, headers: dict[str, str], text: str, filename: str = "contract.txt"):
    return client.post(
        "/api/v1/documents",
        headers=headers,
        files={"file": (filename, text.encode(), "text/plain")},
    )


def make_docx(text: str) -> bytes:
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
    relationships = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
    document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body>
</w:document>"""

    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("word/document.xml", document)
    return output.getvalue()


def test_reviewer_can_upload_a_document(client, reviewer_headers):
    response = upload_text(client, reviewer_headers, "双方于签署之日起合作一年。")

    assert response.status_code == 201
    assert response.json()["document"]["filename"] == "contract.txt"
    assert response.json()["review_job"]["document_id"] == response.json()["document"]["id"]


def test_viewer_cannot_upload_or_retry_review_jobs(client, northwind_viewer_headers):
    upload = upload_text(client, northwind_viewer_headers, "只读用户不应创建审核。")
    retry = client.post(
        "/api/v1/review-jobs/00000000-0000-4000-8000-000000000000/retry",
        headers=northwind_viewer_headers,
    )

    assert upload.status_code == 403
    assert retry.status_code == 403


def test_user_without_tenant_membership_cannot_discover_another_tenants_job(
    client,
    reviewer_headers,
    northwind_viewer_headers,
):
    upload = upload_text(client, reviewer_headers, "Acme confidential material")
    assert upload.status_code == 201
    job_id = upload.json()["review_job"]["id"]

    response = client.get(
        f"/api/v1/review-jobs/{job_id}",
        headers={**northwind_viewer_headers, "X-Tenant-ID": reviewer_headers["X-Tenant-ID"]},
    )

    assert response.status_code == 404


def test_worker_completes_txt_review_with_structured_result(client, reviewer_headers):
    upload = upload_text(
        client,
        reviewer_headers,
        "本协议包含无限责任、自动续约和个人信息处理条款。",
    )
    assert upload.status_code == 201
    job_id = upload.json()["review_job"]["id"]

    assert run_once() is True

    response = client.get(f"/api/v1/review-jobs/{job_id}", headers=reviewer_headers)
    assert response.status_code == 200
    job = response.json()
    assert job["status"] == "completed"
    result = job["result"]
    assert result["overall_risk_level"] in {"low", "medium", "high", "critical"}
    assert isinstance(result["risk_score"], int)
    assert 0 <= result["risk_score"] <= 100
    assert result["summary"]
    assert result["review_scope"] in {"contract", "policy", "general"}
    assert result["model_name"]
    assert result["prompt_version"]
    assert datetime.fromisoformat(result["reviewed_at"])
    assert len(result["issues"]) == 3
    expected_issue_fields = {
        "category",
        "severity",
        "title",
        "description",
        "evidence",
        "location",
        "recommendation",
        "suggested_revision",
    }
    assert all(expected_issue_fields <= issue.keys() for issue in result["issues"])


def test_docx_document_is_accepted_and_processed(client, reviewer_headers):
    content = make_docx("The supplier accepts unlimited liability.")
    upload = client.post(
        "/api/v1/documents",
        headers=reviewer_headers,
        files={
            "file": (
                "agreement.docx",
                content,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert upload.status_code == 201
    job_id = upload.json()["review_job"]["id"]
    assert run_once() is True

    response = client.get(f"/api/v1/review-jobs/{job_id}", headers=reviewer_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["result"]["overall_risk_level"] in {"high", "critical"}


def test_unsupported_file_extension_is_rejected(client, reviewer_headers):
    response = client.post(
        "/api/v1/documents",
        headers=reviewer_headers,
        files={"file": ("image.png", b"not an image", "image/png")},
    )

    assert response.status_code == 415


def test_empty_text_document_becomes_failed_when_worker_processes_it(client, reviewer_headers):
    upload = upload_text(client, reviewer_headers, "   \n\t", "empty.txt")

    assert upload.status_code == 201
    job_id = upload.json()["review_job"]["id"]
    assert run_once() is True

    response = client.get(f"/api/v1/review-jobs/{job_id}", headers=reviewer_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "extractable text" in response.json()["error_message"].lower()


def test_original_document_download_is_limited_to_its_tenant(
    client,
    reviewer_headers,
    northwind_viewer_headers,
):
    original = b"Confidential source document"
    upload = client.post(
        "/api/v1/documents",
        headers=reviewer_headers,
        files={"file": ("source.txt", original, "text/plain")},
    )
    assert upload.status_code == 201
    document_id = upload.json()["document"]["id"]

    allowed = client.get(f"/api/v1/documents/{document_id}/download", headers=reviewer_headers)
    outside_tenant = client.get(
        f"/api/v1/documents/{document_id}/download",
        headers={**northwind_viewer_headers, "X-Tenant-ID": reviewer_headers["X-Tenant-ID"]},
    )

    assert allowed.status_code == 200
    assert allowed.content == original
    assert "source.txt" in allowed.headers["content-disposition"]
    assert outside_tenant.status_code == 404


def test_retry_creates_a_new_job_and_preserves_the_failed_attempt(client, reviewer_headers):
    upload = upload_text(client, reviewer_headers, "[[FAIL]] force mock error", "broken.txt")
    assert upload.status_code == 201
    original_job_id = upload.json()["review_job"]["id"]
    assert run_once() is True

    original = client.get(f"/api/v1/review-jobs/{original_job_id}", headers=reviewer_headers)
    assert original.status_code == 200
    assert original.json()["status"] == "failed"

    retry = client.post(f"/api/v1/review-jobs/{original_job_id}/retry", headers=reviewer_headers)

    assert retry.status_code == 201
    retried_job = retry.json()
    assert retried_job["id"] != original_job_id
    assert retried_job["retry_of_job_id"] == original_job_id
    assert retried_job["root_job_id"] == original_job_id

    unchanged_original = client.get(f"/api/v1/review-jobs/{original_job_id}", headers=reviewer_headers)
    assert unchanged_original.status_code == 200
    assert unchanged_original.json()["status"] == "failed"
    assert unchanged_original.json()["retry_of_job_id"] is None
    assert unchanged_original.json()["root_job_id"] == original_job_id
