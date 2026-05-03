from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from rocky_relay.config import Config, load_config


def migrate_legacy_logs(config: Config, *, gap_minutes: float = 10.0) -> dict[str, int]:
    legacy_turns = config.resolve(config.log_dir) / "turns.jsonl"
    legacy_recorded = config.resolve(config.log_dir) / "recorded_turns.jsonl"
    conversation_turns = config.resolve(config.conversation_log_dir) / "turns.jsonl"
    conversation_recorded = config.resolve(config.conversation_log_dir) / "recorded_turns.jsonl"
    benchmark_turns = config.resolve(config.benchmark_log_dir) / "turns.jsonl"

    recorded_records = _read_jsonl(legacy_recorded)
    recorded_records = _assign_conversation_ids(recorded_records, gap_minutes=gap_minutes)
    recorded_conversation_ids = {
        str(record.get("request_id")): str(record.get("conversation_id"))
        for record in recorded_records
        if record.get("request_id") and record.get("conversation_id")
    }

    conversation_recorded_merged = _merge_jsonl(
        conversation_recorded,
        recorded_records,
        key_fields=("request_id",),
    )

    conversation_turn_records: list[dict[str, Any]] = []
    benchmark_turn_records: list[dict[str, Any]] = []
    for record in _read_jsonl(legacy_turns):
        request_id = str(record.get("request_id", ""))
        if request_id in recorded_conversation_ids:
            record = {**record, "conversation_id": recorded_conversation_ids[request_id]}
            conversation_turn_records.append(record)
        elif _looks_like_benchmark(record):
            benchmark_turn_records.append(record)
        else:
            conversation_turn_records.append(record)

    conversation_turns_merged = _merge_jsonl(
        conversation_turns,
        conversation_turn_records,
        key_fields=("request_id",),
    )
    benchmark_turns_merged = _merge_jsonl(
        benchmark_turns,
        benchmark_turn_records,
        key_fields=("request_id",),
    )

    return {
        "conversation_recorded_added": conversation_recorded_merged["added"],
        "conversation_recorded_updated": conversation_recorded_merged["updated"],
        "conversation_turns_added": conversation_turns_merged["added"],
        "conversation_turns_updated": conversation_turns_merged["updated"],
        "benchmark_turns_added": benchmark_turns_merged["added"],
        "benchmark_turns_updated": benchmark_turns_merged["updated"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate legacy root JSONL logs into separated log folders.")
    parser.add_argument("--config", help="Path to config.json.")
    parser.add_argument(
        "--gap-minutes",
        type=float,
        default=10.0,
        help="Maximum gap between recorded turns to treat them as one conversation.",
    )
    args = parser.parse_args()
    result = migrate_legacy_logs(load_config(args.config), gap_minutes=args.gap_minutes)
    for key, value in result.items():
        print(f"{key}: {value}")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        records.append(json.loads(line))
    return records


def _merge_jsonl(
    path: Path,
    records: list[dict[str, Any]],
    *,
    key_fields: tuple[str, ...],
) -> dict[str, int]:
    existing_records = _read_jsonl(path)
    existing_indexes = {
        _record_key(record, key_fields): index
        for index, record in enumerate(existing_records)
    }
    added = 0
    updated = 0

    for record in records:
        key = _record_key(record, key_fields)
        if key not in existing_indexes:
            existing_indexes[key] = len(existing_records)
            existing_records.append(record)
            added += 1
            continue

        existing = existing_records[existing_indexes[key]]
        merged = _merge_missing_fields(existing, record)
        if merged != existing:
            existing_records[existing_indexes[key]] = merged
            updated += 1

    if added == 0 and updated == 0:
        return {"added": 0, "updated": 0}

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in existing_records:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")
    return {"added": added, "updated": updated}


def _merge_missing_fields(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in incoming.items():
        existing_value = merged.get(key)
        if key not in merged or existing_value is None or existing_value == "":
            merged[key] = value
    return merged


def _assign_conversation_ids(
    records: list[dict[str, Any]],
    *,
    gap_minutes: float,
) -> list[dict[str, Any]]:
    grouped_records: list[dict[str, Any]] = []
    current_conversation_id: str | None = None
    previous_timestamp: datetime | None = None
    gap_seconds = gap_minutes * 60

    for record in records:
        timestamp = _parse_timestamp(str(record.get("created_at", "")))
        if (
            current_conversation_id is None
            or previous_timestamp is None
            or timestamp is None
            or (timestamp - previous_timestamp).total_seconds() > gap_seconds
        ):
            current_conversation_id = str(
                record.get("conversation_id") or f"conv_{record.get('request_id', 'unknown')}"
            )

        if not record.get("conversation_id"):
            record = {**record, "conversation_id": current_conversation_id}
        grouped_records.append(record)
        if timestamp is not None:
            previous_timestamp = timestamp

    return grouped_records


def _looks_like_benchmark(record: dict[str, Any]) -> bool:
    input_audio_path = str(record.get("input_audio_path", ""))
    input_text = str(record.get("input_text", "")).lower()
    if "benchmark" in input_text:
        return True
    if "/samples/" in input_audio_path or input_audio_path.startswith("samples/"):
        return True
    if "rocky-direct-test.wav" in input_audio_path:
        return True
    if record.get("llm_backend") == "echo" and record.get("tts_backend") in {"silent", "tone"}:
        return True
    return False


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _record_key(record: dict[str, Any], key_fields: tuple[str, ...]) -> tuple[object, ...]:
    return tuple(record.get(field) for field in key_fields)


if __name__ == "__main__":
    main()
