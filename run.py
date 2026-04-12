import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
API_DIR = ROOT / "services" / "api"
WEB_DIR = ROOT / "apps" / "web"
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


def _find_npm() -> str | None:
    return shutil.which("npm") or shutil.which("npm.cmd")


def _preflight() -> str:
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

    npm_cmd = _find_npm()
    if not npm_cmd:
        print("Missing npm. Install Node.js 18+ to run the Vue frontend.")
        raise SystemExit(1)

    if not (WEB_DIR / "node_modules").exists():
        print("Missing frontend dependencies.")
        print(rf"Run: cd {WEB_DIR} && npm install")
        raise SystemExit(1)

    return npm_cmd


def _truthy_env(name: str, default: str = "0") -> bool:
    value = os.getenv(name, default).strip().lower()
    return value in {"1", "true", "yes", "on"}


def main() -> int:
    npm_cmd = _preflight()
    python_exe = _python_exe()
    reload_enabled = _truthy_env("APC_RELOAD", "1")

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
        npm_cmd,
        "run",
        "dev",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        str(WEB_PORT),
    ]

    print("[1/3] Starting API server on http://127.0.0.1:8000")
    print(f"      Reload mode: {'ON' if reload_enabled else 'OFF'} (set APC_RELOAD=0 to disable)")
    api_proc = subprocess.Popen(api_cmd, cwd=str(API_DIR))

    print(f"[2/3] Starting Vue dev server on http://127.0.0.1:{WEB_PORT}")
    try:
        web_proc = subprocess.Popen(web_cmd, cwd=str(WEB_DIR))
    except Exception:
        if api_proc.poll() is None:
            api_proc.terminate()
        raise

    url = f"http://127.0.0.1:{WEB_PORT}"
    time.sleep(3)
    print(f"[3/3] Frontend ready: {url}")

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