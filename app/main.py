"""Index-Translate Overlay: перевод выделенного текста, области экрана
и буфера обмена во всплывающей карточке. Трей + горячие клавиши.

Запуск: pythonw app/main.py (см. start.bat)."""
from __future__ import annotations

import ctypes
import json
import logging
import sys
import threading
from collections import deque
from logging.handlers import RotatingFileHandler
from pathlib import Path

# DPI-осознанность обязательна до создания QApplication — иначе скриншоты
# и координаты попапов поедут на масштабировании 125/150%
if sys.platform == "win32":
    _PMV2 = ctypes.c_void_p(-4)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
    try:
        if not ctypes.windll.user32.SetProcessDpiAwarenessContext(_PMV2):
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

import keyboard
from PySide6.QtCore import QObject, QRect, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (QAction, QColor, QFont, QGuiApplication, QIcon,
                           QLinearGradient, QPainter, QPixmap)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QDialog, QLabel, QListWidget,
                               QMenu, QMessageBox, QSystemTrayIcon,
                               QVBoxLayout, QWidget)

from .config import ROOT, Config, LANGS
from .capture import grab_screen_region
from .overlay.popup import ResultPopup
from .overlay.selector import RegionSelector
from .server_manager import LlamaServer
from .settings_ui import SettingsDialog
from .textgrab import (copy_selection, get_clipboard_text,
                       press_copy, press_paste, press_select_all,
                       set_clipboard_text)
from .translator import TranslateJob, TranslationClient

log = logging.getLogger("overlay")


def setup_logging() -> None:
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    handler = RotatingFileHandler(logs / "app.log", maxBytes=1_000_000,
                                  backupCount=2, encoding="utf-8")
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format=None)
    handler.setFormatter(fmt)


def make_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, 64, 64)
    grad.setColorAt(0, QColor("#3b82f6"))
    grad.setColorAt(1, QColor("#8b5cf6"))
    p.setBrush(grad)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 16, 16)
    p.setFont(QFont("Segoe UI", 26, QFont.Weight.Bold))
    p.setPen(QColor("white"))
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "文")
    p.end()
    return QIcon(pm)


class TranslateWorker(QThread):
    delta = Signal(str)
    done = Signal(str, int, int)      # перевод, first_ms, total_ms
    failed = Signal(str)

    def __init__(self, client: TranslationClient, mode: str, payload,
                 target: str, parent=None):
        super().__init__(parent)
        self.client = client
        self.mode = mode            # "text" | "image"
        self.payload = payload
        self.target = target
        self.job = TranslateJob()

    def run(self) -> None:
        try:
            if self.mode == "text":
                out = self.client.translate_text(
                    self.payload, self.target, self.delta.emit, self.job)
            else:
                out = self.client.translate_image(
                    self.payload, self.target, self.delta.emit, self.job)
            if self.job.cancelled:
                return
            self.done.emit(out, self.job.t_first_ms or 0, self.job.t_total_ms or 0)
        except Exception as e:
            if not self.job.cancelled:
                log.exception("ошибка перевода")
                self.failed.emit(str(e))


class ModeBadge(QWidget):
    """Индикатор режима автоперевода ввода: плашка в правом верхнем углу.
    Клик — выключить режим."""

    def __init__(self):
        super().__init__(None,
                         Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._label = QLabel("⌨ RU → English")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._label)
        self.setStyleSheet("""
            QWidget {{ background: rgba(59, 130, 246, 225);
                       border-radius: 8px; }}
            QLabel {{ color: white; font-size: 13px; padding: 5px 12px; }}
        """)
        self.adjustSize()
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 16, screen.top() + 16)

    def set_pair(self, target: str) -> None:
        self._label.setText(f"⌨ RU → {target}")
        self.adjustSize()
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 16, screen.top() + 16)

    def mousePressEvent(self, e) -> None:
        self.hide()


