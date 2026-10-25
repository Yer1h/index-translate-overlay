"""Тест режима ввода v2: ввод через keybd_event (видим для хуков другого
процесса), текст английский, целевой язык — Russian (меняем в config.json
на время теста)."""
import ctypes
import json
import subprocess
import time
from pathlib import Path

import keyboard
from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
u = ctypes.windll.user32
KEYUP = 2

# фраза: только a-z, пробел, запятая, '?', '!' — печатем по vk-кодам
PHRASE = "hi how are you doing today"


def type_char(ch: str) -> None:
    vk = None
    if ch == " ":
        vk = 0x20
    elif ch == ",":
        # запятая = Shift+6 (RU) / Shift+<,> (EN) — проще без неё
        return
    elif ch == "!":
        return
    elif ch == "?":
        return
    elif ch.isalpha():
        base = ch.lower()
        vk = ord("A") + (ord(base) - ord("a"))
        shift = ch.isupper()
    else:
        return
    if vk is None:
        return
    shift = ch.isupper() if ch.isalpha() else False
    if shift:
        u.keybd_event(0x10, 0, 0, 0)
    u.keybd_event(vk, 0, 0, 0)
    time.sleep(0.02)
    u.keybd_event(vk, 0, KEYUP, 0)
    if shift:
        u.keybd_event(0x10, 0, KEYUP, 0)
    time.sleep(0.03)


def main():
    cfg_path = ROOT / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg.setdefault("input", {})
    # целевой язык берём из конфига, который был прописан ПЕРЕД запуском
    # приложения (иначе оно не узнает об изменении)
    target = cfg["input"].get("target_lang", "Russian")

    keyboard.send("ctrl+alt+i")     # включить режим (приложение в другом процессе — увидит)
    time.sleep(1.0)
    subprocess.Popen(["notepad.exe"])
    time.sleep(1.5)
    for ch in PHRASE:
        type_char(ch)
    print("текст напечатан, ждём перевода…")
    time.sleep(8)
    ImageGrab.grab(all_screens=True).save(ROOT / "logs" / "input_mode_test2.png")

    subprocess.run(["taskkill", "/f", "/im", "notepad.exe"], capture_output=True)
    keyboard.send("ctrl+alt+i")
    time.sleep(0.5)
    print("DONE")


if __name__ == "__main__":
    main()
