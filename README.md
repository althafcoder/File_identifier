# File Identifier

An intelligent, lightweight PDF classification engine built on top of [PyMuPDF](https://pymupdf.readthedocs.io/). It inspects the internal PDF structure—fonts, text streams, raster images, and hidden OCR layers—to classify documents for optimal document processing and routing.

---

## 🎯 Purpose & Classification Types

`file_identifier` determines whether incoming PDF documents need expensive OCR processing or can be extracted directly using native text/table parsers:

| Classification | Meaning | Recommended Action |
| :--- | :--- | :--- |
| **`digital`** | Every content page has a clean, genuine vector text layer with standard embedded fonts (TrueType, Type1, Type0/CID). | Direct digital text/table extraction (**no OCR needed**). |
| **`semi_scanned`** | A mixture of digital pages and scanned/image pages. | Selective routing: digital extraction on digital pages, OCR on scanned pages. |
| **`fully_scanned`** | Every content page is an image scan, an OCR-under-image sandwich, or rendered via **Type3 raster/bitmap print-stream fonts**. | Route to full OCR / Vision-LLM engine. |

*(Note: Blank pages are automatically detected and omitted from content routing decisions).*

---

## ✨ Key Features

- **Type3 Bitmap Font Detection**: Identifies legacy print-stream / mainframe converters (e.g., Compart Docponent, AFP/IPDS) where text is rendered via 1-bit raster glyphs rather than vector outlines, routing them to OCR for clean parsing.
- **Image Bounding Box Union**: Merges overlapping images before calculating page coverage, preventing layered stamps, watermarks, and headers from distorting scan percentages.
- **Hidden OCR Layer Detection**: Detects invisible text layers (`render mode 3` / `opacity == 0`) used in scanner software (like OCRmyPDF or Adobe Acrobat Paper Capture).
- **Automatic Audit Vault (`upload_files/`)**: When testing any external PDF (from Downloads, Documents, or shared drives), a copy is automatically archived into `upload_files/` for audit trails and regression testing.
- **Batch Directory Processing**: Analyze individual PDF files or an entire folder of PDFs in one command.
- **Prefix Sampling (`--max-pages`)**: Cap analysis to the first $N$ pages for large documents to maximize throughput.

---

## 🚀 Installation & Setup

### 1. Create and Activate Virtual Environment

```powershell
# Create Python 3.11 virtual environment
py -3.11 -m venv venv

# Activate on Windows PowerShell
.\venv\Scripts\activate
```

### 2. Install Requirements

```powershell
pip install -r requirement.txt
```

---

## 💻 Usage

### Command Line Interface (CLI)

#### 1. Analyze a Single PDF File
```powershell
python file_identifier.py "upload_files\UHC- SEFL- Feb 26 1.pdf"
```

#### 2. Analyze an Entire Directory (Batch Mode)
```powershell
python file_identifier.py upload_files
```

#### 3. Analyze an External File (Auto-copies to `upload_files/` for Audit)
```powershell
python file_identifier.py "C:\Users\username\Downloads\sample_invoice.pdf"
```

#### 4. Additional CLI Options
- `--max-pages N`: Only analyze the first $N$ pages (useful for very large multi-hundred page PDFs).
  ```powershell
  python file_identifier.py --max-pages 10 "path\to\document.pdf"
  ```
- `--no-type3-as-scanned`: Disable Type3 bitmap font detection (treat Type3 fonts as digital text).
  ```powershell
  python file_identifier.py --no-type3-as-scanned "path\to\document.pdf"
  ```
- `--no-save`: Disable automatic copy to `upload_files/`.
  ```powershell
  python file_identifier.py --no-save "path\to\document.pdf"
  ```

---

### Python API Usage

```python
from file_identifier import FileIdentifier, FileType

# Initialize classifier
identifier = FileIdentifier(
    min_text_chars=25,             # Minimum characters to consider real text
    scan_image_coverage=0.70,      # Page coverage fraction threshold for scans
    treat_type3_as_scanned=True,   # Treat bitmap raster fonts as scanned
)

# Analyze PDF
result = identifier.identify("path/to/document.pdf")

# Basic checks
print("Classification:", result.file_type.value)   # "digital" | "semi_scanned" | "fully_scanned"
print("Total Pages:", result.total_pages)
print("Scanned Pages:", result.scanned_page_numbers)
print("Digital Pages:", result.digital_page_numbers)

# Full JSON report
print(result.to_dict())
```

---

## 📋 Sample Output JSON

```json
{
  "file_type": "fully_scanned",
  "total_pages": 5,
  "digital_pages": 0,
  "scanned_pages": 5,
  "blank_pages": 0,
  "scanned_ratio": 1.0,
  "pages": [
    {
      "page_number": 1,
      "page_type": "scanned",
      "text_chars": 1366,
      "image_coverage": 0.042,
      "has_invisible_text": false,
      "has_type3_fonts": true,
      "confidence": 0.9,
      "reasons": [
        "visible=1366, invisible=0, img_cov=0.042, fonts=True, type3_ratio=1.00",
        "predominantly Type3 bitmap fonts (raster print-stream) -> scanned"
      ]
    }
  ],
  "scanned_page_numbers": [1, 2, 3, 4, 5],
  "digital_page_numbers": [],
  "pages_checked": 5,
  "max_pages_checked": null,
  "saved_copy": "C:\\Users\\c1755\\File_Identifier\\upload_files\\UHC- SEFL- Feb 26 1.pdf"
}
```

---

## 📂 Project Structure

```text
File_Identifier/
├── file_identifier.py     # Main identifier engine and CLI
├── requirement.txt        # Dependencies (PyMuPDF)
├── upload_files/          # Audit vault storing tested sample files
├── .gitignore             # Git ignore patterns
└── README.md              # Project documentation
```