class InputMode:
    """Режим автоперевода ввода.

    Включён → слушаем клавиатуру; после паузы idle_sec без нажатий
    берём текст из активного поля (Ctrl+A, Ctrl+C), переводим RU →
    input.target_lang и вставляем обратно (Ctrl+V). Работает в любом
    приложении с обычным полем ввода; в терминалах/IDE лучше выключить.
    """

    def __init__(self, app: "OverlayApp"):
        self.app = app
        self.enabled = False
        self._typed = False
        self._busy = False
        self._timer: threading.Timer | None = None
        self._unhook = None
        self._lock = threading.Lock()

    def toggle(self, on: bool | None = None) -> None:
        with self._lock:
            new = (not self.enabled) if on is None else on
            changed = new != self.enabled
            self.enabled = new
            if changed and self.enabled:
                self._typed = False
                self._unhook = keyboard.on_release(self._on_key)
            elif changed and not self.enabled:
                if self._unhook:
                    try:
                        self._unhook()
                    except Exception:
                        pass
                    self._unhook = None
                if self._timer:
                    self._timer.cancel()
                    self._timer = None
        enabled = self.enabled
        target = self.app.cfg.data["input"]["target_lang"]
        # бейдж и меню — в GUI-потоке
        self.app.sig_input_state.emit(enabled, target)
        log.info("режим ввода %s", "включён" if enabled else "выключен")

    # ------------------------------------------------------------ клавиши
    def _on_key(self, event) -> None:
        name = event.name or ""
        if name in ("ctrl", "alt", "shift", "left ctrl", "right ctrl",
                    "left alt", "right alt", "left shift", "right shift",
                    "left windows", "right windows", "caps lock", "tab"):
            return
        try:
            if keyboard.is_pressed("ctrl") or keyboard.is_pressed("alt"):
                return  # горячие клавиши и шорткаты — не «набор текста»
        except Exception:
            pass
        if not self._typed:
            log.info("input-mode: первое нажатие после простоя (%r)", name)
        self._typed = True
        self._arm()

    def _arm(self) -> None:
        if self._timer:
            self._timer.cancel()
        idle = float(self.app.cfg.data["input"].get("idle_sec", 2.5))
        self._timer = threading.Timer(idle, self._fire)
        self._timer.daemon = True
        self._timer.start()

    # -------------------------------------------------------------- перевод
    def _fire(self) -> None:
        if self._busy or not self.enabled or not self._typed:
            return
        self._busy = True
        try:
            log.info("input-mode: пауза в наборе, переводим поле")
            self._translate_active_field()
        except Exception:
            log.exception("input-mode: ошибка перевода поля")
        finally:
            self._busy = False
            self._typed = False
            if self.enabled:
                self._arm()

    def _translate_active_field(self) -> None:
        import time as _t
        from .textgrab import _user32

        seq_before = _user32.GetClipboardSequenceNumber()
        saved = get_clipboard_text()

        press_select_all()
        _t.sleep(0.02)
        press_copy()
        for _ in range(30):  # ждём, пока приложение отдаст выделение
            if _user32.GetClipboardSequenceNumber() != seq_before:
                break
            _t.sleep(0.02)
        _t.sleep(0.05)
        text = get_clipboard_text()
        # пусто или копирование не удалось (терминал? защита?) — выходим,
        # ничего не вставляя
        if not text or not text.strip():
            return

        target = self.app.cfg.data["input"]["target_lang"]
        job = TranslateJob()
        translation = self.app.client.translate_text(
            text, target, lambda s: None, job)
        if not translation:
            return

        set_clipboard_text(translation)
        _t.sleep(0.05)
        press_paste()
        # вернуть пользователю его буфер обмена
        _t.sleep(0.4)
        if saved:
            set_clipboard_text(saved)
        log.info("input-mode: перевёл поле на %s за %s мс",
                 target, job.t_total_ms)


