"""
PDF File Identifier - FastAPI Application with Interactive Swagger UI / OpenAPI Spec
-----------------------------------------------------------------------------------
Provides a RESTful API and interactive Swagger documentation (/docs) to classify
PDF documents as 'digital', 'semi_scanned', or 'fully_scanned' so external projects
and microservices can easily integrate and choose optimal extraction pathways.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field

import pymupdf as fitz
from file_identifier import FileIdentifier, FileType, IdentifierResult, PageInfo, PageType

# --------------------------------------------------------------------------- #
# Metadata & App Config
# --------------------------------------------------------------------------- #
TITLE = "PDF File Identifier API"
DESCRIPTION = """
### 🚀 PDF Classification Engine with Automated Routing

Classifies incoming PDF files into three architectural categories to optimize downstream extraction:

* **`digital`**: Every content page contains a genuine, selectable vector text layer with standard embedded fonts.
  * *Recommended Action*: Direct text & table extraction via PyMuPDF or pdfplumber. **No OCR required.**
* **`semi_scanned`**: A hybrid document with a mixture of vector pages and raster scanned pages.
  * *Recommended Action*: Extract digital pages natively; route only specific scanned page numbers to OCR.
* **`fully_scanned`**: Every content page is an image scan, hidden OCR-sandwich layer, or raster print-stream font.
  * *Recommended Action*: Route entire document to OCR / Vision LLM pipeline.

