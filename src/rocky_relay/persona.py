from __future__ import annotations

import re
import subprocess
from pathlib import Path


def apply_persona(text: str, persona: str, rocky_say_path: Path) -> str:
    if persona == "none":
        return text
    if persona == "rocky_basic":
        return rocky_basic(text)
    if persona == "rocky_say":
        return rocky_say_transform(text, rocky_say_path)
    raise ValueError(f"Unknown persona: {persona}")


def rocky_basic(text: str) -> str:
    """Tiny local fallback, not a full clone of the Rocky script."""
    stripped = text.strip()
    if not stripped:
        return stripped

    replacements = {
        r"\bI do not understand\b": "No understand",
        r"\bI don't understand\b": "No understand",
        r"\bamazing\b": "amaze amaze amaze",
        r"\bgreat\b": "good good good",
        r"\bterrible\b": "bad bad bad",
        r"\breally\b": "very",
    }
    result = stripped
    for pattern, replacement in replacements.items():
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    result = re.sub(r"\b(a|an|the)\b\s*", "", result, flags=re.IGNORECASE)
    if result.endswith("?") and "question" not in result.lower():
        result = result[:-1].rstrip() + ", question?"
    return result[:1].upper() + result[1:]


def rocky_say_transform(text: str, rocky_say_path: Path) -> str:
    if not rocky_say_path.exists():
        raise FileNotFoundError(f"rocky_say not found: {rocky_say_path}")

    result = subprocess.run(
        ["python3", str(rocky_say_path), "--transform-only", text],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"rocky_say transform failed: {detail}")
    return result.stdout.strip()
