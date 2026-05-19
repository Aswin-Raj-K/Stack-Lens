"""Register the .sltrace file type with the Windows shell. No-op on non-Windows."""
import sys


def register_sltrace_association(icon_path: str) -> None:
    """Write HKCU registry entries so .sltrace files show the app icon in Explorer.

    Silently does nothing on non-Windows or when the icon file is missing.
    """
    if sys.platform != "win32":
        return
    if not _icon_exists(icon_path):
        return
    try:
        _write_registry(icon_path)
        _notify_shell()
    except Exception:
        pass  # Never crash the app over a cosmetic registration


def _icon_exists(icon_path: str) -> bool:
    import os
    return os.path.isfile(icon_path)


def _write_registry(icon_path: str) -> None:
    import winreg
    prog_id = "StackLens.Trace"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\.sltrace") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, prog_id)
        winreg.SetValueEx(k, "Content Type", 0, winreg.REG_SZ, "application/x-sltrace")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{prog_id}") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "Stack-Lens Trace File")
    with winreg.CreateKey(
        winreg.HKEY_CURRENT_USER, rf"Software\Classes\{prog_id}\DefaultIcon"
    ) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f"{icon_path},0")


def _notify_shell() -> None:
    import ctypes
    # SHCNE_ASSOCCHANGED = 0x08000000, SHCNF_IDLIST = 0x0000
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
