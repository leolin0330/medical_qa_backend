# video_utils.py
"""
影片處理模組：GPT-4o 視覺摘要 + 雙通道融合
"""

# services/video_utils.py
from __future__ import annotations

import base64
import math
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable, List, Tuple
import re
from openai import OpenAI

# ====== 可調參數 ======
# 每隔幾秒抽一張影格（成本/精度開關）
FRAME_INTERVAL_SEC = float(os.getenv("FRAME_INTERVAL_SEC", "1.0"))
# 單次請求最多送幾張圖給 GPT-4o（避免太大）
BATCH_SIZE = int(os.getenv("CAPTION_BATCH_SIZE", "12"))
# 將影格縮到這個寬度（像素），降低請求成本
FRAME_RESIZE_WIDTH = int(os.getenv("FRAME_RESIZE_WIDTH", "768"))
# 使用的多模態模型（可用 gpt-4o 或 gpt-4o-mini）
VISION_MODEL = os.getenv("VISION_MODEL", "gpt-4o")
# 影像 caption 的系統提示（醫療/教學友好）
CAPTION_SYSTEM_PROMPT = os.getenv(
    "CAPTION_SYSTEM_PROMPT",
    "你是一位專業的醫學影片摘要助理。"
    "僅以醫學/教學角度描述畫面內容；禁止辨識或猜測任何人物身分或隱私，只描述場景、器械、操作步驟與可見結構。"
    "逐張影格請簡要寫中文重點：正在進行的醫療/教學步驟、使用的器械或可見組織/影像；"
    "若畫面與醫學無關或只有人物自拍/一般場景，請回覆：『本影格無醫學相關內容。』"
)

_openai_client: OpenAI | None = None


def _client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI()
    return _openai_client


# 常見拒絕語（中英字串都列，忽略大小寫）
REFUSAL_PATTERNS = [
    r"(?i)i['’]m\s+sorr(y|i)",            # I'm sorry / I’m sorry
    r"(?i)can('?|no)t\s+assist",          # can't assist / cannot assist
    r"(?i)unable\s+to\s+(help|comply|assist)",
    r"(?i)policy|policies|content\s+policy",
    r"無法協助", r"不能協助", r"抱歉.*無法", r"很抱歉.*不能"
]

def _looks_like_refusal(text: str) -> bool:
    for pat in REFUSAL_PATTERNS:
        if re.search(pat, text):
            return True
    return False



def _require_ffmpeg():
    from shutil import which
    if which("ffmpeg") is None:
        raise RuntimeError("缺少 ffmpeg，請先安裝並加入 PATH。")


# ---------- 抽幀 ----------

def _ffmpeg_extract_frames(video_path: str, out_dir: Path, interval_sec: float) -> List[Tuple[Path, float]]:
    """
    以固定間隔抽幀（每 interval_sec 取一張），輸出 JPEG。
    回傳 [(影格路徑, 以秒計的時間戳)]，時間戳由 ffmpeg 以命名帶出。
    """
    _require_ffmpeg()
    out_dir.mkdir(parents=True, exist_ok=True)

    # 以 fps=1/interval 取樣，檔名中帶 frame 序號
    # 再使用 -vf scale= 寬度縮放（維持比例），降低成本
    pattern = str(out_dir / "frame_%06d.jpg")
    scale_expr = f"scale={FRAME_RESIZE_WIDTH}:-1"
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"fps=1/{interval_sec},{scale_expr}",
        "-qscale:v", "3",
        pattern
    ]
    ret = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if ret.returncode != 0:
        raise RuntimeError("ffmpeg 抽幀失敗：\n" + ret.stderr.decode("utf-8", errors="ignore"))

    # 建立 (path, 秒數) 清單；因為我們固定間隔取樣，可用序號×間隔近似為時間戳
    frames = sorted(Path(out_dir).glob("frame_*.jpg"))
    results: List[Tuple[Path, float]] = []
    for i, p in enumerate(frames, start=1):
        ts = round(i * interval_sec, 2)
        results.append((p, ts))
    return results


# ---------- 影像 → Base64 data URL ----------

