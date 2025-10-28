from typing import List, Tuple, Dict
import fitz  # PyMuPDF




def extract_text_by_page(pdf_path: str) -> List[Tuple[int, str]]:
    """讀取 PDF 檔案並提取每頁的純文字內容。回傳 (頁碼, 該頁文字) 列表。"""
    doc = fitz.open(pdf_path)
    pages_text: List[Tuple[int, str]] = []
    try:
        for page in doc:
            text = page.get_text() or ""
            page_number = page.number + 1  # 轉為 1-based
            pages_text.append((page_number, text))
    finally:
        doc.close()
    return pages_text



def split_into_paragraphs(pages_text) -> List[Dict]:
    """
    將每頁文字依段落切分，保留頁碼資訊。
    ⚙️ 同時支援：
       - list[(page_num, text)]：PDF、Word 等格式
       - str：影片或音檔（Whisper 轉錄）
    """
    paragraphs: List[Dict] = []

    # 🔹 若傳入是單一字串（影片 / 音檔），包成一頁結構
    if isinstance(pages_text, str):
        pages_text = [(0, pages_text)]

    for page_num, text in pages_text:
        # 換行正規化
        normalized = text.replace('\r', '\n')

        # 以空行切段
        parts = [p.strip() for p in normalized.split('\n\n')]

        for part in parts:
            # 過濾太短的段落，避免雜訊
            if part and len(part) > 10:
                paragraphs.append({"page": page_num, "text": part})

    return paragraphs

