"""Живой тест режима автоперевода ввода.

Включает режим (Ctrl+Alt+I), открывает Блокнот, печатает русскую фразу,
ждёт паузы+перевода, снимает скриншот, выключает режим.
"""
import subprocess
import time

import keyboard
from PIL import ImageGrab

TEXT = "Привет! Как у тебя дела? Давай поиграем сегодня вечером."


def main():
    keyboard.send("ctrl+alt+i")          # включить режим
    time.sleep(1.0)
    subprocess.Popen(["notepad.exe"])
    time.sleep(1.5)
    keyboard.write(TEXT, delay=0.02)     # печатаем по-русски
    time.sleep(8)                        # пауза 2.5с + перевод + вставка
    ImageGrab.grab(all_screens=True).save("logs/input_mode_test.png")
    print("screenshot saved")
    time.sleep(0.5)
    subprocess.run(["taskkill", "/f", "/im", "notepad.exe"], capture_output=True)
    keyboard.send("ctrl+alt+i")          # выключить режим
    time.sleep(0.5)
    print("DONE")


if __name__ == "__main__":
    main()