def _image_to_data_url(img_path: Path) -> str:
    with open(img_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def _chunk(iterable: Iterable, size: int):
    it = iter(iterable)
    while True:
        buf = []
        try:
            for _ in range(size):
                buf.append(next(it))
        except StopIteration:
            if buf:
                yield buf
            break
        yield buf


# ---------- GPT-4o Caption ----------

def _caption_batch(items: List[Tuple[Path, float]]) -> List[str]:
    """
    對一批 [(影像路徑, 秒數)] 產生描述；回傳每張對應的文字（與 items 順序一致）。
    """
    client = _client()

    print(f"[OpenAI] GPT-4o 處理 {len(items)} 張影格中...")

    # 準備 content：交替放文字 + 圖片（最多 BATCH_SIZE 張）
    content: List[dict] = [{
        "type": "text",
        "text": (
            "以下是一批影片影格。請逐張產出一句中文描述，"
            "格式為：`[mm:ss] 描述`。描述重點：臨床/教學重點、器械/器官/病灶、步驟變化。"
            "避免冗詞與臆測。"
        )
    }]

    for path, ts in items:
        data_url = _image_to_data_url(path)
        mm = int(ts // 60)
        ss = int(ts % 60)
        # 先給模型一段對應時間，幫助它按順序輸出
        content.append({"type": "text", "text": f"時間 {mm:02}:{ss:02}"})
        content.append({"type": "image_url", "image_url": {"url": data_url}})

    resp = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[
            {"role": "system", "content": CAPTION_SYSTEM_PROMPT},
            {"role": "user", "content": content}
        ],
        temperature=0.2,
        max_tokens=800,
    )

    text = (resp.choices[0].message.content or "").strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        lines = ["（無法產生描述）"] * len(items)
    if len(lines) < len(items):
        lines += [lines[-1]] * (len(items) - len(lines))
    return lines[:len(items)]
    print("[OpenAI] GPT-4o 回傳結果完成。")


def generate_captions(video_path: str) -> str:
    """
    核心：抽幀 → 批次丟 GPT-4o → 合併文字（含時間戳）。
    回傳：整段可索引文字。
    """
    with TemporaryDirectory() as td:
        out_dir = Path(td) / "frames"
        pairs = _ffmpeg_extract_frames(video_path, out_dir, FRAME_INTERVAL_SEC)
        print(f"[DEBUG] 抽取影格數量：{len(pairs)}")
        if not pairs:
            return "（此影片無法抽取任何畫面）"

        # 分批 caption
        all_lines: List[str] = []
        for batch in _chunk(pairs, BATCH_SIZE):
            captions = _caption_batch(batch)
            # 將每行補上時間戳（保險）
            for (path, ts), cap in zip(batch, captions):
                mm = int(ts // 60); ss = int(ts % 60)
                tag = f"[{mm:02}:{ss:02}]"

                # 若模型未加時間戳就補上
                if tag not in cap:
                    cap = f"{tag} {cap}"

                # ★ 過濾拒絕句：避免把「I'm sorry… / 無法協助…」寫進索引
                if _looks_like_refusal(cap):
                    cap = f"{tag} 本影格無醫學相關內容。"

                all_lines.append(cap)

        # 合併為可讀段落
        merged = "\n".join(all_lines)
        vision_cost = round(len(pairs) * 0.011, 5)  # 影格數 × 單張成本，保留 5 位小數
        print(f"[成本統計] 抽取 {len(pairs)} 張圖像 → 預估 GPT-4o 視覺處理成本：${vision_cost}")
        return merged.strip(), vision_cost
    


# ---------- Whisper + Caption 融合 ----------

def _split_sentences(text: str) -> List[str]:
    """
    粗略切句，用於融合（不做過度 NLP，避免依賴）。
    """
    if not text:
        return []
    # 以換行或句號分割
    import re as _re
    parts = _re.split(r"[。\n]+", text)
    return [p.strip() for p in parts if p.strip()]


def fuse_text(audio_text: str, captions_text: str) -> str:
    """
    將 Whisper transcript（音訊）與 GPT caption（畫面）融合成一份「可讀摘要」。
    目前使用簡單的策略：
      1) 先給出「語音重點」
      2) 再給出「畫面逐段描述」
    後續可升級為時間軸對齊（ASR 帶 timecode + 抽幀時間），再交給 GPT 進行段落合併。
    """
    audio_sent = _split_sentences(audio_text)
    # 將 caption 行保留為原樣（已含 [mm:ss]）
    caption_lines = [ln.strip() for ln in captions_text.splitlines() if ln.strip()]

    out: List[str] = []
    if audio_sent:
        out.append("【語音重點摘要】")
        # 取前 10–15 句避免過長
        keep = min(len(audio_sent), 15)
        for s in audio_sent[:keep]:
            out.append(f"• {s}")

    if caption_lines:
        out.append("\n【畫面逐段描述】")
        out.extend(caption_lines)

    if not out:
        return "（無法產生有效的語音與畫面內容）"

    return "\n".join(out).strip()


def caption_single_image(image_path: str | Path):
    """
    單張圖片 → GPT-4o 視覺描述。
    回傳：(描述文字, vision_cost)
    """
    p = Path(image_path)
    items = [(p, 0.0)]                 # 假設時間 0 秒
    captions = _caption_batch(items)   # 重用影片的 caption 流程
    text = captions[0] if captions else "（無法產生描述）"
    vision_cost = 0.011                # 單張影像固定成本
    return text, vision_cost