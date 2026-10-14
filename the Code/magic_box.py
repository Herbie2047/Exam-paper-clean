"""
magic_box.py
------------
自動分類香港小學 mock exam PDF 到 24 個 grade/subject folder。

策略：
  1. PyMuPDF 抽全文文字（快）
  2. 抽唔到 → OCR 頭 3 頁 + 尾 3 頁（快，通常 grade 喺 header/footer）
  3. 仲未 match → OCR 全份（慢，但保險）
  4. regex 判斷 grade + subject
  5. regex 失敗 → 字型統計 fallback（中文佔比 → Chi 等）

Folder 結構（全部同一層）：
    Exam paper clear/
    ├── input/
    ├── output/
    └── magic_box.py
"""

import re
import csv
import shutil
import tempfile
from pathlib import Path

import fitz  # PyMuPDF


# ===== CONFIG =====
BASE_DIR   = Path(__file__).parent
INPUT_DIR  = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"

GRADES   = ["P1", "P2", "P3", "P4", "P5", "P6"]
SUBJECTS = ["Chi", "English", "Maths", "GS"]

DUMP_TEXT = True

# OCR 策略參數
HEAD_PAGES = 3      # 先 OCR 頭幾頁
TAIL_PAGES = 3      # 加尾幾頁
OCR_DPI    = 200    # 高啲 = 準啲但慢啲


# ===== KEYWORD PATTERNS =====
GRADE_PATTERNS = {
    "P1": [r"P\.?1", r"Primary1", r"Pri\.?1", r"Grade1",
           r"一年級", r"小一", r"1年級", r"小1"],
    "P2": [r"P\.?2", r"Primary2", r"Pri\.?2", r"Grade2",
           r"二年級", r"小二", r"2年級", r"小2"],
    "P3": [r"P\.?3", r"Primary3", r"Pri\.?3", r"Grade3",
           r"三年級", r"小三", r"3年級", r"小3"],
    "P4": [r"P\.?4", r"Primary4", r"Pri\.?4", r"Grade4",
           r"四年級", r"小四", r"4年級", r"小4"],
    "P5": [r"P\.?5", r"Primary5", r"Pri\.?5", r"Grade5",
           r"五年級", r"小五", r"5年級", r"小5"],
    "P6": [r"P\.?6", r"Primary6", r"Pri\.?6", r"Grade6",
           r"六年級", r"小六", r"6年級", r"小6"],
}

SUBJECT_PATTERNS = {
    "Chi":     [r"中文科", r"中文", r"中國語文科", r"中國語文", r"語文科", r"Chinese"],
    "English": [r"English", r"英文科", r"英文", r"英國語文科", r"英國語文"],
    "Maths":   [r"數學科", r"數學", r"Maths", r"Math", r"Mathematics"],
    "GS":      [r"常識科", r"常識", r"GeneralStudies", r"General Studies"],
}


# ===== OCR (lazy load) =====
_ocr = None

def get_ocr():
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    return _ocr


# ===== TEXT EXTRACTION =====
def extract_text_pymupdf_all(pdf_path: Path) -> str:
    """抽晒所有頁嘅文字。"""
    try:
        doc = fitz.open(str(pdf_path))
        parts = []
        for page in doc:
            parts.append(page.get_text("text"))
        doc.close()
        return "\n".join(parts)
    except Exception as e:
        print(f"   ⚠️  PyMuPDF fail: {e}")
        return ""


def ocr_pages(pdf_path: Path, page_indices: list[int]) -> str:
    """OCR 指定頁數（0-based index）。"""
    try:
        doc = fitz.open(str(pdf_path))
        total = len(doc)
        lines = []
        ocr = get_ocr()
        for i in page_indices:
            if i < 0 or i >= total:
                continue
            page = doc[i]
            pix = page.get_pixmap(dpi=OCR_DPI)
            img_bytes = pix.tobytes("png")
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(img_bytes)
                tmp_path = tmp.name
            try:
                result, _ = ocr(tmp_path)
                if result:
                    lines.extend(item[1] for item in result)
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        doc.close()
        return "\n".join(lines)
    except Exception as e:
        print(f"   ⚠️  OCR fail: {e}")
        return ""


def get_all_text(pdf_path: Path) -> str:
    """
    三層策略：
      1. PyMuPDF 全文
      2. 如果少過 15 字 → OCR 頭 3 頁 + 尾 3 頁
      3. 如果仲係少過 15 字 → OCR 全份
    """
    # Layer 1
    text = extract_text_pymupdf_all(pdf_path)
    if len(text.strip()) >= 15:
        return text

    # Layer 2 — 頭尾
    print("   🔍 冇文字層，OCR 頭尾頁...")
    try:
        doc = fitz.open(str(pdf_path))
        n = len(doc)
        doc.close()
    except Exception:
        n = 0

    idxs = list(range(min(HEAD_PAGES, n))) + list(range(max(0, n - TAIL_PAGES), n))
    idxs = sorted(set(idxs))
    text = ocr_pages(pdf_path, idxs)
    if len(text.strip()) >= 15:
        return text

    # Layer 3 — 全份
    print("   🔍 頭尾搵唔到，OCR 全份...")
    text = ocr_pages(pdf_path, list(range(n)))
    return text


