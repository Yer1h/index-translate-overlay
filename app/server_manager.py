"""Управление llama-server: запуск, ожидание готовности, перезапуск, остановка."""
from __future__ import annotations

import logging
import subprocess
import threading
import time
from pathlib import Path

import requests

from .config import ROOT

log = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000


class LlamaServer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.proc: subprocess.Popen | None = None
        self.owned = False  # True, если процесс запущены нами (чужой не трогаем)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ api
    @property
    def base_url(self) -> str:
        s = self.cfg.data["server"]
        return f"http://{s['host']}:{s['port']}"

    def is_healthy(self) -> bool:
        try:
            r = requests.get(self.base_url + "/health", timeout=2)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def start(self) -> None:
        """Запускает процесс (неблокирующее). Бросает исключение при ошибке."""
        with self._lock:
            if self.proc and self.proc.poll() is None:
                return
            s = self.cfg.data["server"]
            exe = self.cfg.abs_path(s["exe"])
            model = self.cfg.abs_path(s["model"])
            mmproj = self.cfg.abs_path(s["mmproj"])
            if not exe.exists():
                raise FileNotFoundError(f"Не найден llama-server: {exe}")
            if not model.exists():
                raise FileNotFoundError(f"Не найдена модель: {model}")

            args = [
                str(exe),
                "-m", str(model),
                "-c", str(int(s["ctx_size"])),
                "-ngl", str(int(s["ngl"])),
                "--host", s["host"],
                "--port", str(int(s["port"])),
                "--jinja",          # честный chat-шаблон из GGUF (+enable_thinking=False)
            ]
            if mmproj.exists():
                args += ["--mmproj", str(mmproj)]
            else:
                log.warning("mmproj не найден (%s): режим картинок работать не будет",
                            mmproj)
            args += list(s.get("extra_args", []))

            logs_dir = ROOT / "logs"
            logs_dir.mkdir(exist_ok=True)
            log_file = open(logs_dir / "server.log", "ab")
            log.info("запуск llama-server: %s", " ".join(args))
            self.proc = subprocess.Popen(
                args, cwd=str(ROOT), stdout=log_file, stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW,
            )
            self.owned = True

    def wait_healthy(self, timeout: float = 180.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc and self.proc.poll() is not None:
                raise RuntimeError(
                    f"llama-server упал при старте (код {self.proc.returncode}), "
                    f"см. logs/server.log")
            if self.is_healthy():
                return True
            time.sleep(0.5)
        return False

    def stop(self) -> None:
        with self._lock:
            if self.proc and self.proc.poll() is None:
                log.info("остановка llama-server")
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            self.proc = None
            self.owned = False
