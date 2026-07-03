from __future__ import annotations

import time
from collections import deque
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode

import requests
from tqdm import tqdm

from app.io_utils import safe_relative_path


YANDEX_PUBLIC_RESOURCES_API = "https://cloud-api.yandex.net/v1/disk/public/resources"


def _get_public_resource(
    public_key: str,
    path: str = "/",
    limit: int = 1000,
    timeout: int = 60,
    max_retries: int = 5,
) -> dict[str, Any]:
    params = {"public_key": public_key, "path": path, "limit": limit}
    url = f"{YANDEX_PUBLIC_RESOURCES_API}?{urlencode(params)}"
    for attempt in range(max_retries + 1):
        response = requests.get(url, timeout=timeout)
        if response.status_code == 429 and attempt < max_retries:
            retry_after = response.headers.get("Retry-After")
            sleep_s = float(retry_after) if retry_after and retry_after.isdigit() else min(2 ** attempt, 30)
            time.sleep(sleep_s)
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError("unreachable retry state")


def list_public_files(public_key: str, sleep_s: float = 0.03) -> list[dict[str, Any]]:
    queue: deque[str] = deque(["/"])
    seen: set[str] = set()
    files: list[dict[str, Any]] = []

    while queue:
        path = queue.popleft()
        if path in seen:
            continue
        seen.add(path)
        data = _get_public_resource(public_key, path=path)
        for item in data.get("_embedded", {}).get("items", []):
            item_type = item.get("type")
            if item_type == "dir":
                queue.append(item["path"])
            elif item_type == "file":
                files.append(normalize_public_file(item))
        time.sleep(sleep_s)
    return files


def normalize_public_file(item: dict[str, Any]) -> dict[str, Any]:
    path = item.get("path", "")
    suffix = Path(item.get("name", "")).suffix.lower()
    parts = [part for part in path.split("/") if part]
    top_folder = parts[1] if len(parts) > 1 else ""
    return {
        "name": item.get("name"),
        "path": path,
        "relative_path": str(safe_relative_path(path)),
        "top_folder": top_folder,
        "type": item.get("type"),
        "size": int(item.get("size") or 0),
        "size_mb": round(int(item.get("size") or 0) / 1024 / 1024, 3),
        "mime_type": item.get("mime_type"),
        "extension": suffix,
        "download_url": item.get("file"),
        "created": item.get("created"),
        "modified": item.get("modified"),
    }


def select_seed_files(
    files: Iterable[dict[str, Any]],
    max_files: int,
    preferred_extensions: Iterable[str],
    max_file_size_mb: float,
) -> list[dict[str, Any]]:
    preferred = set(preferred_extensions)
    max_bytes = int(max_file_size_mb * 1024 * 1024)
    selected: list[dict[str, Any]] = []
    candidates = [
        row
        for row in files
        if row.get("extension") in preferred
        and row.get("download_url")
        and int(row.get("size") or 0) <= max_bytes
    ]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        grouped[row.get("top_folder") or "<root>"].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: (extension_rank(row.get("extension", "")), int(row.get("size") or 0)))

    keys = sorted(grouped)
    while len(selected) < max_files and any(grouped.values()):
        for key in keys:
            if grouped[key]:
                selected.append(grouped[key].pop(0))
                if len(selected) >= max_files:
                    break
    return selected


def extension_rank(extension: str) -> int:
    order = {".pdf": 0, ".docx": 1, ".docm": 2, ".pptx": 3, ".xlsx": 4, ".xls": 5}
    return order.get(extension, 99)


def refresh_download_url(public_key: str, public_path: str) -> str:
    data = _get_public_resource(public_key, path=public_path)
    return data.get("file") or ""


def download_files(
    files: list[dict[str, Any]],
    output_root: Path,
    overwrite: bool = False,
    public_key: str | None = None,
) -> list[dict[str, Any]]:
    output_root.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    for row in tqdm(files, desc="download", unit="file"):
        rel = Path(row["relative_path"])
        target = output_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        status = "skipped_exists"
        error = ""
        if overwrite or not target.exists():
            try:
                download_url = row.get("download_url") or ""
                try:
                    stream_to_file(download_url, target)
                except requests.HTTPError as exc:
                    if exc.response is not None and exc.response.status_code == 410 and public_key:
                        download_url = refresh_download_url(public_key, row["path"])
                        stream_to_file(download_url, target)
                    else:
                        raise
                status = "downloaded"
            except Exception as exc:  # noqa: BLE001
                status = "failed"
                error = str(exc)
        manifest.append({**row, "local_path": str(target), "download_status": status, "download_error": error})
    return manifest


def stream_to_file(download_url: str, target: Path) -> None:
    if not download_url:
        raise ValueError("missing download_url")
    with requests.get(download_url, stream=True, timeout=180) as response:
        response.raise_for_status()
        tmp = target.with_suffix(target.suffix + ".part")
        with tmp.open("wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
        tmp.replace(target)
