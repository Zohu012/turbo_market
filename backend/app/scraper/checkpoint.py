"""
Shared checkpoint I/O for the scraper.

Layout of `backend/scraper_checkpoint.txt`:
    listing_full:Chevrolet:75
    listing_make:BMW:12
    listing_full_parallel:Hyundai:3
    listing_make_parallel:Audi:1
    details_full:11761
    details_full_make:Chevrolet:11761
    details_update:5234
    details_full_parallel:18002
    details_full_make_parallel:BMW:18002
    details_update_parallel:7400

Each line is `key:value`. Listing keys store `make[:page]`; details keys store
the highest fully-completed `vehicle.id`. Each UI button gets its own key so
serial and parallel runs of the "same" mode track progress independently
(starting Details Full ⚡ won't disturb the Details Full serial checkpoint).
"""
from pathlib import Path
from typing import Optional


CHECKPOINT_FILE = Path(__file__).parent.parent.parent / "scraper_checkpoint.txt"

# Stable on-disk order — keeps diffs of the file readable. One key per UI
# button: serial keys first, then their parallel (⚡) counterparts.
_CHECKPOINT_KEYS = (
    "listing_full",
    "listing_make",
    "listing_full_parallel",
    "listing_make_parallel",
    "details_full",
    "details_full_make",
    "details_update",
    "details_full_parallel",
    "details_full_make_parallel",
    "details_update_parallel",
)


def read_checkpoint() -> dict[str, str]:
    """Parse checkpoint file into a key→value dict."""
    result: dict[str, str] = {}
    if not CHECKPOINT_FILE.exists():
        return result
    for raw in CHECKPOINT_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        if key in _CHECKPOINT_KEYS:
            result[key] = value
    return result


def write_checkpoint(data: dict[str, str]) -> None:
    parts = [f"{k}:{data[k]}" for k in _CHECKPOINT_KEYS if k in data and data[k]]
    if parts:
        CHECKPOINT_FILE.write_text("\n".join(parts), encoding="utf-8")
    elif CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()


def set_checkpoint(key: str, value: str) -> None:
    data = read_checkpoint()
    data[key] = value
    write_checkpoint(data)


def clear_checkpoint(key: str) -> None:
    data = read_checkpoint()
    data.pop(key, None)
    write_checkpoint(data)


def load_listing_progress(key: str) -> tuple[Optional[str], int]:
    """Decode `make_name:page_num` (or just `make_name`) → (make, page)."""
    val = read_checkpoint().get(key, "")
    if not val:
        return None, 1
    idx = val.rfind(":")
    if idx > 0 and val[idx + 1:].isdigit():
        return val[:idx], int(val[idx + 1:])
    return val, 1


def save_listing_progress(key: str, make_name: str, page_num: Optional[int] = None) -> None:
    val = f"{make_name}:{page_num}" if page_num else make_name
    set_checkpoint(key, val)


def load_details_progress(key: str) -> Optional[int]:
    val = read_checkpoint().get(key, "")
    return int(val) if val.isdigit() else None


def save_details_progress(key: str, vehicle_id: int) -> None:
    set_checkpoint(key, str(vehicle_id))


# ── Failed-rows file (per-mode retry queue) ───────────────────────────────

def failed_ids_path(mode_key: str) -> Path:
    """Per-mode failed-row id file.

    Format: one int per line. Workers in the parallel runner append to this
    file when a row fails to load; the next run loads it and re-prepends the
    ids so they get one more attempt before resuming forward progress.
    """
    return CHECKPOINT_FILE.parent / f"scraper_failed_{mode_key}.txt"


def load_failed_ids(mode_key: str) -> list[int]:
    p = failed_ids_path(mode_key)
    if not p.exists():
        return []
    out: list[int] = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.isdigit():
            out.append(int(line))
    return out


def append_failed_ids(mode_key: str, ids: list[int]) -> None:
    if not ids:
        return
    p = failed_ids_path(mode_key)
    with p.open("a", encoding="utf-8") as f:
        for vid in ids:
            f.write(f"{vid}\n")


def clear_failed_ids(mode_key: str) -> None:
    p = failed_ids_path(mode_key)
    if p.exists():
        p.unlink()
