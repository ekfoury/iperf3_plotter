from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


class ManifestError(ValueError):
    """Raised when an experiment manifest cannot be read."""


def load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    """Load run metadata from a JSON or CSV manifest."""

    path = Path(path)
    if path.suffix.lower() == ".json":
        records = _load_json_manifest(path)
    elif path.suffix.lower() == ".csv":
        records = _load_csv_manifest(path)
    else:
        raise ManifestError("Manifest must be a .json or .csv file")

    metadata: dict[str, dict[str, Any]] = {}
    for record in records:
        file_value = record.get("file") or record.get("path") or record.get("source_file")
        if not file_value:
            raise ManifestError("Each manifest row must include a file/path/source_file field")
        file_path = Path(str(file_value))
        if not file_path.is_absolute():
            file_path = (path.parent / file_path).resolve()
        clean_record = {key: _coerce(value) for key, value in record.items() if key not in {"file", "path"}}
        metadata[str(file_path)] = clean_record
        metadata[file_path.name] = clean_record
        metadata[file_path.as_posix()] = clean_record
    return metadata


def metadata_for_path(metadata: dict[str, dict[str, Any]] | None, path: Path) -> dict[str, Any]:
    if not metadata:
        return {}
    resolved = Path(path).resolve()
    return (
        metadata.get(str(resolved))
        or metadata.get(resolved.as_posix())
        or metadata.get(resolved.name)
        or metadata.get(str(path))
        or {}
    )


def _load_json_manifest(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{path} is not valid JSON: {exc}") from exc

    if isinstance(data, list):
        records = data
    elif isinstance(data, dict) and isinstance(data.get("runs"), list):
        records = data["runs"]
    else:
        raise ManifestError("JSON manifest must be a list or an object with a 'runs' list")

    if not all(isinstance(record, dict) for record in records):
        raise ManifestError("Manifest run entries must be objects")
    return records


def _load_csv_manifest(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def _coerce(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if stripped == "":
        return None
    lowered = stripped.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        if "." in stripped:
            return float(stripped)
        return int(stripped)
    except ValueError:
        return stripped

