"""Конфигурация приложения: config.json в корне проекта."""
from __future__ import annotations

import json
import copy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# языки для меню/настроек — англ. названия понимает промпт-шаблон модели
LANGS = ["Russian", "English", "Chinese (Simplified)", "Chinese (Traditional)",
         "Japanese", "Korean", "German", "French", "Spanish", "Italian",
         "Portuguese", "Ukrainian", "Polish", "Turkish", "Arabic"]

DEFAULTS: dict[str, Any] = {
    # "local" — llama.cpp на этой машине (2B), "bilibili" — бесплатный онлайн-API (35B)
    "backend": "local",
    "target_lang": "Russian",

    "server": {
        "autostart": True,          # поднимать llama-server вместе с приложением
        "stop_on_exit": True,       # гасить сервер при выходе
        "host": "127.0.0.1",
        "port": 8080,
        "exe": "bin/llama-server.exe",
        "model": "models/Index-Translate-2B.Q6_K.gguf",
        "mmproj": "models/Index-Translate-2B.mmproj-Q8_0.gguf",
        "ctx_size": 6144,
        "ngl": 99,
        "extra_args": ["-fa", "on"],
        "startup_timeout_sec": 180,
    },

    "hotkeys": {
        "selected_text": "ctrl+alt+t",
        "screen_region": "ctrl+alt+g",
        "clipboard": "ctrl+alt+c",
        "input_toggle": "ctrl+alt+i",
    },

    # режим автоперевода ввода: печатаешь по-русски в любом поле,
    # пауза idle_sec — содержимое поля переводится и вставляется обратно
    "input": {
        "target_lang": "English",
        "idle_sec": 2.5,
    },

    "ui": {
        "font_size": 14,
        "opacity": 0.95,        # непрозрачность карточки 0.5–1.0
        "max_width_px": 560,    # максимальная ширина попапа
        "image_max_side": 1024, # куда ужимать скриншот перед отправкой в модель
        "auto_close_sec": 0,    # 0 — не закрывать автоматически
    },

    "history_limit": 500,

    "api": {
        # Бесплатный публичный API Bilibili, OpenAI-совместимый
        "base_url": "https://index-translate.bilibili.com/v1",
        "model": "index-translate",
        "user_agent": "Index-Translate-Client/1.0",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, path: Path | None = None):
        self.path = path or ROOT / "config.json"
        self.data: dict[str, Any] = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                with open(self.path, encoding="utf-8") as f:
                    user = json.load(f)
                self.data = _deep_merge(self.data, user)
            except Exception as e:  # повреждённый конфиг не должен ронять приложение
                print(f"[config] не удалось прочитать {self.path}: {e}")

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def abs_path(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else (ROOT / p)
