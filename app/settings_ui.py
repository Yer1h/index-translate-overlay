"""Диалог настроек: язык, горячие клавиши, сервер, внешний вид."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QSpinBox,
                               QVBoxLayout)

from .config import ROOT, LANGS


def _models_in_dir() -> list[str]:
    d = ROOT / "models"
    out = []
    if d.exists():
        for p in sorted(d.glob("*.gguf")):
            if "mmproj" in p.name.lower():
                continue
            out.append(f"models/{p.name}")
    return out


def _mmproj_in_dir() -> list[str]:
    d = ROOT / "models"
    out = []
    if d.exists():
        for p in sorted(d.glob("*mmproj*.gguf")):
            out.append(f"models/{p.name}")
    return out


class SettingsDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Настройки — Index-Translate Overlay")
        self.setMinimumWidth(480)

        lay = QVBoxLayout(self)
        form = QFormLayout()

        self.lang = QComboBox()
        self.lang.setEditable(True)
        self.lang.addItems(LANGS)
        self.lang.setCurrentText(cfg.data["target_lang"])
        form.addRow("Язык перевода", self.lang)

        self.backend = QComboBox()
        self.backend.addItem("Локально · 2B (оффлайн)", "local")
        self.backend.addItem("Онлайн API Bilibili · 35B", "bilibili")
        i = self.backend.findData(cfg.data["backend"])
        self.backend.setCurrentIndex(max(0, i))
        form.addRow("Движок", self.backend)
        lay.addLayout(form)

        # --- горячие клавиши
        gb_hk = QGroupBox("Горячие клавиши (формат: ctrl+alt+t)")
        f_hk = QFormLayout(gb_hk)
        hk = cfg.data["hotkeys"]
        self.hk_sel = QLineEdit(hk["selected_text"])
        self.hk_reg = QLineEdit(hk["screen_region"])
        self.hk_clip = QLineEdit(hk["clipboard"])
        self.hk_input = QLineEdit(hk.get("input_toggle", "ctrl+alt+i"))
        f_hk.addRow("Перевести выделенное", self.hk_sel)
        f_hk.addRow("Перевести область экрана", self.hk_reg)
        f_hk.addRow("Перевести буфер обмена", self.hk_clip)
        f_hk.addRow("Вкл/выкл автоперевод ввода", self.hk_input)
        lay.addWidget(gb_hk)

        # --- автоперевод ввода
        gb_inp = QGroupBox("Автоперевод ввода (печатаешь по-русски → перевод в поле)")
        f_inp = QFormLayout(gb_inp)
        inp = cfg.data.get("input", {})
        self.inp_lang = QComboBox()
        self.inp_lang.setEditable(True)
        self.inp_lang.addItems(LANGS)
        self.inp_lang.setCurrentText(inp.get("target_lang", "English"))
        f_inp.addRow("Язык, на который переводить", self.inp_lang)

        self.inp_idle = QDoubleSpinBox()
        self.inp_idle.setRange(1.0, 10.0)
        self.inp_idle.setSingleStep(0.5)
        self.inp_idle.setSuffix(" с")
        self.inp_idle.setValue(float(inp.get("idle_sec", 2.5)))
        f_inp.addRow("Пауза без ввода до перевода", self.inp_idle)
        lay.addWidget(gb_inp)

        # --- сервер
        gb_srv = QGroupBox("Локальный сервер (llama.cpp)")
        f_srv = QFormLayout(gb_srv)
        s = cfg.data["server"]
        self.model = QComboBox()
        self.model.setEditable(True)
        models = _models_in_dir()
        self.model.addItems(models or [s["model"]])
        self.model.setCurrentText(s["model"])
        f_srv.addRow("Модель (GGUF)", self.model)

        self.mmproj = QComboBox()
        self.mmproj.setEditable(True)
        mms = _mmproj_in_dir()
        self.mmproj.addItems(mms or [s["mmproj"]])
        self.mmproj.setCurrentText(s["mmproj"])
        f_srv.addRow("Vision-веса (mmproj)", self.mmproj)

        self.ctx = QSpinBox()
        self.ctx.setRange(2048, 32768)
        self.ctx.setSingleStep(1024)
        self.ctx.setValue(int(s["ctx_size"]))
        f_srv.addRow("Размер контекста", self.ctx)

        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(int(s["port"]))
        f_srv.addRow("Порт", self.port)

        self.autostart = QCheckBox("Запускать сервер вместе с приложением")
        self.autostart.setChecked(bool(s["autostart"]))
        f_srv.addRow("", self.autostart)
        lay.addWidget(gb_srv)

        # --- внешний вид
        gb_ui = QGroupBox("Внешний вид")
        f_ui = QFormLayout(gb_ui)
        ui = cfg.data["ui"]
        self.font_size = QSpinBox()
        self.font_size.setRange(9, 28)
        self.font_size.setValue(int(ui["font_size"]))
        f_ui.addRow("Размер шрифта", self.font_size)

        self.opacity = QDoubleSpinBox()
        self.opacity.setRange(0.5, 1.0)
        self.opacity.setSingleStep(0.05)
        self.opacity.setValue(float(ui["opacity"]))
        f_ui.addRow("Непрозрачность карточки", self.opacity)

        self.max_w = QSpinBox()
        self.max_w.setRange(280, 1200)
        self.max_w.setValue(int(ui["max_width_px"]))
        f_ui.addRow("Макс. ширина, px", self.max_w)

        self.img_side = QSpinBox()
        self.img_side.setRange(512, 2048)
        self.img_side.setSingleStep(128)
        self.img_side.setValue(int(ui["image_max_side"]))
        f_ui.addRow("Макс. сторона скриншота", self.img_side)

        self.auto_close = QSpinBox()
        self.auto_close.setRange(0, 120)
        self.auto_close.setSuffix(" с")
        self.auto_close.setValue(int(ui.get("auto_close_sec", 0)))
        f_ui.addRow("Автозакрытие (0 = нет)", self.auto_close)
        lay.addWidget(gb_ui)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def accept(self) -> None:
        d = self.cfg.data
        d["target_lang"] = self.lang.currentText().strip() or "Russian"
        d["backend"] = self.backend.currentData()
        d["hotkeys"].update({
            "selected_text": self.hk_sel.text().strip().lower(),
            "screen_region": self.hk_reg.text().strip().lower(),
            "clipboard": self.hk_clip.text().strip().lower(),
            "input_toggle": self.hk_input.text().strip().lower(),
        })
        d.setdefault("input", {})
        d["input"].update({
            "target_lang": self.inp_lang.currentText().strip() or "English",
            "idle_sec": self.inp_idle.value(),
        })
        d["server"].update({
            "model": self.model.currentText().strip(),
            "mmproj": self.mmproj.currentText().strip(),
            "ctx_size": self.ctx.value(),
            "port": self.port.value(),
            "autostart": self.autostart.isChecked(),
        })
        d["ui"].update({
            "font_size": self.font_size.value(),
            "opacity": self.opacity.value(),
            "max_width_px": self.max_w.value(),
            "image_max_side": self.img_side.value(),
            "auto_close_sec": self.auto_close.value(),
        })
        self.cfg.save()
        super().accept()
