from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Streamlit literature-search demo app.")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--address", default="0.0.0.0")
    parser.add_argument("--background", action="store_true", help="Start Streamlit in background and return after healthcheck.")
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--no-headless", action="store_false", dest="headless")
    parser.add_argument("--restart-existing", action="store_true", default=True, help="Stop stale demo_app Streamlit processes on the selected port before starting.")
    parser.add_argument("--no-restart-existing", action="store_false", dest="restart_existing")
    parser.add_argument("--log-dir", default="logs/streamlit_demo")
    parser.add_argument("--health-timeout-seconds", type=int, default=30)
    return parser.parse_args()


def local_urls(port: int) -> list[str]:
    urls = [f"http://127.0.0.1:{port}"]
    try:
        host_name = socket.gethostname()
        for address in socket.gethostbyname_ex(host_name)[2]:
            if address and not address.startswith("127."):
                urls.append(f"http://{address}:{port}")
    except OSError:
        pass
    return list(dict.fromkeys(urls))


def streamlit_command(app_path: Path, *, port: int, address: str, headless: bool) -> list[str]:
    return [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.port",
        str(port),
        "--server.address",
        address,
        "--server.headless",
        "true" if headless else "false",
    ]


def verify_demo_import(root: Path) -> tuple[bool, str]:
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    try:
        importlib.import_module("app.ui.demo_app")
    except Exception as exc:  # noqa: BLE001 - startup gate must report any import-time failure.
        return False, f"{type(exc).__name__}: {exc}"
    return True, "ok"


def _powershell() -> str:
    return "powershell.exe"


def _normalize_commandline(value: Any) -> str:
    return str(value or "").replace("/", "\\").casefold()


def find_existing_demo_processes(*, port: int) -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    command = (
        "$ErrorActionPreference='SilentlyContinue'; "
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -like '*streamlit*' -and $_.CommandLine -like '*demo_app.py*' } | "
        "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        [_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0 or not (completed.stdout or "").strip():
        return []
    try:
        raw = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []
    rows = raw if isinstance(raw, list) else [raw]
    result: list[dict[str, Any]] = []
    port_marker = str(port)
    for row in rows:
        if not isinstance(row, dict):
            continue
        commandline = _normalize_commandline(row.get("CommandLine"))
        if "streamlit" not in commandline or "demo_app.py" not in commandline or port_marker not in commandline:
            continue
        result.append({"pid": int(row.get("ProcessId")), "commandline": row.get("CommandLine")})
    return result


def stop_processes(processes: list[dict[str, Any]]) -> None:
    if not processes:
        return
    if os.name == "nt":
        pids = ",".join(str(item["pid"]) for item in processes if item.get("pid"))
        if not pids:
            return
        command = f"Stop-Process -Id {pids} -Force -ErrorAction SilentlyContinue"
        subprocess.run([_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command], check=False)
        return
    for item in processes:
        pid = item.get("pid")
        if pid:
            subprocess.run(["kill", str(pid)], check=False)


def wait_for_http(url: str, *, timeout_seconds: int) -> tuple[bool, str]:
    deadline = time.monotonic() + max(timeout_seconds, 1)
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=3) as response:  # noqa: S310 - local demo healthcheck.
                status_code = int(getattr(response, "status", 0) or response.getcode())
            if 200 <= status_code < 500:
                return True, str(status_code)
            last_error = f"HTTP {status_code}"
        except (OSError, URLError) as exc:
            last_error = str(exc)[:200]
        time.sleep(1)
    return False, last_error or "timeout"


def print_urls(port: int) -> None:
    print("Demo URLs:")
    for url in local_urls(port):
        print(f"  {url}")


def main() -> int:
    args = parse_args()
    if importlib.util.find_spec("streamlit") is None:
        print("Streamlit is not installed. Run: .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt")
        return 1
    root = Path(__file__).resolve().parents[1]
    app_path = root / "app" / "ui" / "demo_app.py"
    import_ok, import_detail = verify_demo_import(root)
    if not import_ok:
        print(f"Demo app import failed: {import_detail}")
        return 1
    if args.restart_existing:
        existing = find_existing_demo_processes(port=args.port)
        if existing:
            print(f"Stopping {len(existing)} existing demo Streamlit process(es) on port {args.port}.")
            stop_processes(existing)
            time.sleep(1)
    command = streamlit_command(app_path, port=args.port, address=args.address, headless=args.headless)
    print_urls(args.port)
    if not args.background:
        return subprocess.run(command, check=False, cwd=root).returncode

    log_dir = (root / args.log_dir).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / "stdout.log"
    stderr_path = log_dir / "stderr.log"
    with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
        process = subprocess.Popen(command, cwd=root, stdout=stdout, stderr=stderr)
    health_url = f"http://127.0.0.1:{args.port}/"
    ok, detail = wait_for_http(health_url, timeout_seconds=args.health_timeout_seconds)
    print(f"Launcher PID: {process.pid}")
    print(f"Logs: {stdout_path} | {stderr_path}")
    if not ok:
        print(f"Healthcheck failed for {health_url}: {detail}")
        return 1
    print(f"Healthcheck OK: {health_url} ({detail})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
