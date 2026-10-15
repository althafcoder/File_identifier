"""
Integration tests for PDF File Identifier FastAPI Server and Swagger Endpoints
"""

from pathlib import Path
from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

SAMPLE_PDF_1 = Path("upload_files/APL- VU Tech- May 26 (1) 1.pdf")
SAMPLE_PDF_2 = Path("upload_files/Bank statement (1).pdf")


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["engine"] == "PyMuPDF"
    assert "version" in data
    assert "swagger_docs" in data["endpoints"]
    print("[PASS] /health passed")


def test_swagger_and_openapi_endpoints():
    # Test /docs Swagger UI
    res_docs = client.get("/docs", follow_redirects=True)
    assert res_docs.status_code == 200
    assert "swagger-ui" in res_docs.text.lower() or "swagger" in res_docs.text.lower()

    # Test /openapi.json
    res_json = client.get("/openapi.json")
    assert res_json.status_code == 200
    data = res_json.json()
    assert "openapi" in data
    assert "/api/v1/classify" in data["paths"]

    # Test /openapi.yaml
    res_yaml = client.get("/openapi.yaml")
    assert res_yaml.status_code == 200
    assert "openapi:" in res_yaml.text

    print("[PASS] Swagger UI (/docs) and OpenAPI specs passed")


def test_classify_file_upload():
    assert SAMPLE_PDF_1.exists(), f"Sample file not found: {SAMPLE_PDF_1}"
    with open(SAMPLE_PDF_1, "rb") as f:
        response = client.post(
            "/api/v1/classify",
            files={"file": (SAMPLE_PDF_1.name, f, "application/pdf")},
            params={"max_pages": 5, "save_to_upload": False},
        )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["file_type"] in ["digital", "semi_scanned", "fully_scanned"]
    assert data["total_pages"] > 0
    assert len(data["pages"]) > 0
    print(f"[PASS] /api/v1/classify upload passed: {SAMPLE_PDF_1.name} -> {data['file_type']}")


def test_classify_by_path():
    assert SAMPLE_PDF_1.exists()
    response = client.post(
        "/api/v1/classify/path",
        json={"path": str(SAMPLE_PDF_1), "max_pages": 5, "save_to_upload": False},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["file_type"] in ["digital", "semi_scanned", "fully_scanned"]
    print(f"[PASS] /api/v1/classify/path passed: {SAMPLE_PDF_1.name} -> {data['file_type']}")


def test_classify_batch():
    assert SAMPLE_PDF_1.exists()
    assert SAMPLE_PDF_2.exists()
    with open(SAMPLE_PDF_1, "rb") as f1, open(SAMPLE_PDF_2, "rb") as f2:
        response = client.post(
            "/api/v1/classify/batch",
            files=[
                ("files", (SAMPLE_PDF_1.name, f1, "application/pdf")),
                ("files", (SAMPLE_PDF_2.name, f2, "application/pdf")),
            ],
            params={"max_pages": 2, "save_to_upload": False},
        )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total_files"] == 2
    assert data["successful"] == 2
    print("[PASS] /api/v1/classify/batch passed")


def test_invalid_file_extension():
    response = client.post(
        "/api/v1/classify",
        files={"file": ("test.txt", b"plain text", "text/plain")},
    )
    assert response.status_code == 400
    assert "Only PDF files are supported" in response.json()["detail"]
    print("[PASS] Invalid file rejection passed")


if __name__ == "__main__":
    test_health_endpoint()
    test_swagger_and_openapi_endpoints()
    test_classify_file_upload()
    test_classify_by_path()
    test_classify_batch()
    test_invalid_file_extension()
    print("\nALL TESTS PASSED SUCCESSFULLY!")

