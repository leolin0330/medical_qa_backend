# text_extractor.py
from __future__ import annotations
import os
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional

# ---- OpenAI Whisper（用於音檔/影片語音轉文字） ----
from openai import OpenAI

# ---- 文字檔處理相依（保持輕量） ----
# PDF
from pdfminer.high_level import extract_text as pdf_extract_text  # type: ignore
# DOCX
import docx  # type: ignore
# PPTX
from pptx import Presentation  # type: ignore

from pydub import AudioSegment  # 用來偵測音量
from services import video_utils  

# HTML（可選）：若沒裝 bs4 也能退化成簡單正則
try:
    from bs4 import BeautifulSoup  # type: ignore
    _HAS_BS4 = True
except Exception:
    _HAS_BS4 = False


# =========================
# 基本設定
# =========================
# Whisper 模型：官方雲端轉錄
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "whisper-1")
_openai_client: Optional[OpenAI] = None

def _client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI()  # 從環境變數讀 OPENAI_API_KEY
    return _openai_client


# 支援的副檔名
TEXT_EXTS  = {".txt", ".html", ".htm", ".pdf", ".docx", ".pptx"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}

def _is_audio(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_EXTS

def _is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTS

def _is_text(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTS

def _is_image(path: Path) -> bool:      
    return path.suffix.lower() in IMAGE_EXTS


# =========================
# 公用：文字清理
# =========================
def _normalize_text(s: str) -> str:
    """基礎清理：統一換行、去 BOM、收斂多餘空白行。"""
    if not s:
        return ""
    # 移除 BOM
    s = s.replace("\ufeff", "")
    # 統一換行
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    # 收斂連續空白行
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


# =========================
# 純文字 / HTML
# =========================
def _read_txt(path: Path) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _normalize_text(f.read())
    except UnicodeDecodeError:
        # 回退：嘗試 gbk / big5 等（避免爆掉）
        for enc in ("big5", "gbk", "latin1"):
            try:
                with open(path, "r", encoding=enc, errors="ignore") as f:
                    return _normalize_text(f.read())
            except Exception:
                pass
        # 最後一招：binary 解碼
        with open(path, "rb") as f:
            return _normalize_text(f.read().decode("utf-8", errors="ignore"))

def _html_to_text(html: str) -> str:
    if _HAS_BS4:
        soup = BeautifulSoup(html, "html.parser")
        # 移除 script/style
        for t in soup(["script", "style"]):
            t.decompose()
        text = soup.get_text("\n")
        return _normalize_text(text)
    # 無 bs4：簡單移除標籤
    text = re.sub(r"(?is)<script.*?>.*?</script>", "", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", "", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return _normalize_text(text)

def _read_html(path: Path) -> str:
    raw = _read_txt(path)
    return _html_to_text(raw)


# =========================
# PDF / DOCX / PPTX
# =========================
def _read_pdf(path: Path) -> str:
    return _normalize_text(pdf_extract_text(str(path)) or "")

def _read_docx(path: Path) -> str:
    try:
        d = docx.Document(str(path))
    except Exception:
        # 偶見解析問題，改用二進位讀取忽略錯誤
        d = docx.Document(path)
    parts = [p.text for p in d.paragraphs if p.text]
    return _normalize_text("\n".join(parts))

def _read_pptx(path: Path) -> str:
    prs = Presentation(str(path))
    parts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text:
                parts.append(shape.text)
    return _normalize_text("\n".join(parts))

def _detect_audio_volume(video_path: str) -> float:
    """
    用 ffmpeg 抽取音訊後，用 pydub 偵測平均音量 (dBFS)。
    回傳值越小代表越安靜，例如 -60 幾乎無聲。
    """
    _require_ffmpeg()
    from tempfile import TemporaryDirectory
    import subprocess
    from pathlib import Path

    with TemporaryDirectory() as td:
        tmp_audio = Path(td) / "probe.wav"
        cmd = [
            "ffmpeg", "-y", "-i", str(video_path),
            "-vn", "-ac", "1", "-ar", "16000",
            "-f", "wav", str(tmp_audio)
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            audio = AudioSegment.from_wav(tmp_audio)
            return audio.dBFS
        except Exception:
            return -90.0  # 若無法解析視為極低音量



# =========================
# 音檔（Whisper）
# =========================
def extract_from_audio(path: str | Path) -> str:
    """
    使用 OpenAI Whisper 轉錄音檔（.mp3 / .wav / .m4a）。
    回傳：轉錄後的全文字串
    """
    p = Path(path)
    with open(p, "rb") as f:
        # Whisper 雲端 API：以分鐘計價
        transcript = _client().audio.transcriptions.create(
            model=WHISPER_MODEL,
            file=f,
            response_format="text",  # 直接拿純文字
            # language="zh",        # 如多為中文可打開；預設自動偵測
            # temperature=0,
        )
    return _normalize_text(transcript)


# =========================
# 影片（ffmpeg 抽音 → Whisper）
# =========================
def _require_ffmpeg():
    from shutil import which
    if which("ffmpeg") is None:
        raise RuntimeError(
            "缺少 ffmpeg，請先安裝並加入 PATH（Windows 請安裝 ffmpeg.exe；macOS: brew install ffmpeg）。"
        )

def extract_from_video(path: str | Path) -> str:
    """
    影片：
    若有語音 → Whisper + GPT-4o Frame Caption 雙通道融合
    若無語音 → GPT-4o Frame Caption 單通道摘要
    """
    _require_ffmpeg()
    src = str(path)

    # --- 新增：音量偵測 ---
    loudness = _detect_audio_volume(src)
    print(f"[DEBUG] 平均音量 dBFS = {loudness:.2f}")

    # 判斷是否有語音（閾值可調）
    has_audio = loudness > -40

    if not has_audio:
        # 🔸 無聲影片：只跑 GPT-4o 畫面摘要
        print("[INFO] 偵測到無聲影片 → 進行 Frame-based Caption 摘要")
        captions_text, vision_cost = video_utils.generate_captions(src)
        return captions_text, vision_cost

    # 🔸 有聲影片：同時跑 Whisper + Frame Caption + 融合
    print("[INFO] 偵測到有聲影片 → 啟動雙通道融合模式")

    # 1. 轉錄語音
    audio_text = extract_from_video_audioonly(src)

    # 2. 生成畫面描述
    captions_text, vision_cost = video_utils.generate_captions(src)

    # 3. 融合兩者（Whisper + Caption）
    merged_text = video_utils.fuse_text(audio_text, captions_text)

    return merged_text, vision_cost


def extract_from_video_audioonly(src: str) -> str:
    """
    專供有聲影片使用的音訊轉文字（保持原 extract_from_video 流程）
    """
    with TemporaryDirectory() as td:
        audio_path = str(Path(td) / "audio.wav")
        cmd = [
            "ffmpeg", "-y", "-i", src,
            "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", audio_path
        ]
        ret = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if ret.returncode != 0:
            raise RuntimeError("ffmpeg 抽取音訊失敗。")
        return extract_from_audio(audio_path)


def extract_from_image(path: str | Path):
    """
    單張圖片：呼叫 GPT-4o 視覺模型做醫學描述。
    回傳：描述文字 + 預估 vision_cost
    """
    p = Path(path)
    # 直接呼叫 video_utils 內的單張圖片 caption 函式（下面第 2 部分會加）
    caption, vision_cost = video_utils.caption_single_image(p)
    return _normalize_text(caption), vision_cost



# =========================
# 統一入口（供外部呼叫）
# =========================
def extract_any(path: str | Path) -> str:
    """
    依副檔名自動選擇解析方式，回傳 (文字內容, vision_cost)。
    - 文字檔：TXT / HTML / PDF / DOCX / PPTX
    - 音檔：MP3 / WAV / M4A（Whisper）
    - 影片：MP4 / MOV / M4V（ffmpeg 抽音 + Whisper）
    - 圖片：JPG / PNG / BMP（GPT-4o 視覺摘要）
    """
    p = Path(path)
    ext = p.suffix.lower()

    # 音檔
    if _is_audio(p):
        text = extract_from_audio(p)
        return text, 0.0

    # 影片
    if _is_video(p):
        return extract_from_video(p)
    
    # #圖片
    if _is_image(p):
        text, vision_cost = extract_from_image(p)
        return text, vision_cost

    # 純文字
    if ext == ".txt":
        text = _read_txt(p)
        return text, 0.0

    # HTML
    if ext in {".html", ".htm"}:
        text = _read_html(p)
        return text, 0.0

    # PDF / DOCX / PPTX
    if ext == ".pdf":
        text = _read_pdf(p)
        return text, 0.0
    if ext == ".docx":
        text = _read_docx(p)
        return text, 0.0
    if ext == ".pptx":
        text = _read_pptx(p)
        return text, 0.0

    # 不支援的副檔名
    return "", 0.0
