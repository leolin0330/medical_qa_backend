# from typing import List, Tuple, Dict
# import fitz  # PyMuPDF




# def extract_text_by_page(pdf_path: str) -> List[Tuple[int, str]]:
#     """讀取 PDF 檔案並提取每頁的純文字內容。回傳 (頁碼, 該頁文字) 列表。"""
#     doc = fitz.open(pdf_path)
#     pages_text: List[Tuple[int, str]] = []
#     try:
#         for page in doc:
#             text = page.get_text() or ""
#             page_number = page.number + 1  # 轉為 1-based
#             pages_text.append((page_number, text))
#     finally:
#         doc.close()
#     return pages_text



# def split_into_paragraphs(pages_text) -> List[Dict]:
#     """
#     將每頁文字依段落切分，保留頁碼資訊。
#     ⚙️ 同時支援：
#        - list[(page_num, text)]：PDF、Word 等格式
#        - str：影片或音檔（Whisper 轉錄）
#     """
#     paragraphs: List[Dict] = []

#     # 🔹 若傳入是單一字串（影片 / 音檔），包成一頁結構
#     if isinstance(pages_text, str):
#         pages_text = [(0, pages_text)]

#     for page_num, text in pages_text:
#         # 換行正規化
#         normalized = text.replace('\r', '\n')

#         # 以空行切段
#         parts = [p.strip() for p in normalized.split('\n\n')]

#         for part in parts:
#             # 過濾太短的段落，避免雜訊
#             if part and len(part) > 10:
#                 paragraphs.append({"page": page_num, "text": part})

#     return paragraphs

# pdf_utils.py
# ---------------------------------------------
# 這個模組專門處理「PDF文字擷取」與「段落切分」。
# 在整個醫學問答後端中，它通常被 text_extractor 或 app.py 呼叫：
# 1. extract_text_by_page(pdf_path)  → 讀取 PDF 每一頁的文字
# 2. split_into_paragraphs(pages_text) → 將文字依空行或內容長度切成段落
# ---------------------------------------------

from typing import List, Tuple, Dict
import fitz  # PyMuPDF，用來開啟 PDF 及擷取文字


# =============================
# 1️⃣ 讀取 PDF 每頁文字
# =============================
def extract_text_by_page(pdf_path: str) -> List[Tuple[int, str]]:
    """
    讀取 PDF 檔案並提取每頁的純文字內容。

    回傳：
        List[Tuple[int, str]]，每個元素為：
        (頁碼, 該頁文字)

    範例：
        [
            (1, "第一頁的文字內容..."),
            (2, "第二頁的文字內容..."),
            ...
        ]

    使用說明：
        這個函式通常在上傳 PDF 後被呼叫，將原始檔案轉成每頁文字，
        再交給 split_into_paragraphs() 進一步分段。
    """
    # 開啟 PDF 檔案
    doc = fitz.open(pdf_path)
    pages_text: List[Tuple[int, str]] = []

    try:
        # 逐頁讀取
        for page in doc:
            # get_text() 會嘗試抓出所有可選取的文字內容
            text = page.get_text() or ""
            page_number = page.number + 1  # fitz 的頁碼是從 0 開始，這裡改成 1-based
            pages_text.append((page_number, text))
    finally:
        # 無論成功或失敗都確保關閉文件
        doc.close()

    return pages_text


# =============================
# 2️⃣ 將文字分段（Paragraph Splitter）
# =============================
def split_into_paragraphs(pages_text) -> List[Dict]:
    """
    將每頁文字依段落切分，保留頁碼資訊。

    ⚙️ 支援兩種輸入格式：
       - list[(page_num, text)]：常見於 PDF、Word、PPT 等結構化文件
       - str：例如影片 / 音檔（Whisper 轉錄後的純文字）

    回傳：
        List[Dict]，每個段落為：
        {
            "page": 頁碼,
            "text": 段落內容
        }

    範例：
        [
            {"page": 1, "text": "本研究探討心血管疾病的臨床試驗結果..."},
            {"page": 1, "text": "患者平均年齡為 56 歲..."},
            ...
        ]

    應用場景：
        上傳文件後 → text_extractor 取出全文 → split_into_paragraphs() 切成段落
        → 再送進 qna.embed_paragraphs() 做向量化。
    """
    paragraphs: List[Dict] = []

    # 🔹 如果傳入是單一字串（如影片或音檔的文字轉錄結果），包裝成單一「頁」
    if isinstance(pages_text, str):
        pages_text = [(0, pages_text)]

    # 🔹 逐頁處理
    for page_num, text in pages_text:
        # 統一換行符號
        normalized = text.replace('\r', '\n')

        # 用空行（\n\n）分段。每兩個換行符代表段落分界。
        parts = [p.strip() for p in normalized.split('\n\n')]

        # 🔹 過濾雜訊或太短的段落
        for part in parts:
            # 過濾掉空行與長度太短的段落（例如表格殘字）
            if part and len(part) > 10:
                paragraphs.append({"page": page_num, "text": part})

    return paragraphs
