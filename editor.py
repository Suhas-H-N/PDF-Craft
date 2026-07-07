#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║          PDF FORGE v2 — Professional PDF Editor              ║
║  40+ tools: edit · pages · colour · security · extract       ║
║  convert · annotate · redact · sign · QR · forms · more      ║
╚══════════════════════════════════════════════════════════════╝
"""

import os, sys, json, io, re, math, shutil, traceback, hashlib, datetime, tempfile
from pathlib import Path
from copy import deepcopy

# ── Core deps ──────────────────────────────────────────────────────────
from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.pagesizes import letter, A4, A3, A5, landscape, portrait
from reportlab.lib.colors import Color, HexColor, black, white
from reportlab.lib.units import mm, cm, inch
from reportlab.pdfbase import pdfmetrics
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageDraw, ImageFont
import pikepdf
import pdfplumber
import qrcode
from barcode.codex import Code128
from barcode.ean import EAN13, EAN8
from barcode.upc import UPCA
from barcode.isxn import ISBN13, ISBN10
from barcode.writer import ImageWriter as BarcodeWriter
import numpy as np

OUT_DIR = Path("output")
UP_DIR  = Path("uploads")
OUT_DIR.mkdir(exist_ok=True)
UP_DIR.mkdir(exist_ok=True)

PAGESIZES = {
    "A4": (595.28, 841.89), "A3": (841.89, 1190.55), "A5": (419.53, 595.28),
    "Letter": (612.0, 792.0), "Legal": (612.0, 1008.0),
    "B5": (498.90, 708.66), "Executive": (521.86, 756.0),
    "Tabloid": (792.0, 1224.0), "Custom": None,
}
FONTS = ["Helvetica","Helvetica-Bold","Helvetica-Oblique","Helvetica-BoldOblique",
         "Times-Roman","Times-Bold","Times-Italic","Times-BoldItalic",
         "Courier","Courier-Bold","Courier-Oblique","Courier-BoldOblique",
         "Symbol","ZapfDingbats"]

def _out(name): return OUT_DIR / name
def _load(path): return PdfReader(str(path), strict=False)

# ══════════════════════════════════════════════════════════════════════
#  INFO & ANALYSIS
# ══════════════════════════════════════════════════════════════════════

def get_info(path):
    """Full metadata + per-page dimensions."""
    try:
        r = _load(path)
        meta = r.metadata or {}
        pages_info = []
        for i, p in enumerate(r.pages):
            w, h = float(p.mediabox.width), float(p.mediabox.height)
            pages_info.append({"page": i+1, "w_pt": round(w,1), "h_pt": round(h,1),
                                "w_mm": round(w*0.352778,1), "h_mm": round(h*0.352778,1),
                                "orientation": "Landscape" if w>h else "Portrait"})
        p0 = r.pages[0]
        w0, h0 = float(p0.mediabox.width), float(p0.mediabox.height)
        return {
            "pages": len(r.pages), "width_pt": round(w0,2), "height_pt": round(h0,2),
            "width_mm": round(w0*0.352778,1), "height_mm": round(h0*0.352778,1),
            "orientation": "Landscape" if w0>h0 else "Portrait",
            "size_kb": round(os.path.getsize(path)/1024,1),
            "title": meta.get("/Title","—"), "author": meta.get("/Author","—"),
            "creator": meta.get("/Creator","—"), "producer": meta.get("/Producer","—"),
            "subject": meta.get("/Subject","—"), "keywords": meta.get("/Keywords","—"),
            "creation_date": str(meta.get("/CreationDate","—")),
            "encrypted": r.is_encrypted, "pages_detail": pages_info,
        }
    except Exception as e:
        return {"error": str(e)}

def _info(path): return get_info(path)

def extract_text(path, page_spec="all"):
    """Extract all text from PDF using pdfplumber (accurate layout-aware)."""
    try:
        result = {}
        with pdfplumber.open(path) as pdf:
            total = len(pdf.pages)
            pages = _parse_pages(page_spec, total)
            for i in pages:
                pg = pdf.pages[i]
                result[f"page_{i+1}"] = pg.extract_text() or ""
        out_path = _out(f"text_{Path(path).stem}.txt")
        with open(out_path,"w",encoding="utf-8") as f:
            for pg, txt in result.items():
                f.write(f"\n{'='*40}\n{pg}\n{'='*40}\n{txt}\n")
        return {"success": True, "output": str(out_path),
                "pages_extracted": len(result),
                "total_chars": sum(len(v) for v in result.values()),
                "preview": list(result.values())[0][:300] if result else ""}
    except Exception as e:
        return {"error": str(e), "trace": traceback.format_exc()}

def extract_tables(path, page_num=0):
    """Extract tables from a PDF page as CSV."""
    try:
        with pdfplumber.open(path) as pdf:
            pg = pdf.pages[page_num]
            tables = pg.extract_tables()
        if not tables:
            return {"success": True, "tables": 0, "message": "No tables found on this page"}
        out_path = _out(f"tables_p{page_num+1}_{Path(path).stem}.csv")
        lines = []
        for t_idx, table in enumerate(tables):
            lines.append(f"# Table {t_idx+1}")
            for row in table:
                lines.append(",".join(f'"{str(c or "")}"' for c in row))
            lines.append("")
        with open(out_path,"w",encoding="utf-8") as f:
            f.write("\n".join(lines))
        return {"success": True, "output": str(out_path),
                "tables_found": len(tables),
                "rows": sum(len(t) for t in tables)}
    except Exception as e:
        return {"error": str(e)}

def extract_images(path, output_format="PNG", min_size_kb=1):
    """Extract all embedded images from a PDF."""
    try:
        reader = _load(path)
        saved = []
        img_idx = 0
        for page_num, page in enumerate(reader.pages):
            if "/Resources" not in page: continue
            res = page["/Resources"]
            if "/XObject" not in res: continue
            xobj = res["/XObject"].get_object()
            for name, obj_ref in xobj.items():
                obj = obj_ref.get_object()
                if obj.get("/Subtype") != "/Image": continue
                try:
                    w = int(obj.get("/Width", 0))
                    h = int(obj.get("/Height", 0))
                    if w < 10 or h < 10: continue
                    data = obj.get_data()
                    cs = str(obj.get("/ColorSpace",""))
                    mode = "RGB"
                    if "Gray" in cs: mode = "L"
                    elif "CMYK" in cs: mode = "CMYK"
                    img = Image.frombytes(mode, (w, h), data)
                    fname = f"img_p{page_num+1}_{img_idx+1}.{output_format.lower()}"
                    fpath = _out(fname)
                    img.save(str(fpath), output_format)
                    size_kb = os.path.getsize(fpath)/1024
                    if size_kb >= min_size_kb:
                        saved.append({"file": str(fpath), "size_kb": round(size_kb,1),
                                      "width": w, "height": h, "page": page_num+1})
                    else:
                        os.remove(fpath)
                    img_idx += 1
                except Exception: pass
        return {"success": True, "images_extracted": len(saved), "files": saved}
    except Exception as e:
        return {"error": str(e)}

def get_fonts_list(path):
    """List all fonts used in a PDF."""
    try:
        fonts = {}
        reader = _load(path)
        for i, page in enumerate(reader.pages):
            if "/Resources" not in page: continue
            res = page["/Resources"]
            if "/Font" not in res: continue
            fd = res["/Font"].get_object()
            for fname, fobj in fd.items():
                resolved = fobj.get_object()
                base = str(resolved.get("/BaseFont","Unknown")).lstrip("/")
                ftype = str(resolved.get("/Subtype","Unknown")).lstrip("/")
                key = f"{base}"
                fonts[key] = {"base_font": base, "subtype": ftype,
                               "pages": fonts.get(key,{}).get("pages",[])+[i+1]}
        return {"success": True, "total_fonts": len(fonts), "fonts": list(fonts.values())}
    except Exception as e:
        return {"error": str(e)}

# ══════════════════════════════════════════════════════════════════════
#  TEXT & ANNOTATION TOOLS
# ══════════════════════════════════════════════════════════════════════

def _detect_text_style(page):
    sizes, fonts = [], []
    try:
        if "/Resources" in page and "/Font" in page["/Resources"]:
            fd = page["/Resources"]["/Font"]
            for k, v in fd.items():
                obj = v.get_object() if hasattr(v,"get_object") else v
                if "/BaseFont" in obj:
                    fonts.append(str(obj["/BaseFont"]).lstrip("/"))
        raw = page.get_contents()
        if raw:
            data = raw.get_data() if hasattr(raw,"get_data") else b""
            for m in re.finditer(r'/\S+\s+([\d.]+)\s+Tf', data.decode("latin-1",errors="ignore")):
                s = float(m.group(1))
                if s > 0: sizes.append(s)
    except Exception: pass
    result = {}
    if sizes:
        rounded = [round(s) for s in sizes]
        result["font_size"] = max(set(rounded), key=rounded.count)
    if fonts:
        best = fonts[0]
        for rl in FONTS:
            if rl.lower().replace("-","") in best.lower().replace("-",""):
                result["font"] = rl; break
        else:
            result["font"] = "Helvetica"
        result["detected_font_name"] = best
    return result

def add_text(path, text, page_num=0, x=100, y=100,
             font="Helvetica", font_size=12, color_hex="#000000",
             auto_detect=False, opacity=1.0):
    try:
        reader = _load(path)
        if page_num >= len(reader.pages):
            return {"error": f"Page {page_num} out of range"}
        page = reader.pages[page_num]
        pw, ph = float(page.mediabox.width), float(page.mediabox.height)
        detected = {}
        if auto_detect:
            detected = _detect_text_style(page)
            if detected.get("font_size"): font_size = detected["font_size"]
            if detected.get("font"):      font = detected["font"]
        packet = io.BytesIO()
        c = rl_canvas.Canvas(packet, pagesize=(pw, ph))
        r_v = int(color_hex[1:3],16)/255
        g_v = int(color_hex[3:5],16)/255
        b_v = int(color_hex[5:7],16)/255
        c.setFillColorRGB(r_v, g_v, b_v, opacity)
        safe_font = font if font in FONTS else "Helvetica"
        c.setFont(safe_font, font_size)
        for i, line in enumerate(text.split("\n")):
            c.drawString(x, ph - y - i*font_size*1.2, line)
        c.save(); packet.seek(0)
        page.merge_page(PdfReader(packet).pages[0])
        writer = PdfWriter()
        for p in reader.pages: writer.add_page(p)
        out_path = _out(f"text_added_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path),
                "detected": detected, "applied": {"font": safe_font, "size": font_size}}
    except Exception as e:
        return {"error": str(e)}

def add_text_box(path, text, page_num=0, x=100, y=100,
                 width=200, height=100,
                 font="Helvetica", font_size=11,
                 text_color="#000000", bg_color="#FFFDE7",
                 border_color="#F59E0B", padding=8):
    """Add a styled text box / callout with background fill."""
    try:
        reader = _load(path)
        page = reader.pages[page_num]
        pw, ph = float(page.mediabox.width), float(page.mediabox.height)
        packet = io.BytesIO()
        c = rl_canvas.Canvas(packet, pagesize=(pw, ph))
        def hex2rgb(h):
            return int(h[1:3],16)/255, int(h[3:5],16)/255, int(h[5:7],16)/255
        br,bg,bb = hex2rgb(bg_color)
        bor,bog,bob = hex2rgb(border_color)
        tr,tg,tb = hex2rgb(text_color)
        cy = ph - y - height
        c.setFillColorRGB(br,bg,bb)
        c.setStrokeColorRGB(bor,bog,bob)
        c.setLineWidth(1.5)
        c.roundRect(x, cy, width, height, 6, fill=1, stroke=1)
        c.setFillColorRGB(tr,tg,tb)
        c.setFont(font if font in FONTS else "Helvetica", font_size)
        lines = text.split("\n")
        lh = font_size * 1.3
        ty = cy + height - padding - font_size
        for line in lines:
            if ty < cy + padding: break
            c.drawString(x+padding, ty, line)
            ty -= lh
        c.save(); packet.seek(0)
        page.merge_page(PdfReader(packet).pages[0])
        writer = PdfWriter()
        for p in reader.pages: writer.add_page(p)
        out_path = _out(f"textbox_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path)}
    except Exception as e:
        return {"error": str(e)}

def highlight_text_region(path, page_num=0, x=50, y=50,
                           width=300, height=20, color_hex="#FFFF00", opacity=0.4):
    """Draw a semi-transparent highlight rectangle (simulate text highlight)."""
    try:
        reader = _load(path)
        page = reader.pages[page_num]
        pw, ph = float(page.mediabox.width), float(page.mediabox.height)
        packet = io.BytesIO()
        c = rl_canvas.Canvas(packet, pagesize=(pw, ph))
        r_v = int(color_hex[1:3],16)/255
        g_v = int(color_hex[3:5],16)/255
        b_v = int(color_hex[5:7],16)/255
        c.setFillColorRGB(r_v, g_v, b_v, opacity)
        c.setStrokeColorRGB(r_v, g_v, b_v, 0)
        c.rect(x, ph-y-height, width, height, fill=1, stroke=0)
        c.save(); packet.seek(0)
        page.merge_page(PdfReader(packet).pages[0])
        writer = PdfWriter()
        for p in reader.pages: writer.add_page(p)
        out_path = _out(f"highlight_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path)}
    except Exception as e:
        return {"error": str(e)}

def redact_region(path, page_num=0, regions=None, color_hex="#000000"):
    """Black-out (redact) rectangular regions on a page. regions=[[x,y,w,h],...]"""
    try:
        if regions is None: regions = [[100,100,200,30]]
        reader = _load(path)
        page = reader.pages[page_num]
        pw, ph = float(page.mediabox.width), float(page.mediabox.height)
        packet = io.BytesIO()
        c = rl_canvas.Canvas(packet, pagesize=(pw, ph))
        r_v = int(color_hex[1:3],16)/255
        g_v = int(color_hex[3:5],16)/255
        b_v = int(color_hex[5:7],16)/255
        c.setFillColorRGB(r_v, g_v, b_v)
        c.setStrokeColorRGB(r_v, g_v, b_v)
        for reg in regions:
            rx, ry, rw, rh = reg
            c.rect(rx, ph-ry-rh, rw, rh, fill=1, stroke=0)
        c.save(); packet.seek(0)
        page.merge_page(PdfReader(packet).pages[0])
        writer = PdfWriter()
        for p in reader.pages: writer.add_page(p)
        out_path = _out(f"redacted_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path), "regions_redacted": len(regions)}
    except Exception as e:
        return {"error": str(e)}

def add_sticky_note(path, page_num=0, x=100, y=100,
                    title="Note", content="This is a sticky note.",
                    color_hex="#FFD700"):
    """Add a visible sticky-note style annotation box."""
    try:
        reader = _load(path)
        page = reader.pages[page_num]
        pw, ph = float(page.mediabox.width), float(page.mediabox.height)
        packet = io.BytesIO()
        c = rl_canvas.Canvas(packet, pagesize=(pw, ph))
        r_v = int(color_hex[1:3],16)/255
        g_v = int(color_hex[3:5],16)/255
        b_v = int(color_hex[5:7],16)/255
        note_w, note_h = 160, 90
        cy = ph - y - note_h
        # Shadow
        c.setFillColorRGB(0,0,0,0.12)
        c.roundRect(x+3, cy-3, note_w, note_h, 4, fill=1, stroke=0)
        # Body
        c.setFillColorRGB(r_v, g_v, b_v, 0.92)
        c.setStrokeColorRGB(r_v*0.7, g_v*0.7, b_v*0.7)
        c.setLineWidth(1)
        c.roundRect(x, cy, note_w, note_h, 4, fill=1, stroke=1)
        # Title bar
        c.setFillColorRGB(r_v*0.8, g_v*0.8, b_v*0.8, 0.95)
        c.roundRect(x, cy+note_h-22, note_w, 22, 4, fill=1, stroke=0)
        c.rect(x, cy+note_h-22, note_w, 11, fill=1, stroke=0)
        # Title text
        c.setFillColorRGB(0.2,0.2,0.2)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x+6, cy+note_h-15, title[:28])
        # Body text
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0.1,0.1,0.1)
        lines = content.split("\n")
        ty = cy+note_h-32
        for line in lines:
            if ty < cy+4: break
            c.drawString(x+6, ty, line[:36])
            ty -= 11
        c.save(); packet.seek(0)
        page.merge_page(PdfReader(packet).pages[0])
        writer = PdfWriter()
        for p in reader.pages: writer.add_page(p)
        out_path = _out(f"sticky_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path)}
    except Exception as e:
        return {"error": str(e)}

def add_line_annotation(path, page_num=0, x1=50, y1=50, x2=300, y2=50,
                         color_hex="#FF0000", line_width=2, style="solid",
                         arrow=False):
    """Draw a line or arrow annotation on a page."""
    try:
        reader = _load(path)
        page = reader.pages[page_num]
        pw, ph = float(page.mediabox.width), float(page.mediabox.height)
        packet = io.BytesIO()
        c = rl_canvas.Canvas(packet, pagesize=(pw, ph))
        r_v = int(color_hex[1:3],16)/255
        g_v = int(color_hex[3:5],16)/255
        b_v = int(color_hex[5:7],16)/255
        c.setStrokeColorRGB(r_v, g_v, b_v)
        c.setLineWidth(line_width)
        if style == "dashed": c.setDash(10,5)
        elif style == "dotted": c.setDash(2,4)
        ry1, ry2 = ph-y1, ph-y2
        c.line(x1, ry1, x2, ry2)
        if arrow:
            import math
            angle = math.atan2(ry2-ry1, x2-x1)
            alen = 12
            for da in [0.4, -0.4]:
                c.line(x2, ry2,
                       x2 - alen*math.cos(angle+da),
                       ry2 - alen*math.sin(angle+da))
        c.save(); packet.seek(0)
        page.merge_page(PdfReader(packet).pages[0])
        writer = PdfWriter()
        for p in reader.pages: writer.add_page(p)
        out_path = _out(f"line_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path)}
    except Exception as e:
        return {"error": str(e)}

def add_shapes(path, page_num=0, shape="rectangle",
               x=100, y=100, width=150, height=80,
               fill_color="#E0E7FF", stroke_color="#4F46E5",
               line_width=2, opacity=0.9, radius=8):
    """Add shape: rectangle | circle | ellipse | rounded_rect | triangle."""
    try:
        reader = _load(path)
        page = reader.pages[page_num]
        pw, ph = float(page.mediabox.width), float(page.mediabox.height)
        packet = io.BytesIO()
        c = rl_canvas.Canvas(packet, pagesize=(pw, ph))
        def hex2rgb(h):
            return int(h[1:3],16)/255, int(h[3:5],16)/255, int(h[5:7],16)/255
        fr,fg,fb = hex2rgb(fill_color)
        sr,sg,sb = hex2rgb(stroke_color)
        c.setFillColorRGB(fr,fg,fb,opacity)
        c.setStrokeColorRGB(sr,sg,sb)
        c.setLineWidth(line_width)
        cy = ph - y - height
        if shape == "rectangle":
            c.rect(x, cy, width, height, fill=1, stroke=1)
        elif shape == "rounded_rect":
            c.roundRect(x, cy, width, height, radius, fill=1, stroke=1)
        elif shape in ("circle","ellipse"):
            c.ellipse(x, cy, x+width, cy+height, fill=1, stroke=1)
        elif shape == "triangle":
            p = c.beginPath()
            p.moveTo(x+width/2, cy+height)
            p.lineTo(x, cy)
            p.lineTo(x+width, cy)
            p.close()
            c.drawPath(p, fill=1, stroke=1)
        c.save(); packet.seek(0)
        page.merge_page(PdfReader(packet).pages[0])
        writer = PdfWriter()
        for p in reader.pages: writer.add_page(p)
        out_path = _out(f"shape_{shape}_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path)}
    except Exception as e:
        return {"error": str(e)}

# ══════════════════════════════════════════════════════════════════════
#  QR CODE & BARCODE TOOLS
# ══════════════════════════════════════════════════════════════════════

def add_qr_code(path, data="https://example.com", page_num=0,
                x=50, y=50, size=80,
                qr_color="#000000", bg_color="#FFFFFF",
                error_correction="M"):
    """Generate a QR code and embed it on a PDF page."""
    try:
        ec_map = {"L": qrcode.constants.ERROR_CORRECT_L,
                  "M": qrcode.constants.ERROR_CORRECT_M,
                  "Q": qrcode.constants.ERROR_CORRECT_Q,
                  "H": qrcode.constants.ERROR_CORRECT_H}
        qr = qrcode.QRCode(
            version=None, error_correction=ec_map.get(error_correction, ec_map["M"]),
            box_size=10, border=2)
        qr.add_data(data)
        qr.make(fit=True)
        fill_c = tuple(int(qr_color[i:i+2],16) for i in (1,3,5))
        back_c = tuple(int(bg_color[i:i+2],16) for i in (1,3,5))
        img = qr.make_image(fill_color=fill_c, back_color=back_c).convert("RGB")
        tmp = _out(f"_qr_tmp.png")
        img.save(str(tmp))
        reader = _load(path)
        page = reader.pages[page_num]
        pw, ph = float(page.mediabox.width), float(page.mediabox.height)
        packet = io.BytesIO()
        c = rl_canvas.Canvas(packet, pagesize=(pw, ph))
        c.drawImage(str(tmp), x, ph-y-size, width=size, height=size)
        c.save(); packet.seek(0)
        page.merge_page(PdfReader(packet).pages[0])
        writer = PdfWriter()
        for p in reader.pages: writer.add_page(p)
        out_path = _out(f"qr_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        tmp.unlink(missing_ok=True)
        return {"success": True, "output": str(out_path), "qr_data": data}
    except Exception as e:
        return {"error": str(e), "trace": traceback.format_exc()}

def add_barcode(path, data="123456789012", barcode_type="code128",
                page_num=0, x=50, y=50, width=180, height=50):
    """Embed a barcode (code128/ean13/ean8/upca/isbn13/isbn10/issn/pzn) on a page."""
    try:
        CLASS_MAP = {
            "code128": Code128, "ean13": EAN13, "ean8": EAN8,
            "upca": UPCA, "isbn13": ISBN13, "isbn10": ISBN10,
        }
        btype = barcode_type.lower()
        bc_cls = CLASS_MAP.get(btype, Code128)
        tmp_path = str(_out(f"_barcode_tmp"))
        bc = bc_cls(data, writer=BarcodeWriter())
        bc.save(tmp_path)
        img_path = tmp_path + ".png"
        reader = _load(path)
        page = reader.pages[page_num]
        pw, ph = float(page.mediabox.width), float(page.mediabox.height)
        packet = io.BytesIO()
        c = rl_canvas.Canvas(packet, pagesize=(pw, ph))
        c.drawImage(img_path, x, ph-y-height, width=width, height=height,
                    preserveAspectRatio=False)
        c.save(); packet.seek(0)
        page.merge_page(PdfReader(packet).pages[0])
        writer = PdfWriter()
        for p in reader.pages: writer.add_page(p)
        out_path = _out(f"barcode_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        Path(img_path).unlink(missing_ok=True)
        return {"success": True, "output": str(out_path), "barcode_type": btype}
    except Exception as e:
        return {"error": str(e)}

# ══════════════════════════════════════════════════════════════════════
#  PAGE LAYOUT TOOLS
# ══════════════════════════════════════════════════════════════════════

def change_orientation(path, mode="landscape", pages="all"):
    try:
        reader = _load(path)
        writer = PdfWriter()
        target = _parse_pages(pages, len(reader.pages))
        for i, page in enumerate(reader.pages):
            if i in target:
                w, h = float(page.mediabox.width), float(page.mediabox.height)
                if mode == "landscape" and h > w: page.rotate(90)
                elif mode == "portrait" and w > h: page.rotate(90)
                elif mode == "rotate90":  page.rotate(90)
                elif mode == "rotate180": page.rotate(180)
                elif mode == "rotate270": page.rotate(270)
            writer.add_page(page)
        out_path = _out(f"orientation_{mode}_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path), "mode": mode}
    except Exception as e:
        return {"error": str(e)}

def nup_pages(path, n=2, paper="A4", orientation="portrait"):
    try:
        reader = _load(path)
        total = len(reader.pages)
        grid = {2:(1,2), 4:(2,2), 6:(2,3), 9:(3,3)}.get(n,(2,2))
        cols, rows = grid
        pw, ph = PAGESIZES.get(paper, PAGESIZES["A4"])
        if orientation == "landscape": pw, ph = max(pw,ph), min(pw,ph)
        cell_w, cell_h = pw/cols, ph/rows
        writer = PdfWriter()
        src_idx = 0
        while src_idx < total:
            packet = io.BytesIO()
            c = rl_canvas.Canvas(packet, pagesize=(pw,ph))
            c.setFillColorRGB(1,1,1); c.rect(0,0,pw,ph,fill=1,stroke=0); c.save()
            packet.seek(0)
            output_page = PdfReader(packet).pages[0]
            for row in range(rows):
                for col in range(cols):
                    if src_idx >= total: break
                    src = reader.pages[src_idx]
                    sw, sh = float(src.mediabox.width), float(src.mediabox.height)
                    scale = min(cell_w/sw, cell_h/sh) * 0.92
                    tx = col*cell_w + (cell_w-sw*scale)/2
                    ty = (rows-1-row)*cell_h + (cell_h-sh*scale)/2
                    sc = deepcopy(src)
                    t = Transformation().scale(scale,scale).translate(tx/scale, ty/scale)
                    sc.add_transformation(t)
                    sc.mediabox.lower_left=(0,0); sc.mediabox.upper_right=(pw,ph)
                    output_page.merge_page(sc)
                    src_idx += 1
            writer.add_page(output_page)
        out_path = _out(f"nup{n}_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path), "nup": n,
                "output_pages": math.ceil(total/n)}
    except Exception as e:
        return {"error": str(e), "trace": traceback.format_exc()}

def resize_pages(path, paper="A4", orientation="portrait",
                 custom_w_mm=0, custom_h_mm=0):
    try:
        if paper == "Custom" and custom_w_mm and custom_h_mm:
            tw, th = custom_w_mm*mm, custom_h_mm*mm
        else:
            tw, th = PAGESIZES.get(paper, PAGESIZES["A4"])
        if orientation == "landscape": tw, th = max(tw,th), min(tw,th)
        else: tw, th = min(tw,th), max(tw,th)
        reader = _load(path)
        writer = PdfWriter()
        for page in reader.pages:
            sw, sh = float(page.mediabox.width), float(page.mediabox.height)
            scale = min(tw/sw, th/sh)
            tx, ty = (tw-sw*scale)/2, (th-sh*scale)/2
            t = Transformation().scale(scale,scale).translate(tx/scale, ty/scale)
            page.add_transformation(t)
            page.mediabox.lower_left=(0,0); page.mediabox.upper_right=(tw,th)
            writer.add_page(page)
        out_path = _out(f"resized_{paper}_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path), "size": paper}
    except Exception as e:
        return {"error": str(e)}

def add_blank_pages(path, count=1, position="end", after_page=0, paper="same"):
    """Insert blank pages at start, end, or after a specific page."""
    try:
        reader = _load(path)
        total = len(reader.pages)
        p0 = reader.pages[0]
        pw = float(p0.mediabox.width)
        ph = float(p0.mediabox.height)
        if paper != "same" and paper in PAGESIZES:
            pw, ph = PAGESIZES[paper]
        def make_blank():
            packet = io.BytesIO()
            c = rl_canvas.Canvas(packet, pagesize=(pw,ph))
            c.setFillColorRGB(1,1,1); c.rect(0,0,pw,ph,fill=1,stroke=0); c.save()
            packet.seek(0)
            return PdfReader(packet).pages[0]
        writer = PdfWriter()
        if position == "start":
            for _ in range(count): writer.add_page(make_blank())
            for p in reader.pages: writer.add_page(p)
        elif position == "end":
            for p in reader.pages: writer.add_page(p)
            for _ in range(count): writer.add_page(make_blank())
        elif position == "after":
            for i, p in enumerate(reader.pages):
                writer.add_page(p)
                if i == after_page-1:
                    for _ in range(count): writer.add_page(make_blank())
        out_path = _out(f"blank_added_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path),
                "new_total": total + count}
    except Exception as e:
        return {"error": str(e)}

def delete_pages(path, pages_to_delete):
    try:
        reader = _load(path)
        to_del = set(_parse_pages(pages_to_delete, len(reader.pages)))
        writer = PdfWriter()
        for i, p in enumerate(reader.pages):
            if i not in to_del: writer.add_page(p)
        out_path = _out(f"deleted_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path),
                "deleted": sorted(to_del), "remaining": len(reader.pages)-len(to_del)}
    except Exception as e:
        return {"error": str(e)}

def reorder_pages(path, order):
    try:
        reader = _load(path)
        writer = PdfWriter()
        for i in order: writer.add_page(reader.pages[i])
        out_path = _out(f"reordered_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path)}
    except Exception as e:
        return {"error": str(e)}

def extract_pages(path, pages):
    try:
        reader = _load(path)
        to_ext = _parse_pages(pages, len(reader.pages))
        writer = PdfWriter()
        for i in to_ext: writer.add_page(reader.pages[i])
        out_path = _out(f"extracted_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path), "extracted": len(to_ext)}
    except Exception as e:
        return {"error": str(e)}

def duplicate_pages(path, page_num=0, times=2):
    try:
        reader = _load(path)
        writer = PdfWriter()
        for i, p in enumerate(reader.pages):
            writer.add_page(p)
            if i == page_num:
                for _ in range(times-1): writer.add_page(reader.pages[i])
        out_path = _out(f"duplicated_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path)}
    except Exception as e:
        return {"error": str(e)}

def crop_pages(path, left=0, bottom=0, right=0, top=0):
    try:
        reader = _load(path)
        writer = PdfWriter()
        for page in reader.pages:
            mb = page.mediabox
            page.mediabox.lower_left  = (float(mb.left)+left,   float(mb.bottom)+bottom)
            page.mediabox.upper_right = (float(mb.right)-right, float(mb.top)-top)
            writer.add_page(page)
        out_path = _out(f"cropped_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path)}
    except Exception as e:
        return {"error": str(e)}

def scale_pages(path, scale_x=1.0, scale_y=1.0, pages="all"):
    """Scale page content (not just resize paper) — stretches/shrinks content."""
    try:
        reader = _load(path)
        writer = PdfWriter()
        target = _parse_pages(pages, len(reader.pages))
        for i, page in enumerate(reader.pages):
            if i in target:
                t = Transformation().scale(scale_x, scale_y)
                page.add_transformation(t)
                pw = float(page.mediabox.width)*scale_x
                ph = float(page.mediabox.height)*scale_y
                page.mediabox.upper_right=(pw,ph)
            writer.add_page(page)
        out_path = _out(f"scaled_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path),
                "scale_x": scale_x, "scale_y": scale_y}
    except Exception as e:
        return {"error": str(e)}

def mirror_pages(path, axis="horizontal", pages="all"):
    """Mirror / flip pages horizontally or vertically."""
    try:
        reader = _load(path)
        writer = PdfWriter()
        target = _parse_pages(pages, len(reader.pages))
        for i, page in enumerate(reader.pages):
            if i in target:
                pw = float(page.mediabox.width)
                ph = float(page.mediabox.height)
                if axis == "horizontal":
                    t = Transformation().scale(-1,1).translate(-pw, 0)
                else:
                    t = Transformation().scale(1,-1).translate(0, -ph)
                page.add_transformation(t)
            writer.add_page(page)
        out_path = _out(f"mirror_{axis}_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path)}
    except Exception as e:
        return {"error": str(e)}

# ══════════════════════════════════════════════════════════════════════
#  HEADERS, FOOTERS, WATERMARKS, STAMPS
# ══════════════════════════════════════════════════════════════════════

def add_watermark(path, text="CONFIDENTIAL", opacity=0.15,
                  font_size=60, color_hex="#FF0000",
                  angle=45, position="center"):
    try:
        reader = _load(path)
        writer = PdfWriter()
        for page in reader.pages:
            pw, ph = float(page.mediabox.width), float(page.mediabox.height)
            packet = io.BytesIO()
            c = rl_canvas.Canvas(packet, pagesize=(pw,ph))
            c.setFillColorRGB(int(color_hex[1:3],16)/255,
                               int(color_hex[3:5],16)/255,
                               int(color_hex[5:7],16)/255, opacity)
            c.setFont("Helvetica-Bold", font_size)
            cx = pw/2
            cy = {"center":ph/2,"top":ph*0.85,"bottom":ph*0.12}.get(position,ph/2)
            c.translate(cx,cy); c.rotate(angle); c.drawCentredString(0,0,text)
            c.save(); packet.seek(0)
            page.merge_page(PdfReader(packet).pages[0])
            writer.add_page(page)
        out_path = _out(f"watermark_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path)}
    except Exception as e:
        return {"error": str(e)}

def add_image_watermark(path, image_path, opacity=0.15,
                         scale=0.5, pages="all"):
    """Use an image (logo, signature PNG/JPEG) as a watermark."""
    try:
        if not Path(image_path).exists():
            return {"error": f"Image file not found: {image_path}"}
        if Path(image_path).suffix.lower() not in ('.png','.jpg','.jpeg','.bmp','.gif','.tiff','.webp'):
            return {"error": "image_path must be an image file (PNG, JPEG, etc.), not a PDF"}
        reader = _load(path)
        writer = PdfWriter()
        target = _parse_pages(pages, len(reader.pages))
        with Image.open(image_path) as wm_img:
            wm_img = wm_img.convert("RGBA")
            r, g, b, a = wm_img.split()
            a = a.point(lambda x: int(x * opacity))
            wm_img = Image.merge("RGBA",(r,g,b,a))
            tmp = _out("_wm_img_tmp.png")
            wm_img.save(str(tmp))
        for i, page in enumerate(reader.pages):
            if i not in target:
                writer.add_page(page); continue
            pw, ph = float(page.mediabox.width), float(page.mediabox.height)
            iw, ih = wm_img.size
            aspect = iw/ih
            disp_w = pw * scale
            disp_h = disp_w / aspect
            packet = io.BytesIO()
            c = rl_canvas.Canvas(packet, pagesize=(pw,ph))
            c.drawImage(str(tmp), (pw-disp_w)/2, (ph-disp_h)/2,
                        width=disp_w, height=disp_h, mask="auto")
            c.save(); packet.seek(0)
            page.merge_page(PdfReader(packet).pages[0])
            writer.add_page(page)
        tmp.unlink(missing_ok=True)
        out_path = _out(f"imgwm_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path)}
    except Exception as e:
        return {"error": str(e)}

def add_stamp(path, stamp_text="APPROVED", color_hex="#22c55e",
              page_num=0, x=0, y=0):
    try:
        reader = _load(path)
        page = reader.pages[page_num]
        pw, ph = float(page.mediabox.width), float(page.mediabox.height)
        cx = x or pw/2; cy = y or ph/2
        packet = io.BytesIO()
        c = rl_canvas.Canvas(packet, pagesize=(pw,ph))
        r_c = int(color_hex[1:3],16)/255
        g_c = int(color_hex[3:5],16)/255
        b_c = int(color_hex[5:7],16)/255
        c.setStrokeColorRGB(r_c,g_c,b_c)
        c.setFillColorRGB(r_c,g_c,b_c,0)
        c.setLineWidth(3)
        tw = len(stamp_text)*18
        c.roundRect(cx-tw/2-10,cy-18,tw+20,40,6,fill=0,stroke=1)
        c.setFillColorRGB(r_c,g_c,b_c,0.85)
        c.setFont("Helvetica-Bold",22)
        c.drawCentredString(cx,cy-6,stamp_text)
        c.save(); packet.seek(0)
        page.merge_page(PdfReader(packet).pages[0])
        writer = PdfWriter()
        for p in reader.pages: writer.add_page(p)
        out_path = _out(f"stamp_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path)}
    except Exception as e:
        return {"error": str(e)}

def add_header_footer(path, header="", footer="", page_numbers=False,
                      font="Helvetica", font_size=10, color_hex="#555555", margin=20):
    try:
        reader = _load(path)
        writer = PdfWriter()
        total = len(reader.pages)
        for idx, page in enumerate(reader.pages):
            pw, ph = float(page.mediabox.width), float(page.mediabox.height)
            packet = io.BytesIO()
            c = rl_canvas.Canvas(packet, pagesize=(pw,ph))
            c.setFillColorRGB(int(color_hex[1:3],16)/255,
                               int(color_hex[3:5],16)/255,
                               int(color_hex[5:7],16)/255)
            sf = font if font in FONTS else "Helvetica"
            c.setFont(sf, font_size)
            if header:
                h = header.replace("{page}",str(idx+1)).replace("{total}",str(total))
                c.drawCentredString(pw/2, ph-margin, h)
            if footer:
                f = footer.replace("{page}",str(idx+1)).replace("{total}",str(total))
                c.drawCentredString(pw/2, margin-font_size, f)
            if page_numbers:
                c.drawRightString(pw-margin, margin-font_size, f"Page {idx+1} of {total}")
            c.save(); packet.seek(0)
            page.merge_page(PdfReader(packet).pages[0])
            writer.add_page(page)
        out_path = _out(f"hf_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path)}
    except Exception as e:
        return {"error": str(e)}

def add_border(path, border_width=10, color_hex="#000000",
               style="solid", margin=15):
    try:
        reader = _load(path)
        writer = PdfWriter()
        for page in reader.pages:
            pw, ph = float(page.mediabox.width), float(page.mediabox.height)
            packet = io.BytesIO()
            c = rl_canvas.Canvas(packet, pagesize=(pw,ph))
            c.setStrokeColorRGB(int(color_hex[1:3],16)/255,
                                 int(color_hex[3:5],16)/255,
                                 int(color_hex[5:7],16)/255)
            c.setLineWidth(border_width)
            if style=="dashed": c.setDash(12,6)
            elif style=="dotted": c.setDash(2,4)
            c.rect(margin,margin,pw-2*margin,ph-2*margin,fill=0,stroke=1)
            c.save(); packet.seek(0)
            page.merge_page(PdfReader(packet).pages[0])
            writer.add_page(page)
        out_path = _out(f"border_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path)}
    except Exception as e:
        return {"error": str(e)}

def add_signature_line(path, page_num=0, x=100, y=700,
                        width=200, label="Signature", date_line=True):
    """Add a professional signature line with label and optional date field."""
    try:
        reader = _load(path)
        page = reader.pages[page_num]
        pw, ph = float(page.mediabox.width), float(page.mediabox.height)
        packet = io.BytesIO()
        c = rl_canvas.Canvas(packet, pagesize=(pw,ph))
        c.setStrokeColorRGB(0.2,0.2,0.2)
        c.setFillColorRGB(0.2,0.2,0.2)
        c.setLineWidth(1)
        cy = ph - y
        c.line(x, cy, x+width, cy)
        c.setFont("Helvetica", 8)
        c.drawString(x, cy-12, label)
        if date_line:
            dx = x+width+30
            c.line(dx, cy, dx+120, cy)
            c.drawString(dx, cy-12, "Date")
        c.save(); packet.seek(0)
        page.merge_page(PdfReader(packet).pages[0])
        writer = PdfWriter()
        for p in reader.pages: writer.add_page(p)
        out_path = _out(f"sigline_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path)}
    except Exception as e:
        return {"error": str(e)}

def insert_image(path, image_path, page_num=0, x=100, y=100,
                 width=150, height=0):
    try:
        with Image.open(image_path) as img:
            iw, ih = img.size
            if height==0: height = width*ih/iw
        reader = _load(path)
        page = reader.pages[page_num]
        pw, ph = float(page.mediabox.width), float(page.mediabox.height)
        packet = io.BytesIO()
        c = rl_canvas.Canvas(packet, pagesize=(pw,ph))
        c.drawImage(image_path, x, ph-y-height, width=width, height=height,
                    preserveAspectRatio=True, mask="auto")
        c.save(); packet.seek(0)
        page.merge_page(PdfReader(packet).pages[0])
        writer = PdfWriter()
        for p in reader.pages: writer.add_page(p)
        out_path = _out(f"img_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path)}
    except Exception as e:
        return {"error": str(e)}

# ══════════════════════════════════════════════════════════════════════
#  COLOUR & QUALITY
# ══════════════════════════════════════════════════════════════════════

def _pdf_to_images(path, dpi=150):
    try:
        from pdf2image import convert_from_path
        return convert_from_path(path, dpi=dpi)
    except Exception:
        pdf = pikepdf.open(path)
        images = []
        for page in pdf.pages:
            box = page.mediabox
            w_pt = float(box[2]-box[0]); h_pt = float(box[3]-box[1])
            img = Image.new("RGB",(int(w_pt*dpi/72), int(h_pt*dpi/72)),(255,255,255))
            images.append(img)
        return images

def _images_to_pdf(images, out_path, dpi=150):
    imgs = [i.convert("RGB") for i in images]
    imgs[0].save(str(out_path),save_all=True,append_images=imgs[1:],resolution=dpi)

def _auto_levels(img):
    r,g,b = img.split()
    def stretch(ch):
        lo,hi = ch.getextrema()
        return ch if hi==lo else ch.point(lambda x: int((x-lo)*255/(hi-lo)))
    return Image.merge("RGB",(stretch(r),stretch(g),stretch(b)))

def _apply_gamma(img, gamma):
    table = [int(((i/255.0)**gamma)*255) for i in range(256)]*3
    return img.point(table)

def _apply_sepia(img):
    gray = ImageOps.grayscale(img)
    sp = Image.new("RGB",img.size)
    px = gray.load(); sp_px = sp.load()
    for y in range(img.height):
        for x in range(img.width):
            v = px[x,y]
            sp_px[x,y] = (min(255,int(v*1.08)),min(255,int(v*0.86)),min(255,int(v*0.67)))
    return sp

def colour_correct(path, brightness=1.0, contrast=1.0, saturation=1.0,
                   sharpness=1.0, gamma=1.0, grayscale=False, sepia=False,
                   invert=False, auto_levels=False, dpi=150):
    try:
        images = _pdf_to_images(path, dpi)
        result = []
        for img in images:
            img = img.convert("RGB")
            if auto_levels: img = _auto_levels(img)
            if grayscale:   img = ImageOps.grayscale(img).convert("RGB")
            if sepia:       img = _apply_sepia(img)
            if invert:      img = ImageOps.invert(img)
            if gamma != 1.0: img = _apply_gamma(img, gamma)
            img = ImageEnhance.Brightness(img).enhance(brightness)
            img = ImageEnhance.Contrast(img).enhance(contrast)
            img = ImageEnhance.Color(img).enhance(saturation)
            img = ImageEnhance.Sharpness(img).enhance(sharpness)
            result.append(img)
        tag = "_".join(filter(None,[
            f"br{brightness}" if brightness!=1 else "",
            f"ct{contrast}"   if contrast!=1   else "",
            "gray" if grayscale else "", "sepia" if sepia else ""
        ])) or "corrected"
        out_path = _out(f"colour_{tag}_{Path(path).stem}.pdf")
        _images_to_pdf(result, out_path, dpi)
        return {"success": True, "output": str(out_path), "pages": len(result)}
    except Exception as e:
        return {"error": str(e), "trace": traceback.format_exc()}

def blur_pages(path, radius=2, pages="all", dpi=150):
    """Apply Gaussian blur to pages (useful for background effect)."""
    try:
        images = _pdf_to_images(path, dpi)
        target = _parse_pages(pages, len(images))
        result = []
        for i, img in enumerate(images):
            if i in target:
                img = img.filter(ImageFilter.GaussianBlur(radius=radius))
            result.append(img)
        out_path = _out(f"blur_r{radius}_{Path(path).stem}.pdf")
        _images_to_pdf(result, out_path, dpi)
        return {"success": True, "output": str(out_path)}
    except Exception as e:
        return {"error": str(e)}

def sharpen_pages(path, factor=2.0, pages="all", dpi=150):
    """Sharpen page images."""
    try:
        images = _pdf_to_images(path, dpi)
        target = _parse_pages(pages, len(images))
        result = []
        for i, img in enumerate(images):
            if i in target:
                img = ImageEnhance.Sharpness(img).enhance(factor)
            result.append(img)
        out_path = _out(f"sharp_{Path(path).stem}.pdf")
        _images_to_pdf(result, out_path, dpi)
        return {"success": True, "output": str(out_path)}
    except Exception as e:
        return {"error": str(e)}

def deskew_pages(path, pages="all", dpi=150):
    """Auto-deskew scanned pages using numpy rotation detection."""
    try:
        images = _pdf_to_images(path, dpi)
        target = _parse_pages(pages, len(images))
        result = []
        for i, img in enumerate(images):
            if i in target:
                gray = np.array(img.convert("L"))
                # Simple skew detection via projection profile
                best_angle, best_score = 0, -1
                for angle in np.arange(-10, 10, 0.5):
                    rotated = img.rotate(angle, expand=False, fillcolor=(255,255,255))
                    g = np.array(rotated.convert("L"))
                    proj = np.sum(g < 128, axis=1)
                    score = np.max(proj) - np.mean(proj)
                    if score > best_score:
                        best_score, best_angle = score, angle
                if abs(best_angle) > 0.3:
                    img = img.rotate(best_angle, expand=False, fillcolor=(255,255,255))
            result.append(img)
        out_path = _out(f"deskewed_{Path(path).stem}.pdf")
        _images_to_pdf(result, out_path, dpi)
        return {"success": True, "output": str(out_path),
                "message": "Deskew applied to selected pages"}
    except Exception as e:
        return {"error": str(e)}

def compress(path, quality="medium", image_dpi=0, image_quality=0):
    PRESETS = {"low":{"dpi":72,"q":40},"medium":{"dpi":100,"q":65},
               "high":{"dpi":150,"q":82},"maximum":{"dpi":200,"q":95}}
    p = PRESETS.get(quality, PRESETS["medium"])
    dpi = image_dpi or p["dpi"]; q = image_quality or p["q"]
    try:
        images = _pdf_to_images(path, dpi)
        out_path = _out(f"compressed_{quality}_{Path(path).stem}.pdf")
        if images:
            imgs_rgb = [img.convert("RGB") for img in images]
            jpegs = []
            for img in imgs_rgb:
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=q, optimize=True)
                buf.seek(0)
                jpegs.append(Image.open(buf).convert("RGB"))
            jpegs[0].save(str(out_path),save_all=True,append_images=jpegs[1:],resolution=dpi)
        else:
            with pikepdf.open(path) as pdf:
                pdf.save(str(out_path), compress_streams=True,
                         object_stream_mode=pikepdf.ObjectStreamMode.generate,
                         recompress_flate=True)
        orig_kb = os.path.getsize(path)/1024
        new_kb  = os.path.getsize(out_path)/1024
        return {"success": True, "output": str(out_path),
                "original_kb": round(orig_kb,1), "output_kb": round(new_kb,1),
                "reduction_pct": round((1-new_kb/orig_kb)*100,1) if orig_kb else 0}
    except Exception as e:
        return {"error": str(e)}

def increase_quality(path, target_dpi=300):
    try:
        images = _pdf_to_images(path, dpi=72)
        upscaled = []
        for img in images:
            w, h = img.size
            factor = target_dpi/72
            upscaled.append(img.resize((int(w*factor),int(h*factor)), Image.LANCZOS))
        out_path = _out(f"hq{target_dpi}dpi_{Path(path).stem}.pdf")
        _images_to_pdf(upscaled, out_path, dpi=target_dpi)
        return {"success": True, "output": str(out_path), "target_dpi": target_dpi,
                "original_kb": round(os.path.getsize(path)/1024,1),
                "output_kb": round(os.path.getsize(out_path)/1024,1)}
    except Exception as e:
        return {"error": str(e)}

def convert_to_grayscale(path, dpi=150):
    """Convert entire PDF to true grayscale (smaller file, print-friendly)."""
    try:
        images = _pdf_to_images(path, dpi)
        result = [img.convert("L").convert("RGB") for img in images]
        out_path = _out(f"grayscale_{Path(path).stem}.pdf")
        _images_to_pdf(result, out_path, dpi)
        orig_kb = os.path.getsize(path)/1024
        new_kb  = os.path.getsize(out_path)/1024
        return {"success": True, "output": str(out_path),
                "original_kb": round(orig_kb,1), "output_kb": round(new_kb,1)}
    except Exception as e:
        return {"error": str(e)}

def convert_to_blackwhite(path, threshold=128, dpi=150):
    """Convert PDF to pure black & white (1-bit) — smallest possible file."""
    try:
        images = _pdf_to_images(path, dpi)
        result = []
        for img in images:
            bw = img.convert("L").point(lambda x: 255 if x > threshold else 0, "1")
            result.append(bw.convert("RGB"))
        out_path = _out(f"bw_{Path(path).stem}.pdf")
        _images_to_pdf(result, out_path, dpi)
        return {"success": True, "output": str(out_path)}
    except Exception as e:
        return {"error": str(e)}

def add_colour_tint(path, tint_color="#FF6B6B", intensity=0.3, dpi=150):
    """Overlay a colour tint on all pages."""
    try:
        images = _pdf_to_images(path, dpi)
        r_t = int(tint_color[1:3],16)
        g_t = int(tint_color[3:5],16)
        b_t = int(tint_color[5:7],16)
        result = []
        for img in images:
            tint = Image.new("RGB", img.size, (r_t, g_t, b_t))
            blended = Image.blend(img.convert("RGB"), tint, intensity)
            result.append(blended)
        out_path = _out(f"tinted_{Path(path).stem}.pdf")
        _images_to_pdf(result, out_path, dpi)
        return {"success": True, "output": str(out_path)}
    except Exception as e:
        return {"error": str(e)}

# ══════════════════════════════════════════════════════════════════════
#  MERGE, SPLIT, COMBINE
# ══════════════════════════════════════════════════════════════════════

def merge_pdfs(paths, output_name="merged"):
    try:
        writer = PdfWriter()
        for p in paths:
            reader = _load(p)
            for page in reader.pages: writer.add_page(page)
        out_path = _out(f"{output_name}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path), "merged_files": len(paths)}
    except Exception as e:
        return {"error": str(e)}

def split_pdf(path, pages="each", ranges=None):
    try:
        reader = _load(path)
        total = len(reader.pages)
        stem = Path(path).stem
        outputs = []
        if pages == "each":
            for i in range(total):
                w = PdfWriter(); w.add_page(reader.pages[i])
                op = _out(f"split_{stem}_p{i+1}.pdf")
                with open(op,"wb") as f: w.write(f)
                outputs.append(str(op))
        elif pages == "ranges" and ranges:
            for s, e in ranges:
                w = PdfWriter()
                for i in range(s-1, min(e,total)): w.add_page(reader.pages[i])
                op = _out(f"split_{stem}_p{s}-{e}.pdf")
                with open(op,"wb") as f: w.write(f)
                outputs.append(str(op))
        return {"success": True, "outputs": outputs, "count": len(outputs)}
    except Exception as e:
        return {"error": str(e)}

def interleave_pdfs(path_a, path_b, output_name="interleaved"):
    """Interleave pages from two PDFs (A1,B1,A2,B2...) — useful for duplex scanning."""
    try:
        ra = _load(path_a); rb = _load(path_b)
        writer = PdfWriter()
        for i in range(max(len(ra.pages), len(rb.pages))):
            if i < len(ra.pages): writer.add_page(ra.pages[i])
            if i < len(rb.pages): writer.add_page(rb.pages[i])
        out_path = _out(f"{output_name}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path),
                "total_pages": len(writer.pages)}
    except Exception as e:
        return {"error": str(e)}

def reverse_pages(path):
    """Reverse page order of a PDF."""
    try:
        reader = _load(path)
        writer = PdfWriter()
        for page in reversed(reader.pages): writer.add_page(page)
        out_path = _out(f"reversed_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path),
                "pages": len(reader.pages)}
    except Exception as e:
        return {"error": str(e)}

def booklet_layout(path, paper="A4"):
    """Rearrange pages for booklet printing (saddle-stitch order)."""
    try:
        reader = _load(path)
        total = len(reader.pages)
        # Pad to multiple of 4
        padded = total + (4 - total%4)%4
        pw, ph = PAGESIZES.get(paper, PAGESIZES["A4"])
        sheet_w, sheet_h = max(pw,ph), min(pw,ph)  # landscape
        half_w = sheet_w / 2
        writer = PdfWriter()
        # Booklet order: last,first,second,last-1,...
        order = []
        sheets = padded // 4
        for s in range(sheets):
            order += [padded-1-2*s, 2*s, 2*s+1, padded-2-2*s]
        for i in range(0, len(order), 2):
            packet = io.BytesIO()
            c = rl_canvas.Canvas(packet, pagesize=(sheet_w,sheet_h))
            c.setFillColorRGB(1,1,1); c.rect(0,0,sheet_w,sheet_h,fill=1,stroke=0); c.save()
            packet.seek(0)
            output_page = PdfReader(packet).pages[0]
            for j, side in enumerate([i, i+1]):
                pg_idx = order[side] if side < len(order) else None
                if pg_idx is not None and pg_idx < total:
                    src = reader.pages[pg_idx]
                    sw, sh = float(src.mediabox.width), float(src.mediabox.height)
                    scale = min(half_w/sw, sheet_h/sh) * 0.95
                    tx = j*half_w + (half_w-sw*scale)/2
                    ty = (sheet_h-sh*scale)/2
                    sc = deepcopy(src)
                    t = Transformation().scale(scale,scale).translate(tx/scale, ty/scale)
                    sc.add_transformation(t)
                    sc.mediabox.lower_left=(0,0); sc.mediabox.upper_right=(sheet_w,sheet_h)
                    output_page.merge_page(sc)
            writer.add_page(output_page)
        out_path = _out(f"booklet_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path),
                "sheets": sheets, "note": "Print double-sided, fold and staple"}
    except Exception as e:
        return {"error": str(e), "trace": traceback.format_exc()}

# ══════════════════════════════════════════════════════════════════════
#  SECURITY
# ══════════════════════════════════════════════════════════════════════

def encrypt_pdf(path, user_password, owner_password=""):
    try:
        reader = _load(path)
        writer = PdfWriter()
        for page in reader.pages: writer.add_page(page)
        writer.encrypt(user_password, owner_password or user_password+"_owner")
        out_path = _out(f"encrypted_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path)}
    except Exception as e:
        return {"error": str(e)}

def decrypt_pdf(path, password):
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            if reader.decrypt(password) == 0:
                return {"error": "Wrong password"}
        writer = PdfWriter()
        for page in reader.pages: writer.add_page(page)
        out_path = _out(f"decrypted_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path)}
    except Exception as e:
        return {"error": str(e)}

def edit_metadata(path, title="", author="", subject="",
                  keywords="", creator="PDF Forge"):
    try:
        reader = _load(path)
        writer = PdfWriter()
        for page in reader.pages: writer.add_page(page)
        meta = {}
        if title:    meta["/Title"]    = title
        if author:   meta["/Author"]   = author
        if subject:  meta["/Subject"]  = subject
        if keywords: meta["/Keywords"] = keywords
        if creator:  meta["/Creator"]  = creator
        meta["/ModDate"] = datetime.datetime.now().strftime("D:%Y%m%d%H%M%S")
        writer.add_metadata(meta)
        out_path = _out(f"meta_{Path(path).stem}.pdf")
        with open(out_path,"wb") as f: writer.write(f)
        return {"success": True, "output": str(out_path), "metadata": meta}
    except Exception as e:
        return {"error": str(e)}

def add_pdf_checksum(path):
    """Compute SHA-256 checksum of a PDF for integrity verification."""
    try:
        sha256 = hashlib.sha256()
        with open(path,"rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        digest = sha256.hexdigest()
        # Save checksum file
        out_path = _out(f"checksum_{Path(path).stem}.txt")
        with open(out_path,"w") as f:
            f.write(f"File: {Path(path).name}\nSHA-256: {digest}\nDate: {datetime.datetime.now().isoformat()}\n")
        return {"success": True, "sha256": digest, "checksum_file": str(out_path)}
    except Exception as e:
        return {"error": str(e)}

# ══════════════════════════════════════════════════════════════════════
#  CONVERSION TOOLS
# ══════════════════════════════════════════════════════════════════════

def pdf_to_images_export(path, format="PNG", dpi=150, pages="all"):
    """Export PDF pages as image files (PNG/JPEG/TIFF/BMP/WEBP)."""
    try:
        images = _pdf_to_images(path, dpi)
        total = len(images)
        target = _parse_pages(pages, total)
        fmt = format.upper()
        if fmt not in ("PNG","JPEG","TIFF","BMP","WEBP"): fmt = "PNG"
        saved = []
        for i in target:
            img = images[i].convert("RGB")
            fname = f"page{i+1}_{Path(path).stem}.{fmt.lower()}"
            fpath = _out(fname)
            img.save(str(fpath), fmt, quality=92 if fmt=="JPEG" else None)
            saved.append(str(fpath))
        return {"success": True, "files": saved, "count": len(saved),
                "format": fmt, "dpi": dpi}
    except Exception as e:
        return {"error": str(e)}

def images_to_pdf(image_paths, output_name="from_images", dpi=150):
    """Convert a list of images to a PDF."""
    try:
        imgs = []
        for p in image_paths:
            img = Image.open(p).convert("RGB")
            imgs.append(img)
        out_path = _out(f"{output_name}.pdf")
        imgs[0].save(str(out_path), save_all=True,
                     append_images=imgs[1:], resolution=dpi)
        return {"success": True, "output": str(out_path),
                "pages": len(imgs)}
    except Exception as e:
        return {"error": str(e)}

def pdf_to_text_file(path, page_spec="all"):
    """Extract all text and save to .txt file (uses pdfplumber)."""
    return extract_text(path, page_spec)

def generate_pdf_from_text(text_content, output_name="generated",
                            paper="A4", font="Helvetica", font_size=11,
                            margin_mm=25):
    """Generate a PDF from plain text content."""
    try:
        pw, ph = PAGESIZES.get(paper, PAGESIZES["A4"])
        margin = margin_mm * mm
        out_path = _out(f"{output_name}.pdf")
        c = rl_canvas.Canvas(str(out_path), pagesize=(pw,ph))
        sf = font if font in FONTS else "Helvetica"
        c.setFont(sf, font_size)
        c.setFillColorRGB(0.1,0.1,0.1)
        lines = text_content.split("\n")
        x, y = margin, ph - margin
        lh = font_size * 1.4
        for line in lines:
            if y < margin + lh:
                c.showPage()
                c.setFont(sf, font_size)
                c.setFillColorRGB(0.1,0.1,0.1)
                y = ph - margin
            c.drawString(x, y, line)
            y -= lh
        c.save()
        return {"success": True, "output": str(out_path),
                "chars": len(text_content), "lines": len(lines)}
    except Exception as e:
        return {"error": str(e)}

# ══════════════════════════════════════════════════════════════════════
#  UTILITIES
# ══════════════════════════════════════════════════════════════════════

def _parse_pages(spec, total):
    if str(spec).strip().lower() == "all":
        return list(range(total))
    result = set()
    for part in str(spec).split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-",1)
            result.update(range(int(a)-1, min(int(b),total)))
        elif part.isdigit():
            i = int(part)-1
            if 0 <= i < total: result.add(i)
    return sorted(result)

# ── COMMAND REGISTRY ─────────────────────────────────────────────────
COMMANDS = {
    # Info & Analysis
    "info":             get_info,
    "extract_text":     extract_text,
    "extract_tables":   extract_tables,
    "extract_images":   extract_images,
    "get_fonts":        get_fonts_list,
    # Text & Annotations
    "add_text":         add_text,
    "add_text_box":     add_text_box,
    "highlight":        highlight_text_region,
    "redact":           redact_region,
    "sticky_note":      add_sticky_note,
    "add_line":         add_line_annotation,
    "add_shape":        add_shapes,
    "add_qr":           add_qr_code,
    "add_barcode":      add_barcode,
    "signature_line":   add_signature_line,
    "insert_image":     insert_image,
    # Page Layout
    "orientation":      change_orientation,
    "nup":              nup_pages,
    "resize":           resize_pages,
    "add_blank":        add_blank_pages,
    "delete_pages":     delete_pages,
    "reorder":          reorder_pages,
    "extract":          extract_pages,
    "duplicate":        duplicate_pages,
    "crop":             crop_pages,
    "scale":            scale_pages,
    "mirror":           mirror_pages,
    "reverse":          reverse_pages,
    "booklet":          booklet_layout,
    # Headers / Footers / Stamps
    "watermark":        add_watermark,
    "image_watermark":  add_image_watermark,
    "stamp":            add_stamp,
    "header_footer":    add_header_footer,
    "border":           add_border,
    # Colour & Quality
    "colour":           colour_correct,
    "blur":             blur_pages,
    "sharpen":          sharpen_pages,
    "deskew":           deskew_pages,
    "grayscale":        convert_to_grayscale,
    "blackwhite":       convert_to_blackwhite,
    "tint":             add_colour_tint,
    "compress":         compress,
    "quality":          increase_quality,
    # Combine
    "merge":            merge_pdfs,
    "split":            split_pdf,
    "interleave":       interleave_pdfs,
    # Security
    "encrypt":          encrypt_pdf,
    "decrypt":          decrypt_pdf,
    "metadata":         edit_metadata,
    "checksum":         add_pdf_checksum,
    # Convert
    "to_images":        pdf_to_images_export,
    "from_images":      images_to_pdf,
    "to_text":          pdf_to_text_file,
    "from_text":        generate_pdf_from_text,
}

def main():
    if len(sys.argv) < 2:
        print("\n📄 PDF FORGE v2 — Available Commands\n")
        cats = {
            "Info & Analysis":   ["info","extract_text","extract_tables","extract_images","get_fonts"],
            "Text & Annotate":   ["add_text","add_text_box","highlight","redact","sticky_note","add_line","add_shape","signature_line"],
            "QR & Barcode":      ["add_qr","add_barcode"],
            "Page Layout":       ["orientation","nup","resize","add_blank","delete_pages","reorder","extract","duplicate","crop","scale","mirror","reverse","booklet"],
            "Decor & Stamps":    ["watermark","image_watermark","stamp","header_footer","border","insert_image"],
            "Colour & Quality":  ["colour","blur","sharpen","deskew","grayscale","blackwhite","tint","compress","quality"],
            "Combine":           ["merge","split","interleave"],
            "Security":          ["encrypt","decrypt","metadata","checksum"],
            "Convert":           ["to_images","from_images","to_text","from_text"],
        }
        for cat, cmds in cats.items():
            print(f"  [{cat}]")
            for cmd in cmds: print(f"    python editor.py {cmd} [args...]")
            print()
        print("  Run:  python ui.py   → Web UI at http://localhost:5000\n")
        return
    cmd = sys.argv[1]
    if cmd not in COMMANDS:
        print(f"[ERROR] Unknown: '{cmd}'. Run without args to see commands.")
        return
    fn = COMMANDS[cmd]
    args, kwargs = [], {}
    for arg in sys.argv[2:]:
        if "=" in arg:
            k, v = arg.split("=",1)
            if v.lower()=="true": v=True
            elif v.lower()=="false": v=False
            else:
                try: v=int(v)
                except ValueError:
                    try: v=float(v)
                    except ValueError: pass
            kwargs[k] = v
        else:
            try: args.append(int(arg))
            except ValueError:
                try: args.append(float(arg))
                except ValueError: args.append(arg)
    try:
        result = fn(*args, **kwargs)
        print(json.dumps(result, indent=2, default=str))
    except TypeError as e:
        print(json.dumps({"error": str(e), "hint": "Check argument names/types"}))

if __name__ == "__main__":
    main()
