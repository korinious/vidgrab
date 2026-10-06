"""Find which processes hold a file open, via the Windows Restart Manager API.

Used only for logging when a file stays locked (WinError 32). Returns an empty list on
other platforms or if the API fails; it must never raise.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

_ERROR_MORE_DATA = 234
_CCH_RM_SESSION_KEY = 32
_CCH_RM_MAX_APP_NAME = 255
_CCH_RM_MAX_SVC_NAME = 63


def lock_holders(path: Path) -> list[str]:
    """Return "AppName (pid N)" for each process holding ``path``. Windows only."""
    if os.name != "nt":
        return []
    try:
        return _rm_get_list(str(path))
    except Exception:
        log.debug("Restart Manager lookup failed for %s", path, exc_info=True)
        return []


def _rm_get_list(path: str) -> list[str]:
    import ctypes
    from ctypes import wintypes

    class RM_UNIQUE_PROCESS(ctypes.Structure):
        _fields_ = [("dwProcessId", wintypes.DWORD), ("ProcessStartTime", wintypes.FILETIME)]

    class RM_PROCESS_INFO(ctypes.Structure):
        _fields_ = [
            ("Process", RM_UNIQUE_PROCESS),
            ("strAppName", wintypes.WCHAR * (_CCH_RM_MAX_APP_NAME + 1)),
            ("strServiceShortName", wintypes.WCHAR * (_CCH_RM_MAX_SVC_NAME + 1)),
            ("ApplicationType", ctypes.c_int),
            ("AppStatus", wintypes.ULONG),
            ("TSSessionId", wintypes.DWORD),
            ("bRestartable", wintypes.BOOL),
        ]

    rstrtmgr = ctypes.WinDLL("rstrtmgr")
    session = wintypes.DWORD()
    key = ctypes.create_unicode_buffer(_CCH_RM_SESSION_KEY + 1)
    if rstrtmgr.RmStartSession(ctypes.byref(session), 0, key) != 0:
        return []
    try:
        files = (wintypes.LPCWSTR * 1)(path)
        if rstrtmgr.RmRegisterResources(session, 1, files, 0, None, 0, None) != 0:
            return []
        needed = wintypes.UINT(0)
        count = wintypes.UINT(0)
        reasons = wintypes.DWORD()
        rc = rstrtmgr.RmGetList(
            session, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reasons)
        )
        if rc == 0:
            return []  # nobody holds it
        if rc != _ERROR_MORE_DATA:
            return []
        infos = (RM_PROCESS_INFO * needed.value)()
        count = wintypes.UINT(needed.value)
        rc = rstrtmgr.RmGetList(
            session, ctypes.byref(needed), ctypes.byref(count), infos, ctypes.byref(reasons)
        )
        if rc != 0:
            return []
        return [
            f"{infos[i].strAppName or '?'} (pid {infos[i].Process.dwProcessId})"
            for i in range(count.value)
        ]
    finally:
        rstrtmgr.RmEndSession(session)