class OverlayApp(QObject):
    # из потоков keyboard/сервера в GUI-поток
    sig_translate_text = Signal(str)      # текст из выделения/буфера
    sig_show_selector = Signal()          # показать рамку выбора области
    sig_need_popup = Signal(str, str)     # mode: "cursor"|"rect:json", подсказка
    sig_tray_msg = Signal(str, str)
    sig_input_state = Signal(bool, str)   # режим ввода вкл/выкл + язык ввода

    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.cfg = Config()
        self.client = TranslationClient(self.cfg)
        self.server = LlamaServer(self.cfg)
        self.worker: TranslateWorker | None = None
        self.popup: ResultPopup | None = None
        self.selector: RegionSelector | None = None
        self.history: deque[dict] = deque(maxlen=int(self.cfg.data["history_limit"]))

        self.sig_translate_text.connect(self._on_text_ready)
        self.sig_show_selector.connect(self._show_selector)
        self.sig_need_popup.connect(self._on_need_popup)
        self.sig_input_state.connect(self._on_input_state)
        self.sig_tray_msg.connect(lambda t, m: self.tray.showMessage(
            t, m, QSystemTrayIcon.MessageIcon.Information, 4000))

        self.input_mode = InputMode(self)
        self.badge: ModeBadge | None = None

        self._load_history()
        self._build_tray()
        self._register_hotkeys()

        if (self.cfg.data["backend"] == "local"
                and self.cfg.data["server"]["autostart"]):
            threading.Thread(target=self._boot_server, daemon=True).start()

    # ------------------------------------------------------------- сервер
    def _boot_server(self) -> None:
        try:
            if self.server.is_healthy():
                log.info("llama-server уже запущен (внешний) — используем")
                self.sig_tray_msg.emit("Переводчик", "Сервер уже работает")
                return
            self.server.start()
            ok = self.server.wait_healthy(
                float(self.cfg.data["server"]["startup_timeout_sec"]))
            if ok:
                self.sig_tray_msg.emit("Переводчик", "Модель загружена, готово")
            else:
                self.sig_tray_msg.emit("Переводчик", "Сервер не ответил вовремя")
        except Exception as e:
            log.exception("не удалось поднять сервер")
            self.sig_tray_msg.emit("Переводчик", f"Ошибка сервера: {e}")

    def _server_action(self, action: str) -> None:
        def run():
            if action == "start":
                try:
                    if not self.server.is_healthy():
                        self.server.start()
                        self.server.wait_healthy(
                            float(self.cfg.data["server"]["startup_timeout_sec"]))
                    self.sig_tray_msg.emit("Сервер", "Запущен")
                except Exception as e:
                    self.sig_tray_msg.emit("Сервер", f"Ошибка: {e}")
            elif action == "stop":
                self.server.stop()
                self.sig_tray_msg.emit("Сервер", "Остановлен")
            elif action == "restart":
                self.server.stop()
                self._boot_server()
        threading.Thread(target=run, daemon=True).start()

    # -------------------------------------------------------- горячие клавиши
    def _register_hotkeys(self) -> None:
        # снимаем только СВОИ хоткеи: keyboard.unhook_all() заодно убил бы
        # хук нажатий режима автоперевода ввода
        for remove in getattr(self, "_hotkey_removers", []):
            try:
                remove()
            except Exception:
                pass
        self._hotkey_removers = []
        hk = self.cfg.data["hotkeys"]
        try:
            self._hotkey_removers.append(
                keyboard.add_hotkey(hk["selected_text"], self._hk_selected))
            self._hotkey_removers.append(
                keyboard.add_hotkey(hk["screen_region"], self._hk_region))
            self._hotkey_removers.append(
                keyboard.add_hotkey(hk["clipboard"], self._hk_clipboard))
            if "input_toggle" in hk:
                self._hotkey_removers.append(
                    keyboard.add_hotkey(hk["input_toggle"],
                                        self._hk_input_toggle))
            log.info("hotkeys: %s", hk)
        except Exception as e:
            log.error("не удалось зарегистрировать горячие клавиши: %s", e)
            self.sig_tray_msg.emit(
                "Переводчик", f"Горячие клавиши не зарегистрированы: {e}")

    def _hk_selected(self) -> None:
        try:
            text = copy_selection()
        except Exception:
            log.exception("copy_selection упал")
            return
        if text:
            self.sig_translate_text.emit(text)
        else:
            self.sig_need_popup.emit(
                "cursor", "Текст не захвачен. Выдели текст или используй "
                          f"{self.cfg.data['hotkeys']['clipboard']} для буфера.")

    def _hk_clipboard(self) -> None:
        try:
            text = get_clipboard_text()
        except Exception:
            log.exception("get_clipboard_text упал")
            return
        if text and text.strip():
            self.sig_translate_text.emit(text)
        else:
            self.sig_need_popup.emit("cursor", "Буфер обмена пуст")

    def _hk_region(self) -> None:
        # селектор — QWidget, создаём строго в GUI-потоке через сигнал
        self.sig_show_selector.emit()

    def _hk_input_toggle(self) -> None:
        self.input_mode.toggle()

    def _on_input_state(self, enabled: bool, target: str) -> None:
        if enabled:
            if self.badge is None:
                self.badge = ModeBadge()
            self.badge.set_pair(target)
            self.badge.show()
        elif self.badge is not None:
            self.badge.hide()
        self._rebuild_tray()

    # --------------------------------------------------------------- GUI
    def _show_selector(self) -> None:
        self._close_popup()
        self.selector = RegionSelector()
        self.selector.picked.connect(self._on_region_picked)
        self.selector.cancelled.connect(lambda: setattr(self, "selector", None))
        self.selector.show()
        log.info("селектор области показан")

    def _on_region_picked(self, rect: QRect, screen) -> None:
        log.info("область выделена: %s", rect)
        self.selector = None
        # даём окну-маске исчезнуть из кадра
        self.app.processEvents()
        QThread.msleep(70)
        try:
            img = grab_screen_region(screen, rect)
        except Exception as e:
            log.exception("скриншот не удался")
            self._on_need_popup("rect:" + json.dumps(
                [rect.x(), rect.y(), rect.width(), rect.height()]), "⚠ " + str(e))
            return
        self._start_translation("image", img, "rect", rect)

    def _on_text_ready(self, text: str) -> None:
        self._start_translation("text", text, "cursor", None)

    def _on_need_popup(self, mode: str, hint: str) -> None:
        self._close_popup()
        self.popup = ResultPopup(self.cfg)
        self._wire_popup()
        if mode.startswith("rect:"):
            coords = json.loads(mode[5:])
            self.popup.show_at_rect(QRect(*coords))
        else:
            self.popup.show_at_cursor()
        self.popup.fail(hint)

    # ----------------------------------------------------------- перевод
    def _start_translation(self, mode: str, payload, place: str, rect) -> None:
        self._cancel_worker()
        self._close_popup()
        self.popup = ResultPopup(self.cfg)
        self._wire_popup()
        if place == "rect" and rect is not None:
            self.popup.show_at_rect(rect)
        else:
            self.popup.show_at_cursor()
        if mode == "text":
            self.popup.set_source_hint(payload)

        # если локальный сервер мёртв — попробуем поднять на лету
        if (self.cfg.data["backend"] == "local"
                and not self.server.is_healthy()):
            self.popup.fail("Сервер не отвечает, запускаю…")
            threading.Thread(target=self._boot_server, daemon=True).start()
            return

        target = self.cfg.data["target_lang"]
        self.worker = TranslateWorker(self.client, mode, payload, target)
        self.worker.delta.connect(self._on_delta)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_fail)
        self.worker.start()

    def _wire_popup(self) -> None:
        if self.popup is None:
            return
        self.popup.closed_sig.connect(self._on_popup_closed)
        # клик мимо карточки закрывает её (если не закреплена)
        self.app.installEventFilter(self)

    def _cancel_worker(self) -> None:
        if self.worker is not None:
            self.worker.job.cancel.set()
            self.worker = None

    def _close_popup(self) -> None:
        self._cancel_worker()
        if self.popup is not None:
            p, self.popup = self.popup, None
            p.closed_sig.disconnect(self._on_popup_closed)
            p.close()
            p.deleteLater()
        self.app.removeEventFilter(self)

    def _on_popup_closed(self) -> None:
        self._cancel_worker()
        if self.popup is not None:
            self.popup = None
        self.app.removeEventFilter(self)

    def _on_delta(self, text: str) -> None:
        if self.popup is not None:
            self.popup.append_stream(text)

    def _on_done(self, translation: str, first_ms: int, total_ms: int) -> None:
        worker, self.worker = self.worker, None
        if worker:
            worker.quit()
            worker.wait(2000)
            worker.deleteLater()
        if self.popup is None:
            return
        src = "📷 область" if "image" in (worker.mode if worker else "") else "текст"
        meta = f"✓ {total_ms} мс (первый символ {first_ms} мс) · {self.client.backend_label}"
        self.popup.finish(translation, meta)
        self._append_history(src, translation)
        auto = int(self.cfg.data["ui"].get("auto_close_sec", 0))
        if auto > 0:
            popup = self.popup
            QTimer.singleShot(auto * 1000, lambda: (
                popup.close() if (popup is self.popup and not popup.pinned)
                else None))

    def _on_fail(self, message: str) -> None:
        worker, self.worker = self.worker, None
        if worker:
            worker.quit()
            worker.wait(2000)
            worker.deleteLater()
        if self.popup is not None:
            self.popup.fail(message)

    # ------------------------------------------------------------- history
    def _append_history(self, src: str, translation: str) -> None:
        import datetime
        entry = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
                 "target": self.cfg.data["target_lang"],
                 "src": src, "text": translation}
        self.history.append(entry)
        try:
            with open(ROOT / "history.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _load_history(self) -> None:
        f = ROOT / "history.jsonl"
        if not f.exists():
            return
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
            for line in lines[-self.history.maxlen:]:
                self.history.append(json.loads(line))
        except Exception:
            pass

    def _show_history(self) -> None:
        dlg = QDialog()
        dlg.setWindowTitle("История переводов")
        dlg.resize(560, 420)
        lay = QVBoxLayout(dlg)
        lw = QListWidget()
        for e in reversed(self.history):
            lw.addItem(f"[{e['ts']}] →{e['target']} ({e['src']})\n{e['text'][:300]}")
        lw.itemDoubleClicked.connect(lambda it: (
            QApplication.clipboard().setText(it.text().split("\n", 1)[1]),
            None))
        lay.addWidget(QLabel("Двойной клик — скопировать перевод"))
        lay.addWidget(lw)
        dlg.exec()

    # ------------------------------------------------------------- eventFilter
    def eventFilter(self, obj, ev) -> bool:
        from PySide6.QtCore import QEvent
        if (self.popup is not None and not self.popup.pinned
                and ev.type() == QEvent.Type.MouseButtonPress):
            w = self.app.widgetAt(ev.globalPosition().toPoint())
            inside = False
            while w is not None:
                if w is self.popup:
                    inside = True
                    break
                w = w.parentWidget()
            if not inside:
                self._close_popup()
        return super().eventFilter(obj, ev)

    # ----------------------------------------------------------------- tray
    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(make_icon())
        self.tray.setToolTip("Index-Translate Overlay")
        menu = QMenu()

        def act(text, slot, shortcut=None):
            a = QAction(text, menu)
            if shortcut:
                a.setShortcut(shortcut)
            a.triggered.connect(slot)
            menu.addAction(a)
            return a

        hk = self.cfg.data["hotkeys"]
        act(f"Перевести выделенное  [{hk['selected_text']}]", self._hk_selected)
        act(f"Перевести область экрана  [{hk['screen_region']}]", self._hk_region)
        act(f"Перевести буфер обмена  [{hk['clipboard']}]",
            self._hk_clipboard)
        menu.addSeparator()

        input_act = QAction(
            f"Автоперевод ввода  [{hk.get('input_toggle', 'ctrl+alt+i')}]",
            menu, checkable=True)
        input_act.setChecked(self.input_mode.enabled)
        input_act.toggled.connect(lambda on: self.input_mode.toggle(on))
        menu.addAction(input_act)

        inp_lang_menu = menu.addMenu("Язык ввода (куда переводить)")
        for lang in LANGS:
            a = QAction(lang, inp_lang_menu, checkable=True)
            a.setChecked(lang == self.cfg.data["input"].get("target_lang",
                                                            "English"))
            def set_inp_lang(checked, lang=lang):
                if checked:
                    self.cfg.data["input"]["target_lang"] = lang
                    self.cfg.save()
                    if self.input_mode.enabled:
                        self.input_mode.toggle(True)  # обновить бейдж
            a.toggled.connect(set_inp_lang)
            inp_lang_menu.addAction(a)
        menu.addSeparator()

        lang_menu = menu.addMenu("Язык перевода")
        for lang in LANGS:
            a = QAction(lang, lang_menu, checkable=True)
            a.setChecked(lang == self.cfg.data["target_lang"])
            def set_lang(checked, lang=lang):
                if checked:
                    self.cfg.data["target_lang"] = lang
                    self.cfg.save()
                    self._rebuild_tray()
            a.toggled.connect(set_lang)
            lang_menu.addAction(a)

        backend_menu = menu.addMenu("Движок")
        for key, label in (("local", "Локально · 2B (оффлайн)"),
                           ("bilibili", "Онлайн API · 35B (бесплатно)")):
            a = QAction(label, backend_menu, checkable=True)
            a.setChecked(self.cfg.data["backend"] == key)
            def set_backend(checked, key=key):
                if checked:
                    self.cfg.data["backend"] = key
                    self.cfg.save()
                    self._rebuild_tray()
                    if key == "local" and not self.server.is_healthy():
                        threading.Thread(target=self._boot_server, daemon=True).start()
            a.toggled.connect(set_backend)
            backend_menu.addAction(a)

        srv_menu = menu.addMenu("Сервер (локальный)")
        for label, cmd in (("Запустить", "start"), ("Остановить", "stop"),
                           ("Перезапустить", "restart")):
            a = QAction(label, srv_menu)
            a.triggered.connect(lambda checked=False, c=cmd: self._server_action(c))
            srv_menu.addAction(a)

        menu.addSeparator()
        act("История…", self._show_history)
        act("Настройки…", self._open_settings)
        act("Выход", self._quit)
        self.tray.setContextMenu(menu)
        self.tray.show()

    def _rebuild_tray(self) -> None:
        self.tray.hide()
        self.tray.deleteLater()
        self._build_tray()
        self._register_hotkeys()

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.cfg)  # родитель-QWidget не нужен: OverlayApp — QObject
        if dlg.exec():
            self.cfg.save()
            self._rebuild_tray()

    def _quit(self) -> None:
        self._cancel_worker()
        if self.cfg.data["server"]["stop_on_exit"]:
            self.server.stop()
        self.tray.hide()
        self.app.quit()


def ensure_single_instance(app: QApplication) -> bool:
    name = "IndexTranslateOverlay"
    sock = QLocalSocket()
    sock.connectToServer(name)
    if sock.waitForConnected(300):
        sock.disconnectFromServer()
        return False  # уже запущено
    QLocalServer.removeServer(name)
    server = QLocalServer(app)
    server.listen(name)
    return True


def main() -> int:
    setup_logging()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Index-Translate Overlay")
    if not ensure_single_instance(app):
        log.warning("экземпляр уже запущен — выходим")
        return 0
    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.error("системный трей недоступен")
        return 1
    _app = OverlayApp(app)  # noqa: F841 — держим ссылку
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
