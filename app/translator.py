"""Клиент перевода: локальный llama-server (OpenAI-совместимый API)
или бесплатный онлайн-API Bilibili. Стриминг, отмена, кэш текстов."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import threading
from collections import OrderedDict
from typing import Callable, Optional

import requests
from PIL import Image


class TranslateJob:
    """Один перевод. job.cancel прерывает стриминг из любого потока."""

    def __init__(self) -> None:
        self.cancel = threading.Event()
        self.t_first_ms: Optional[int] = None
        self.t_total_ms: Optional[int] = None

    @property
    def cancelled(self) -> bool:
        return self.cancel.is_set()


def strip_think(s: str) -> str:
    """Убирает служебные блоки размышлений Qwen, если модель их просочила."""
    if "</think>" in s:
        s = s.split("</think>", 1)[1]
    elif "<think>" in s:
        return ""  # модель ещё «думает»
    return s.replace("/no_think", "").strip()


class TranslationError(RuntimeError):
    pass


class TranslationClient:
    def __init__(self, cfg):
        self.cfg = cfg
        self._cache: "OrderedDict[str, str]" = OrderedDict()
        self._cache_lock = threading.Lock()
        self._cache_max = 256

    # ------------------------------------------------------------------ API
    @property
    def backend_label(self) -> str:
        return "API 35B" if self.cfg.data["backend"] == "bilibili" else "локально 2B"

    def base_url(self) -> str:
        if self.cfg.data["backend"] == "bilibili":
            return self.cfg.data["api"]["base_url"].rstrip("/")
        s = self.cfg.data["server"]
        return f"http://{s['host']}:{s['port']}/v1"

    def translate_text(self, text: str, target: str,
                       on_delta: Callable[[str], None], job: TranslateJob) -> str:
        text = text.strip()
        if not text:
            return ""
        key = self._cache_key("text", target, text)
        hit = self._cache_get(key)
        if hit is not None:
            on_delta(hit)
            return hit
        prompt = (
            f"Translate the following text into {target}, directly output the "
            f"translation result, do not perform any explanation.\n\n{text}\n/no_think"
        )
        result = self._run(prompt, on_delta, job)
        if result and not job.cancelled:
            self._cache_put(key, result)
        return result

    def translate_image(self, img: Image.Image, target: str,
                        on_delta: Callable[[str], None], job: TranslateJob) -> str:
        prompt = (
            f"Translate the text in this image into {target}, directly output the "
            f"translation result, do not perform any explanation.\n/no_think"
        )
        b64, mime = self._image_payload(img)
        content = [
            {"type": "image_url",
             "image_url": {"url": f"data:{mime};base64,{b64}"}},
            {"type": "text", "text": prompt},
        ]
        return self._run(content, on_delta, job)

    # -------------------------------------------------------------- internals
    def _cache_key(self, mode: str, target: str, text: str) -> str:
        h = hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:16]
        return f"{mode}:{target}:{h}"

    def _cache_get(self, key: str) -> Optional[str]:
        with self._cache_lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        return None

    def _cache_put(self, key: str, value: str) -> None:
        with self._cache_lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_max:
                self._cache.popitem(last=False)

    def _image_payload(self, img: Image.Image) -> tuple[str, str]:
        max_side = int(self.cfg.data["ui"].get("image_max_side", 1024))
        img = img.copy()
        if max(img.size) > max_side:
            img.thumbnail((max_side, max_side), Image.LANCZOS)
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = io.BytesIO()
        if img.width <= 640:  # мелкий текст — PNG без артефактов
            img.save(buf, "PNG")
            mime = "image/png"
        else:
            img.save(buf, "JPEG", quality=88)
            mime = "image/jpeg"
        return base64.b64encode(buf.getvalue()).decode("ascii"), mime

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.cfg.data["backend"] == "bilibili":
            # без этого User-Agent API Bilibili не принимает картинки
            h["User-Agent"] = self.cfg.data["api"]["user_agent"]
        return h

    def _run(self, content, on_delta: Callable[[str], None],
             job: TranslateJob, max_tokens: int = 700) -> str:
        import time
        t0 = time.monotonic()

        use_kwargs = self.cfg.data["backend"] != "bilibili" or True
        # у llama-server thinking выключается шаблонизатором (нужен --jinja),
        # на всякий случай дублируем мягким переключателем /no_think в промпте
        payload = {
            "messages": [{"role": "user", "content": content}],
            "temperature": 0,
            "top_p": 1,
            "max_tokens": max_tokens,
            "stream": True,
            "model": (self.cfg.data["api"]["model"]
                      if self.cfg.data["backend"] == "bilibili"
                      else "index-translate"),
        }
        url = self.base_url() + "/chat/completions"

        for attempt in range(2):
            if attempt == 0:
                payload["chat_template_kwargs"] = {"enable_thinking": False}
            else:
                payload.pop("chat_template_kwargs", None)  # старые сборки не знают поля
            try:
                return self._stream(url, payload, on_delta, job, t0)
            except requests.HTTPError as e:
                code = e.response.status_code if e.response is not None else 0
                if attempt == 0 and code in (400, 422, 500):
                    continue  # повторяем без chat_template_kwargs
                raise TranslationError(
                    f"HTTP {code}: {self._err_text(e.response)}") from e
            except requests.RequestException as e:
                raise TranslationError(f"Нет связи с сервером перевода: {e}") from e
        raise TranslationError("Сервер отклонил запрос")

    @staticmethod
    def _err_text(resp) -> str:
        try:
            body = resp.json()
            return str(body.get("error", {}).get("message", body))[:200]
        except Exception:
            return ""

    def _stream(self, url, payload, on_delta, job, t0) -> str:
        import time
        full = ""
        with requests.post(url, json=payload, headers=self._headers(),
                           stream=True, timeout=(5, 300)) as r:
            r.raise_for_status()
            for raw in r.iter_lines():
                if job.cancelled:
                    job.cancel.set()
                    break
                if not raw:
                    continue
                line = raw.decode("utf-8", "replace")
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                piece = (choices[0].get("delta") or {}).get("content")
                if piece:
                    full += piece
                    if job.t_first_ms is None:
                        job.t_first_ms = int((time.monotonic() - t0) * 1000)
                    on_delta(strip_think(full))
        job.t_total_ms = int((time.monotonic() - t0) * 1000)
        out = strip_think(full)
        if not out:
            raise TranslationError("Модель вернула пустой ответ")
        return out