---
### 🛠️ Interactive Documentation & Specs
* **Swagger UI**: [`/docs`](/docs)
* **ReDoc UI**: [`/redoc`](/redoc)
* **OpenAPI JSON**: [`/openapi.json`](/openapi.json)
* **OpenAPI YAML**: [`/openapi.yaml`](/openapi.yaml)
* **Health Check**: [`/health`](/health)
"""

VERSION = "1.0.0"

tags_metadata = [
    {
        "name": "Classification",
        "description": "Endpoints to classify single or multiple PDF documents via upload or server path.",
    },
    {
        "name": "System & Specs",
        "description": "System health diagnostics, environment metrics, and OpenAPI schema exports.",
    },
]

app = FastAPI(
    title=TITLE,
    description=DESCRIPTION,
    version=VERSION,
    openapi_tags=tags_metadata,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# --------------------------------------------------------------------------- #
# CORS Configuration
# --------------------------------------------------------------------------- #
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path(__file__).resolve().parent / "upload_files"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# Pydantic Response & Request Schemas
# --------------------------------------------------------------------------- #
class FileTypeEnum(str, Enum):
    DIGITAL = "digital"
    SEMI_SCANNED = "semi_scanned"
    FULLY_SCANNED = "fully_scanned"


class PageTypeEnum(str, Enum):
    DIGITAL = "digital"
    SCANNED = "scanned"
    BLANK = "blank"


class PageInfoModel(BaseModel):
    page_number: int = Field(..., description="1-based page number in document", example=1)
    page_type: PageTypeEnum = Field(..., description="Classification for this page", example=PageTypeEnum.DIGITAL)
    text_chars: int = Field(..., description="Number of visible text characters", example=1240)
    image_coverage: float = Field(..., description="Fraction of page area covered by images (0.0 to 1.0)", example=0.08)
    has_invisible_text: bool = Field(..., description="Whether hidden OCR text layer is present", example=False)
    has_type3_fonts: bool = Field(False, description="Whether Type3 bitmap/raster fonts are detected", example=False)
    confidence: float = Field(..., description="Classification confidence heuristic (0.0 to 1.0)", example=0.95)
    reasons: List[str] = Field(default_factory=list, description="Diagnostic reasons explaining the decision")


class ClassifyResultModel(BaseModel):
    file_name: Optional[str] = Field(None, description="Original filename", example="contract.pdf")
    file_type: FileTypeEnum = Field(
        ...,
        description="Document-level classification: digital | semi_scanned | fully_scanned",
        example=FileTypeEnum.DIGITAL,
    )
    total_pages: int = Field(..., description="Total pages in the PDF", example=10)
    digital_pages: int = Field(..., description="Count of digital pages", example=10)
    scanned_pages: int = Field(..., description="Count of scanned pages", example=0)
    blank_pages: int = Field(..., description="Count of blank pages", example=0)
    scanned_ratio: float = Field(..., description="Ratio of scanned to content pages (0.0 to 1.0)", example=0.0)
    scanned_page_numbers: List[int] = Field(
        default_factory=list,
        description="1-based page numbers requiring OCR pipeline",
        example=[],
    )
    digital_page_numbers: List[int] = Field(
        default_factory=list,
        description="1-based page numbers suitable for native digital extraction",
        example=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    )
    pages_checked: int = Field(..., description="Total number of pages analyzed", example=10)
    max_pages_checked: Optional[int] = Field(
        None,
        description="Sampling limit if max_pages was specified",
        example=None,
    )
    saved_copy: Optional[str] = Field(
        None,
        description="Path to stored copy in upload_files directory if archived",
        example="C:/Users/.../upload_files/contract.pdf",
    )
    pages: List[PageInfoModel] = Field(
        default_factory=list,
        description="Detailed page-by-page inspection report",
    )


class ClassifyPathRequest(BaseModel):
    path: str = Field(
        ...,
        description="Path to a PDF file on the server's filesystem",
        example="upload_files/Bank statement (1).pdf",
    )
    max_pages: Optional[int] = Field(
        None,
        description="Inspect only the first N pages (prefix sampling)",
        example=10,
    )
    min_text_chars: int = Field(
        25,
        description="Minimum character count threshold to consider visible text genuine",
        example=25,
    )
    scan_image_coverage: float = Field(
        0.70,
        description="Fraction of page image coverage (0.0 to 1.0) above which a page is treated as scanned",
        example=0.70,
    )
    treat_type3_as_scanned: bool = Field(
        True,
        description="Treat Type3 raster/bitmap fonts as scanned pages",
        example=True,
    )
    save_to_upload: bool = Field(
        False,
        description="Archive an audit copy into the upload_files directory",
        example=False,
    )


class BatchFileResult(BaseModel):
    file_name: str = Field(..., description="Name of the file processed", example="sample1.pdf")
    status: str = Field("success", description="'success' or 'error'", example="success")
    result: Optional[ClassifyResultModel] = Field(None, description="Classification result on success")
    error: Optional[str] = Field(None, description="Error message if processing failed")


class BatchClassifyResponse(BaseModel):
    total_files: int = Field(..., description="Number of files processed in batch", example=2)
    successful: int = Field(..., description="Count of successfully classified files", example=2)
    failed: int = Field(..., description="Count of failed files", example=0)
    items: List[BatchFileResult] = Field(default_factory=list, description="Per-file results")


class HealthResponse(BaseModel):
    status: str = Field("healthy", example="healthy")
    engine: str = Field("PyMuPDF", example="PyMuPDF")
    engine_version: str = Field(..., example="1.28.2")
    python_version: str = Field(..., example="3.11.0")
    version: str = Field(VERSION, example=VERSION)
    endpoints: Dict[str, str] = Field(default_factory=dict, description="Key endpoint paths")


# --------------------------------------------------------------------------- #
# Helper Functions
# --------------------------------------------------------------------------- #
def _convert_result(result: IdentifierResult, original_name: Optional[str] = None) -> ClassifyResultModel:
    pages_model = [
        PageInfoModel(
            page_number=p.page_number,
            page_type=PageTypeEnum(p.page_type.value),
            text_chars=p.text_chars,
            image_coverage=p.image_coverage,
            has_invisible_text=p.has_invisible_text,
            has_type3_fonts=p.has_type3_fonts,
            confidence=p.confidence,
            reasons=p.reasons,
        )
        for p in result.pages
    ]

    return ClassifyResultModel(
        file_name=original_name,
        file_type=FileTypeEnum(result.file_type.value),
        total_pages=result.total_pages,
        digital_pages=result.digital_pages,
        scanned_pages=result.scanned_pages,
        blank_pages=result.blank_pages,
        scanned_ratio=result.scanned_ratio,
        scanned_page_numbers=result.scanned_page_numbers,
        digital_page_numbers=result.digital_page_numbers,
        pages_checked=result.pages_checked,
        max_pages_checked=result.max_pages_checked,
        saved_copy=result.saved_copy,
        pages=pages_model,
    )


def _process_pdf_file(
    file_path: Path,
    max_pages: Optional[int],
    min_text_chars: int,
    scan_image_coverage: float,
    treat_type3_as_scanned: bool,
    save_to_upload: bool,
) -> IdentifierResult:
    target_upload_dir = UPLOAD_DIR if save_to_upload else None
    identifier = FileIdentifier(
        min_text_chars=min_text_chars,
        scan_image_coverage=scan_image_coverage,
        max_pages_to_check=max_pages,
        treat_type3_as_scanned=treat_type3_as_scanned,
        upload_dir=target_upload_dir,
    )
    return identifier.identify(file_path)


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.get(
    "/",
    summary="API Root & Interactive Navigation",
    include_in_schema=False,
)
def root():
    """Redirects to Swagger documentation (/docs)."""
    return RedirectResponse(url="/docs")


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["System & Specs"],
    summary="Health Check & System Diagnostics",
    description="Check the server status, PyMuPDF engine version, and available API routes.",
)
def health():
    return HealthResponse(
        status="healthy",
        engine="PyMuPDF",
        engine_version=getattr(fitz, "__version__", "unknown"),
        python_version=sys.version.split()[0],
        version=VERSION,
        endpoints={
            "swagger_docs": "/docs",
            "redoc": "/redoc",
            "openapi_json": "/openapi.json",
            "openapi_yaml": "/openapi.yaml",
            "classify_file": "/api/v1/classify",
            "classify_path": "/api/v1/classify/path",
            "classify_batch": "/api/v1/classify/batch",
        },
    )


@app.get(
    "/openapi.yaml",
    tags=["System & Specs"],
    summary="Download OpenAPI Spec (YAML format)",
    description="Returns the OpenAPI 3.x specification formatted as YAML for Swagger Codegen, Postman, or SDK generation.",
    response_class=PlainTextResponse,
)
def get_openapi_yaml():
    spec = app.openapi()
    yaml_spec = yaml.dump(spec, sort_keys=False)
    return PlainTextResponse(content=yaml_spec, media_type="application/x-yaml")


@app.post(
    "/api/v1/classify",
    response_model=ClassifyResultModel,
    tags=["Classification"],
    summary="Classify an Uploaded PDF File",
    description="""
