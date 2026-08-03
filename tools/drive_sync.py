#!/usr/bin/env python3
"""Build a provenance-preserving manifest of the Da Vinci Drive corpus.

The script reads Google Drive through a service account, recursively inventories
one authorised folder, and writes machine-readable JSON. It does not move,
rename, overwrite, download, or delete Drive content.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
FOLDER_MIME = "application/vnd.google-apps.folder"


def credentials_from_env() -> service_account.Credentials:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set")
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON") from exc
    return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)


def list_children(service: Any, parent_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        response = (
            service.files()
            .list(
                q=f"'{parent_id}' in parents and trashed = false",
                spaces="drive",
                fields=(
                    "nextPageToken,files(id,name,mimeType,size,createdTime,modifiedTime,"
                    "md5Checksum,sha1Checksum,sha256Checksum,webViewLink,parents)"
                ),
                pageSize=1000,
                pageToken=token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        items.extend(response.get("files", []))
        token = response.get("nextPageToken")
        if not token:
            return items


def walk(service: Any, folder_id: str, path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in sorted(list_children(service, folder_id), key=lambda x: x["name"].lower()):
        current_path = f"{path}/{item['name']}"
        row = {
            "source_path": current_path,
            "file_id": item.get("id"),
            "file_name": item.get("name"),
            "mime_type": item.get("mimeType"),
            "size_bytes": int(item["size"]) if item.get("size") else None,
            "created_time": item.get("createdTime"),
            "modified_time": item.get("modifiedTime"),
            "md5": item.get("md5Checksum"),
            "sha1": item.get("sha1Checksum"),
            "sha256": item.get("sha256Checksum"),
            "web_view_link": item.get("webViewLink"),
            "is_folder": item.get("mimeType") == FOLDER_MIME,
            "codex_or_folio": None,
            "topic": None,
            "evidence_status": "UNREVIEWED",
            "duplicate_status": "UNCHECKED",
            "destination_category": None,
        }
        rows.append(row)
        if row["is_folder"]:
            rows.extend(walk(service, item["id"], current_path))
    return rows


def main() -> int:
    folder_id = os.environ.get("DRIVE_CORPUS_FOLDER_ID", "").strip()
    if not folder_id:
        raise RuntimeError("DRIVE_CORPUS_FOLDER_ID is not set")

    output = Path(os.environ.get("DRIVE_MANIFEST_OUTPUT", "manifests/drive-corpus-manifest.json"))
    output.parent.mkdir(parents=True, exist_ok=True)

    service = build("drive", "v3", credentials=credentials_from_env(), cache_discovery=False)
    rows = walk(service, folder_id, "DA VINCI PROJECT — CONSOLIDATED CORPUS")
    payload = {
        "schema_version": 1,
        "root_folder_id": folder_id,
        "item_count": len(rows),
        "items": rows,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} Drive entries to {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"Drive sync failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
