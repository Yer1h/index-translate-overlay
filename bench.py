"""Быстрый бенчмарк сервера: текст (en/ja/ru) + картинка со текстом.

Запуск (сервер должен работать):
    .venv\\Scripts\\python.exe bench.py
"""
from __future__ import annotations

import base64
import io
import sys
import time

import requests
from PIL import Image, ImageDraw, ImageFont

BASE = "http://127.0.0.1:8080"

PHRASES = [
    ("The quick brown fox jumps over the lazy dog.", "Russian"),
    ("Meeting postponed to Friday 3 PM, please confirm.", "Russian"),
    ("Привет! Давай встретимся завтра в семь вечера у метро.", "English"),
    ("雨の中を走り抜ける電車の窓から、街の灯りが滲んで見えた。", "Russian"),
    ("这个 DLC 的价格会在周末打折，别忘了领取每日奖励。", "Russian"),
]


def translate(content: str | list, target: str, tag: str) -> None:
    payload = {
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "max_tokens": 400,
        "stream": False,
        "model": "index-translate",
        "chat_template_kwargs": {"enable_thinking": False},
    }
    t0 = time.monotonic()
    r = requests.post(f"{BASE}/v1/chat/completions", json=payload, timeout=300)
    ms = (time.monotonic() - t0) * 1000
    r.raise_for_status()
    data = r.json()
    out = data["choices"][0]["message"]["content"].strip()
    usage = data.get("usage", {})
    tok_s = ""
    if usage.get("completion_tokens") and ms > 0:
        tok_s = f" | {usage['completion_tokens'] / (ms / 1000):.0f} tok/s"
    print(f"[{tag}] {ms:6.0f} мс{tok_s} | {out!r}")


def make_test_image() -> str:
    img = Image.new("RGB", (720, 200), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 40)
    except OSError:
        font = ImageFont.load_default()
    d.text((24, 40), "Your subscription expires", fill="black", font=font)
    d.text((24, 110), "in 3 days. Renew now!", fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def main() -> None:
    # прогрев: первый запрос включает компиляцию CUDA-графов — меряем без него
    try:
        translate("Hello", "Russian", "warmup")
    except Exception as e:
        print(f"Сервер не готов: {e}")
        sys.exit(1)

    print("--- текст ---")
    for text, target in PHRASES:
        prompt = (f"Translate the following text into {target}, directly output "
                  f"the translation result, do not perform any explanation."
                  f"\n\n{text}\n/no_think")
        translate(prompt, target, f"{target[:2]}")

    print("--- картинка ---")
    b64 = make_test_image()
    content = [
        {"type": "image_url",
         "image_url": {"url": f"data:image/png;base64,{b64}"}},
        {"type": "text", "text":
            "Translate the text in this image into Russian, directly output "
            "the translation result, do not perform any explanation.\n/no_think"},
    ]
    translate(content, "Russian", "img")


if __name__ == "__main__":
    main()
