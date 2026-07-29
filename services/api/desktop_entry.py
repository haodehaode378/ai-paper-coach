from __future__ import annotations

import argparse
import os
import threading
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Paper Coach desktop API")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--legacy-data-dir", type=Path)
    parser.add_argument("--parent-pid", type=int)
    parser.add_argument("--api-token", required=True)
    return parser.parse_args()


def start_parent_watchdog(parent_pid: int | None) -> None:
    if not parent_pid or os.name != "nt":
        return

    def watch() -> None:
        import ctypes

        synchronize = 0x00100000
        infinite = 0xFFFFFFFF
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(synchronize, False, parent_pid)
        if not handle:
            os._exit(0)
        try:
            kernel32.WaitForSingleObject(handle, infinite)
        finally:
            kernel32.CloseHandle(handle)
        os._exit(0)

    threading.Thread(target=watch, name="desktop-parent-watchdog", daemon=True).start()


def main() -> None:
    args = parse_args()
    data_dir = args.data_dir.expanduser().resolve()
    start_parent_watchdog(args.parent_pid)

    # These must be set before importing app modules because data paths are
    # resolved once during module import.
    os.environ["APC_DATA_DIR"] = str(data_dir)
    os.environ["APC_REQUIRE_API_KEY"] = "1"
    os.environ["APC_API_KEY"] = args.api_token
    os.environ.setdefault(
        "APC_ALLOWED_ORIGINS",
        "http://tauri.localhost,https://tauri.localhost,tauri://localhost",
    )

    from app.core.paths import migrate_legacy_data

    if args.legacy_data_dir:
        migrate_legacy_data(
            data_dir,
            legacy_root=args.legacy_data_dir.expanduser().resolve(),
        )

    import uvicorn
    from app.main import app

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=args.port,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