# ===== DETECTION =====
def normalize(text: str) -> str:
    return re.sub(r"[\s\u3000]+", "", text)


def detect_grade(norm_text: str):
    for grade, patterns in GRADE_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, norm_text, re.IGNORECASE):
                return grade
    return None


def detect_subject(norm_text: str):
    for subject, patterns in SUBJECT_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, norm_text, re.IGNORECASE):
                return subject
    return None


def detect_subject_by_stats(raw_text: str):
    """
    字型統計 fallback：當 regex 搵唔到 subject 先用。
    規則：
      - 中文字佔比 >= 60%  → Chi
      - 數學符號 + 數字佔比 >= 30% → Maths
      - 英文字母佔比 >= 60% → English
    """
    if not raw_text.strip():
        return None

    total = len(raw_text)
    chinese = len(re.findall(r"[\u4e00-\u9fff]", raw_text))
    alpha   = len(re.findall(r"[A-Za-z]", raw_text))
    digits  = len(re.findall(r"\d", raw_text))
    mathsym = len(re.findall(r"[+\-×÷=<>≤≥()%]", raw_text))

    chinese_ratio = chinese / total
    alpha_ratio   = alpha / total
    maths_ratio   = (digits + mathsym) / total

    print(f"   📊 統計: 中文={chinese_ratio:.0%} 英文={alpha_ratio:.0%} 數學={maths_ratio:.0%}")

    if chinese_ratio >= 0.60:
        return "Chi"
    if maths_ratio >= 0.30:
        return "Maths"
    if alpha_ratio >= 0.60:
        return "English"
    return None


# ===== FILE OPS =====
def unique_dest(dest_folder: Path, base_name: str, ext: str = ".pdf") -> Path:
    candidate = dest_folder / f"{base_name}{ext}"
    i = 1
    while candidate.exists():
        candidate = dest_folder / f"{base_name}_{i:03d}{ext}"
        i += 1
    return candidate


def ensure_folders():
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for g in GRADES:
        for s in SUBJECTS:
            (OUTPUT_DIR / f"{g}_{s}").mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "unknown").mkdir(parents=True, exist_ok=True)
    if DUMP_TEXT:
        (OUTPUT_DIR / "_extracted_text").mkdir(parents=True, exist_ok=True)


# ===== MAIN =====
def main():
    print("🎩 Magic Box — 全文掃描版 (PyMuPDF + RapidOCR + 字型統計)")
    print("=" * 60)
    ensure_folders()

    pdfs = sorted(INPUT_DIR.glob("*.pdf"))
    total = len(pdfs)
    if total == 0:
        print(f"⚠️  No PDFs found in: {INPUT_DIR.resolve()}")
        return

    print(f"📥 Found {total} PDF(s) in {INPUT_DIR}\n")

    counters = {f"{g}_{s}": 0 for g in GRADES for s in SUBJECTS}
    counters["unknown"] = 0

    rows = []
    success, unknown = 0, 0

    for idx, pdf in enumerate(pdfs, 1):
        print(f"[{idx}/{total}] {pdf.name}")

        raw_text = get_all_text(pdf)
        norm_text = normalize(raw_text)

        if DUMP_TEXT:
            dump_path = OUTPUT_DIR / "_extracted_text" / f"{pdf.stem}.txt"
            dump_path.write_text(raw_text, encoding="utf-8")

        preview = norm_text[:200] if norm_text else "(冇文字!)"
        print(f"   📝 preview: {preview}")

        grade   = detect_grade(norm_text)
        subject = detect_subject(norm_text)

        # Subject fallback：字型統計
        if not subject:
            subject = detect_subject_by_stats(raw_text)
            if subject:
                print(f"   🔎 用字型統計判斷 subject = {subject}")

        if grade and subject:
            key = f"{grade}_{subject}"
            counters[key] += 1
            new_name = f"{key}_{counters[key]:04d}.pdf"
            dest_dir = OUTPUT_DIR / key
            print(f"   ✅ {grade} / {subject}  ->  {new_name}")
            success += 1
        else:
            key = "unknown"
            counters[key] += 1
            new_name = f"unknown_{counters[key]:04d}.pdf"
            dest_dir = OUTPUT_DIR / "unknown"
            print(f"   ❓ Unknown (grade={grade}, subject={subject})  ->  {new_name}")
            unknown += 1

        dest_path = unique_dest(dest_dir, Path(new_name).stem)
        shutil.move(str(pdf), str(dest_path))

        rows.append({
            "original": pdf.name,
            "new_name": dest_path.name,
            "folder":   key,
            "grade":    grade or "",
            "subject":  subject or "",
        })

    report_path = OUTPUT_DIR / "report.csv"
    with report_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["original", "new_name", "folder", "grade", "subject"])
        writer.writeheader()
        writer.writerows(rows)

    print("\n" + "=" * 60)
    print(f"🎉 完成！ 已分類: {success}    Unknown: {unknown}    總數: {total}")
    print(f"📤 Output: {OUTPUT_DIR.resolve()}")
    print(f"📄 Report: {report_path.resolve()}")


if __name__ == "__main__":
    main()