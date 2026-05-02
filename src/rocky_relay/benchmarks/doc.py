from __future__ import annotations

from pathlib import Path


def append_markdown_table_row(path: Path, section_label: str, row: str) -> None:
    if not path.exists():
        path.write_text(row, encoding="utf-8")
        return

    text = path.read_text(encoding="utf-8")
    section_start = text.find(section_label)
    if section_start == -1:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(row)
        return

    lines = text.splitlines(keepends=True)
    char_count = 0
    section_line_index = 0
    for index, line in enumerate(lines):
        if char_count <= section_start < char_count + len(line):
            section_line_index = index
            break
        char_count += len(line)

    table_start_index: int | None = None
    for index in range(section_line_index + 1, len(lines)):
        stripped = lines[index].lstrip()
        if stripped.startswith("|"):
            table_start_index = index
            break
        if lines[index].startswith("## ") or lines[index].startswith("# "):
            break

    if table_start_index is None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(row)
        return

    table_end_index = table_start_index
    for index in range(table_start_index, len(lines)):
        if not lines[index].lstrip().startswith("|"):
            break
        table_end_index = index + 1

    insertion_at = sum(len(line) for line in lines[:table_end_index])
    prefix = text[:insertion_at]
    suffix = text[insertion_at:]
    separator = "" if prefix.endswith("\n") else "\n"
    path.write_text(f"{prefix}{separator}{row}{suffix}", encoding="utf-8")