Upload a PDF file using `multipart/form-data`.

The API inspects the PDF text layers, fonts, image bounding boxes, and hidden OCR layers,
returning classification (`digital`, `semi_scanned`, or `fully_scanned`) and detailed per-page metrics.
""",
)
async def classify_file(
    file: UploadFile = File(..., description="PDF file to analyze (multipart/form-data)"),
    max_pages: Optional[int] = Query(
        None,
        description="Inspect only the first N pages (prefix sampling for fast routing)",
        ge=1,
    ),
    min_text_chars: int = Query(
        25,
        description="Minimum character count threshold for real text",
        ge=0,
    ),
    scan_image_coverage: float = Query(
        0.70,
        description="Fraction of image coverage (0.0 - 1.0) to classify page as scanned",
        ge=0.0,
        le=1.0,
    ),
    treat_type3_as_scanned: bool = Query(
        True,
        description="Treat Type3 raster/bitmap fonts as scanned pages",
    ),
    save_to_upload: bool = Query(
        True,
        description="Archive uploaded file into upload_files directory for audit",
    ),
):
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No file uploaded.")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only PDF files are supported. Received: '{file.filename}'",
        )

    # Save to a temporary or persistent file
    temp_file_path: Optional[Path] = None
    try:
        if save_to_upload:
            safe_filename = Path(file.filename).name
            target_path = UPLOAD_DIR / safe_filename
            with open(target_path, "wb") as f:
                shutil.copyfileobj(file.file, f)
            input_file = target_path
        else:
            fd, tmp_path_str = tempfile.mkstemp(suffix=".pdf")
            temp_file_path = Path(tmp_path_str)
            with os.fdopen(fd, "wb") as f:
                shutil.copyfileobj(file.file, f)
            input_file = temp_file_path

        result = _process_pdf_file(
            file_path=input_file,
            max_pages=max_pages,
            min_text_chars=min_text_chars,
            scan_image_coverage=scan_image_coverage,
            treat_type3_as_scanned=treat_type3_as_scanned,
            save_to_upload=save_to_upload,
        )
        return _convert_result(result, original_name=file.filename)

    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Classification failed: {str(exc)}",
        ) from exc
    finally:
        if temp_file_path is not None and temp_file_path.exists():
            try:
                temp_file_path.unlink()
            except Exception:
                pass


@app.post(
    "/api/v1/classify/path",
    response_model=ClassifyResultModel,
    tags=["Classification"],
    summary="Classify a PDF by Server File Path",
    description="""
