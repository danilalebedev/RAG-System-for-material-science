from __future__ import annotations

import argparse
import importlib.util
import socket
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Streamlit literature-search demo app.")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--address", default="0.0.0.0")
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


def main() -> int:
    args = parse_args()
    if importlib.util.find_spec("streamlit") is None:
        print("Streamlit is not installed. Run: .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt")
        return 1
    root = Path(__file__).resolve().parents[1]
    app_path = root / "app" / "ui" / "demo_app.py"
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.port",
        str(args.port),
        "--server.address",
        args.address,
    ]
    print("Demo URLs:")
    for url in local_urls(args.port):
        print(f"  {url}")
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
