"""Захват выделенного текста: эмуляция Ctrl+C + буфер обмена через win32 API."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

CF_UNICODETEXT = 13
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_C = 0x43

_kernel32 = ctypes.windll.kernel32
_user32 = ctypes.windll.user32

# обязательные прототипы: без restype ctypes режет 64-битные указатели до int
_user32.OpenClipboard.argtypes = [wt.HWND]
_user32.OpenClipboard.restype = wt.BOOL
_user32.GetClipboardData.argtypes = [wt.UINT]
_user32.GetClipboardData.restype = ctypes.c_void_p
_user32.CloseClipboard.argtypes = []
_user32.CloseClipboard.restype = wt.BOOL
_user32.GetClipboardSequenceNumber.argtypes = []
_user32.GetClipboardSequenceNumber.restype = wt.DWORD
_kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
_kernel32.GlobalLock.restype = ctypes.c_void_p
_kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
_kernel32.GlobalUnlock.restype = wt.BOOL
_kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
_kernel32.GlobalAlloc.restype = ctypes.c_void_p
_user32.EmptyClipboard.argtypes = []
_user32.EmptyClipboard.restype = wt.BOOL
_user32.SetClipboardData.argtypes = [wt.UINT, ctypes.c_void_p]
_user32.SetClipboardData.restype = ctypes.c_void_p

VK_A = 0x41
VK_V = 0x56


def _tap_ctrl_key(vk: int, hold: float = 0.03) -> None:
    import time
    _user32.keybd_event(VK_CONTROL, 0, 0, 0)
    _user32.keybd_event(vk, 0, 0, 0)
    time.sleep(hold)
    _user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
    _user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def press_select_all() -> None:
    _tap_ctrl_key(VK_A)


def press_copy() -> None:
    _tap_ctrl_key(VK_C)


def press_paste() -> None:
    _tap_ctrl_key(VK_V)


def set_clipboard_text(text: str) -> bool:
    if not _open_clipboard():
        return False
    try:
        _user32.EmptyClipboard()
        buf = ctypes.create_unicode_buffer(text)
        size = ctypes.sizeof(buf)
        handle = _kernel32.GlobalAlloc(0x0002, size)  # GMEM_MOVEABLE
        if not handle:
            return False
        ptr = _kernel32.GlobalLock(handle)
        if not ptr:
            return False
        ctypes.memmove(ptr, ctypes.addressof(buf), size)
        _kernel32.GlobalUnlock(handle)
        return bool(_user32.SetClipboardData(CF_UNICODETEXT, handle))
    finally:
        _user32.CloseClipboard()


def _open_clipboard(retries: int = 15) -> bool:
    for _ in range(retries):
        if _user32.OpenClipboard(None):
            return True
        import time
        time.sleep(0.02)
    return False


def get_clipboard_text() -> str | None:
    """Текущий текст буфера обмена или None."""
    if not _open_clipboard():
        return None
    try:
        handle = _user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = _kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)
        finally:
            _kernel32.GlobalUnlock(handle)
    finally:
        _user32.CloseClipboard()


def copy_selection(timeout: float = 0.7) -> str | None:
    """Жмёт Ctrl+C и ждёт появления в буфере нового текста.

    Возвращает скопированный текст либо None (ничего не выделено).
    Работает не везде: приложения с защитой от синтетического ввода
    (некоторые игры) игнорируют Ctrl+C — для них есть режим региона экрана.
    """
    import time

    seq_before = _user32.GetClipboardSequenceNumber()

    _user32.keybd_event(VK_CONTROL, 0, 0, 0)
    _user32.keybd_event(VK_C, 0, 0, 0)
    time.sleep(0.03)
    _user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
    _user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _user32.GetClipboardSequenceNumber() != seq_before:
            # буфер обновился; текст мог прийти кусками — даём дописать
            time.sleep(0.04)
            now = get_clipboard_text()
            if now is not None and now.strip():
                return now
        time.sleep(0.02)
    return None