Classify a PDF file already present on the server or a mounted volume.

Ideal for microservices, background task workers, and queues (Celery, Kafka, RabbitMQ)
where files are saved on shared storage and sending file payloads over HTTP is unnecessary.
""",
)
def classify_by_path(req: ClassifyPathRequest):
    pdf_path = Path(req.path).resolve()
    if not pdf_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found on server: '{req.path}'",
        )
    if pdf_path.suffix.lower() != ".pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only PDF files are supported: '{req.path}'",
        )

    try:
        result = _process_pdf_file(
            file_path=pdf_path,
            max_pages=req.max_pages,
            min_text_chars=req.min_text_chars,
            scan_image_coverage=req.scan_image_coverage,
            treat_type3_as_scanned=req.treat_type3_as_scanned,
            save_to_upload=req.save_to_upload,
        )
        return _convert_result(result, original_name=pdf_path.name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Classification failed: {str(exc)}",
        ) from exc


@app.post(
    "/api/v1/classify/batch",
    response_model=BatchClassifyResponse,
    tags=["Classification"],
    summary="Classify Multiple PDF Files in Batch",
    description="Upload multiple PDF files concurrently and receive classification reports for each file.",
)
async def classify_batch(
    files: List[UploadFile] = File(..., description="List of PDF files to classify"),
    max_pages: Optional[int] = Query(None, description="Prefix sampling limit per file", ge=1),
    treat_type3_as_scanned: bool = Query(True, description="Treat Type3 raster/bitmap fonts as scanned"),
    save_to_upload: bool = Query(True, description="Archive files into upload_files directory"),
):
    items: List[BatchFileResult] = []
    successful = 0
    failed = 0

    for file in files:
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            items.append(
                BatchFileResult(
                    file_name=file.filename or "unknown",
                    status="error",
                    error="Only .pdf files are supported",
                )
            )
            failed += 1
            continue

        temp_file_path: Optional[Path] = None
        try:
            if save_to_upload:
                safe_filename = Path(file.filename).name
                target_path = UPLOAD_DIR / safe_filename
                with open(target_path, "wb") as f:
                    shutil.copyfileobj(file.file, f)
                input_file = target_path
            else:
                fd, tmp_path_str = tempfile.mkstemp(suffix=".pdf")
                temp_file_path = Path(tmp_path_str)
                with os.fdopen(fd, "wb") as f:
                    shutil.copyfileobj(file.file, f)
                input_file = temp_file_path

            result = _process_pdf_file(
                file_path=input_file,
                max_pages=max_pages,
                min_text_chars=25,
                scan_image_coverage=0.70,
                treat_type3_as_scanned=treat_type3_as_scanned,
                save_to_upload=save_to_upload,
            )
            converted = _convert_result(result, original_name=file.filename)
            items.append(
                BatchFileResult(
                    file_name=file.filename,
                    status="success",
                    result=converted,
                )
            )
            successful += 1
        except Exception as exc:
            items.append(
                BatchFileResult(
                    file_name=file.filename,
                    status="error",
                    error=str(exc),
                )
            )
            failed += 1
        finally:
            if temp_file_path is not None and temp_file_path.exists():
                try:
                    temp_file_path.unlink()
                except Exception:
                    pass

    return BatchClassifyResponse(
        total_files=len(files),
        successful=successful,
        failed=failed,
        items=items,
    )


# --------------------------------------------------------------------------- #
# Route Aliases (Convenience Shortcuts)
# --------------------------------------------------------------------------- #
app.add_api_route("/classify", classify_file, methods=["POST"], include_in_schema=False)
app.add_api_route("/classify/path", classify_by_path, methods=["POST"], include_in_schema=False)
app.add_api_route("/classify/batch", classify_batch, methods=["POST"], include_in_schema=False)


# --------------------------------------------------------------------------- #
# Server Launcher
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"✨ Starting PDF File Identifier API on http://{host}:{port}")
    print(f"📖 Interactive Swagger Documentation: http://127.0.0.1:{port}/docs")
    print(f"📘 ReDoc Documentation: http://127.0.0.1:{port}/redoc")
    uvicorn.run("app:app", host=host, port=port, reload=True)
