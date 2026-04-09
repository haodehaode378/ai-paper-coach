import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parent
API_DIR = ROOT / "services" / "api"
WEB_PORT = 5500
API_PORT = 8000


def _python_exe() -> str:
    return sys.executable


def _check_dependency(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def _preflight() -> None:
    required = ["fastapi", "uvicorn", "requests"]
    missing = [name for name in required if not _check_dependency(name)]
    if missing:
        joined = ", ".join(missing)
        print(f"Missing Python packages: {joined}")
        print(rf"Run: cd {API_DIR} && pip install -r requirements.txt")
        raise SystemExit(1)

    if not (_check_dependency("pypdf") or _check_dependency("PyPDF2")):
        print("Warning: neither pypdf nor PyPDF2 is installed.")
        print("PDF full-text extraction will fail until one of them is available.")
        print(rf"Run: cd {API_DIR} && pip install -r requirements.txt")


def _truthy_env(name: str, default: str = "0") -> bool:
    value = os.getenv(name, default).strip().lower()
    return value in {"1", "true", "yes", "on"}


def main() -> int:
    _preflight()
    python_exe = _python_exe()
    reload_enabled = _truthy_env("APC_RELOAD", "0")

    api_cmd = [
        python_exe,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        str(API_PORT),
    ]

    if reload_enabled:
        api_cmd.append("--reload")

    web_cmd = [
        python_exe,
        "-m",
        "http.server",
        str(WEB_PORT),
        "--bind",
        "127.0.0.1",
    ]

    print("[1/3] Starting API server on http://127.0.0.1:8000")
    print(f"      Reload mode: {'ON' if reload_enabled else 'OFF'} (set APC_RELOAD=1 to enable)")
    api_proc = subprocess.Popen(api_cmd, cwd=str(API_DIR))

    print("[2/3] Starting web static server on http://127.0.0.1:5500")
    web_proc = subprocess.Popen(web_cmd, cwd=str(ROOT))

    url = f"http://127.0.0.1:{WEB_PORT}/apps/web/index.html"
    time.sleep(2)
    print(f"[3/3] Opening browser: {url}")
    webbrowser.open(url)

    print("\nPress Ctrl+C to stop both servers.")
    try:
        while True:
            if api_proc.poll() is not None:
                print("API server exited unexpectedly.")
                break
            if web_proc.poll() is not None:
                print("Web server exited unexpectedly.")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping servers...")
    finally:
        for proc in (api_proc, web_proc):
            if proc.poll() is None:
                proc.terminate()
        for proc in (api_proc, web_proc):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
