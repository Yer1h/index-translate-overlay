"""E2E-тест режимов «выделенный текст» и «область экрана».

Открывает Блокнот с английской фразой, затем:
  1) Ctrl+A + Ctrl+Alt+T  -> карточка с переводом (скриншот 1)
  2) Ctrl+Alt+G + рамка мышью над текстом -> vision-перевод (скриншот 2)
"""
import ctypes
import subprocess
import time

import keyboard
from PIL import ImageGrab

user32 = ctypes.windll.user32
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000

TEXT = "Meeting postponed to Friday 3 PM, please confirm your attendance."


def find_notepad_rect():
    import ctypes.wintypes as wt
    hwnd = user32.GetForegroundWindow()  # блокнот только что открыт и в фокусе
    if not hwnd:
        return None
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def click_at(x, y):
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    user32.SetCursorPos(x, y)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_LEFTDOWN,
                       x * 65535 // sw, y * 65535 // sh, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_LEFTUP,
                       x * 65535 // sw, y * 65535 // sh, 0, 0)


def drag(x1, y1, x2, y2, steps=25):
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    user32.SetCursorPos(x1, y1)
    time.sleep(0.15)
    user32.mouse_event(MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_LEFTDOWN,
                       x1 * 65535 // sw, y1 * 65535 // sh, 0, 0)
    time.sleep(0.1)
    for i in range(1, steps + 1):
        x = x1 + (x2 - x1) * i // steps
        y = y1 + (y2 - y1) * i // steps
        user32.SetCursorPos(x, y)
        user32.mouse_event(MOUSEEVENTF_ABSOLUTE,
                           x * 65535 // sw, y * 65535 // sh, 0, 0)
        time.sleep(0.02)
    time.sleep(0.1)
    user32.mouse_event(MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_LEFTUP,
                       x2 * 65535 // sw, y2 * 65535 // sh, 0, 0)


def main():
    subprocess.Popen(["notepad.exe"])
    time.sleep(1.5)
    keyboard.write(TEXT, delay=0.01)
    time.sleep(0.5)

    rect = find_notepad_rect()
    print("notepad rect:", rect)

    # --- тест 1: выделенный текст
    keyboard.send("ctrl+a")
    time.sleep(0.3)
    keyboard.send("ctrl+alt+t")
    time.sleep(4)
    ImageGrab.grab(all_screens=True).save("logs/e2e_selected.png")
    print("test1 done")
    # клик мимо — закрыть карточку
    click_at(960, 540)
    time.sleep(0.8)

    # --- тест 2: область экрана
    if rect:
        x1, y1, x2, y2 = rect
        cx1, cy1 = x1 + 60, y1 + 100   # первая строка текста в клиентской области
        cx2, cy2 = min(x1 + 900, x2 - 40), y1 + 170
    else:
        cx1, cy1, cx2, cy2 = 200, 200, 1000, 280
    keyboard.send("ctrl+alt+g")
    time.sleep(0.8)                    # дождаться полноэкранной рамки
    drag(cx1, cy1, cx2, cy2)
    time.sleep(6)                      # vision-перевод
    ImageGrab.grab(all_screens=True).save("logs/e2e_region.png")
    print("test2 done")

    subprocess.run(["taskkill", "/f", "/im", "notepad.exe"],
                   capture_output=True)
    click_at(960, 540)                 # закрыть карточку кликом мимо
    print("ALL DONE")


if __name__ == "__main__":
    main()
