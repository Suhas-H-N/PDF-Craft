# 📄 PDF Forge — Professional PDF Editor

> Full-featured PDF editing, correction, and conversion toolkit.  
> Web UI + Python CLI. Zero cloud. Everything runs locally.

---

## 🚀 Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

> On some systems: `pip install -r requirements.txt --break-system-packages`

### 2. Launch the Web UI
```bash
python ui.py
```
Opens automatically at **http://localhost:5000**

### 3. Or use the CLI directly
```bash
python editor.py <command> [arguments]
```

---

## 📁 Project Structure

```
pdf-editor/
├── editor.py          # All PDF processing logic (16 tools)
├── ui.py              # Flask web server
├── index.html         # Full web UI (drag & drop, live results)
├── requirements.txt   # Python dependencies
├── uploads/           # Uploaded PDFs (auto-created)
└── output/            # Processed output PDFs (auto-created)
```

---

## ✨ Features — All 16 Tools

### ✏️ Edit
| Tool | Description |
|------|-------------|
| **Add Text** | Insert text at any position. Auto-detects existing font size & style from the page content stream |
| **Watermark** | Diagonal or positioned text watermark. Adjustable opacity, angle, color, position |
| **Stamp** | Bordered rubber-stamp label (APPROVED, DRAFT, VOID…) |
| **Header & Footer** | Add headers/footers with `{page}` and `{total}` placeholders |
| **Insert Image** | Embed PNG/JPEG at any position on any page |
| **Add Border** | Solid, dashed, or dotted border frame on every page |

### 📄 Pages
| Tool | Description |
|------|-------------|
| **Orientation** | Portrait ↔ Landscape, or rotate 90°/180°/270° — all pages or specific ones |
| **N-Up Layout** | 2-up, 4-up, 6-up, or 9-up — multiple source pages per sheet |
| **Delete Pages** | Remove pages by number, range, or list |
| **Reorder Pages** | Specify any page order using 0-based indices |
| **Extract Pages** | Save a subset of pages as a new PDF |
| **Duplicate Page** | Copy a page N times |
| **Resize Pages** | Convert to A4, A3, A5, Letter, Legal, or any custom mm size |
| **Crop Margins** | Trim margins by any amount in points |

### 🎨 Colour & Quality
| Tool | Description |
|------|-------------|
| **Colour Correction** | Brightness, contrast, saturation, sharpness, gamma, grayscale, sepia, invert, auto-levels |
| **Compress** | 4 quality presets (Low/Medium/High/Maximum), custom DPI + JPEG quality |
| **Increase Quality** | Upscale to 150/300/600 DPI using Lanczos resampling |

### 🔗 Combine
| Tool | Description |
|------|-------------|
| **Merge PDFs** | Combine any number of PDFs in order |
| **Split PDF** | One file per page, or custom page ranges |

### 🔐 Security
| Tool | Description |
|------|-------------|
| **Encrypt** | Password-protect with user + owner passwords |
| **Decrypt** | Remove password protection |
| **Edit Metadata** | Set title, author, subject, keywords |

---

## 💻 CLI Reference

All tools are available from the command line:

```bash
# Get file info
python editor.py info document.pdf

# Add text (auto-detect font size from page)
python editor.py add_text document.pdf "Hello World" page_num=0 x=100 y=150 auto_detect=true

# Change orientation
python editor.py orientation document.pdf mode=landscape pages=all
python editor.py orientation document.pdf mode=portrait pages=1,3,5

# N-Up layout (4 pages per sheet)
python editor.py nup document.pdf n=4 paper=A4 orientation=portrait

# Colour corrections
python editor.py colour document.pdf brightness=1.3 contrast=1.2 saturation=0.8
python editor.py colour document.pdf grayscale=true
python editor.py colour document.pdf sepia=true dpi=200

# Compress
python editor.py compress document.pdf quality=medium
python editor.py compress document.pdf image_dpi=120 image_quality=70

# Increase quality
python editor.py quality document.pdf target_dpi=300

# Resize pages
python editor.py resize document.pdf paper=A4 orientation=portrait
python editor.py resize document.pdf paper=Custom custom_w_mm=148 custom_h_mm=210

# Watermark
python editor.py watermark document.pdf text=DRAFT opacity=0.2 angle=45
python editor.py watermark document.pdf text=CONFIDENTIAL color_hex=#0000FF

# Stamp
python editor.py stamp document.pdf stamp_text=APPROVED color_hex=#22c55e page_num=0

# Header & Footer
python editor.py header_footer document.pdf header="My Report" footer="Page {page} of {total}" page_numbers=true

# Merge PDFs
python editor.py merge paths=["a.pdf","b.pdf","c.pdf"] output_name=combined

# Split PDF (one file per page)
python editor.py split document.pdf pages=each

# Delete pages (1-indexed)
python editor.py delete_pages document.pdf pages_to_delete=1,3,5-8

# Reorder pages (0-indexed)
python editor.py reorder document.pdf order=[2,0,1]

# Extract pages
python editor.py extract document.pdf pages=1-5

# Crop margins (in points; 72pt = 1 inch)
python editor.py crop document.pdf left=36 right=36 top=36 bottom=36

# Add border
python editor.py border document.pdf border_width=8 color_hex=#000000 style=solid

# Encrypt
python editor.py encrypt document.pdf user_password=mypassword

# Decrypt
python editor.py decrypt document.pdf password=mypassword

# Edit metadata
python editor.py metadata document.pdf title="Annual Report" author="John Smith"

# Insert image
python editor.py insert_image document.pdf image_path=/path/to/logo.png page_num=0 x=50 y=50 width=120
```

---

## 🎨 Auto Text Detection

When `auto_detect=true` (default in UI), the editor analyses the PDF's content stream to find:
- The most common font size on the page
- The closest matching font family

This lets new text blend naturally with the existing document.

---

## 📦 Dependencies

| Package | Purpose |
|---------|---------|
| `pypdf` | Core PDF reading, writing, page manipulation |
| `reportlab` | PDF generation, text/image overlays |
| `Pillow` | Image processing (brightness, contrast, etc.) |
| `pikepdf` | Stream compression, low-level PDF access |
| `pdf2image` | Rasterise PDF pages to images (uses poppler) |
| `flask` | Web server for the UI |

### Optional system dependency
For `pdf2image` to work, install `poppler-utils`:
```bash
# Ubuntu/Debian
sudo apt install poppler-utils

# macOS
brew install poppler

# Windows
# Download from https://github.com/oschwartz10612/poppler-windows
```

If poppler is not installed, colour correction and quality tools fall back to blank-page rendering. All other tools work without it.

---

## 📐 Page Size Reference

| Name | Width × Height (mm) |
|------|---------------------|
| A3 | 297 × 420 |
| A4 | 210 × 297 |
| A5 | 148 × 210 |
| Letter | 216 × 279 |
| Legal | 216 × 356 |
| Custom | Any mm values |

---

## 🛡️ Privacy

Everything runs **100% locally**. No files are uploaded to any cloud service. Your PDFs never leave your machine.

---

*PDF Forge · Pure Python · No cloud · No ads*
