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
    details_null_fix:9100
    details_full_parallel:18002
    details_full_make_parallel:BMW:18002
    details_update_parallel:7400
    details_null_fix_parallel:9100

Each line is `key:value`. Listing keys store `make[:page]`; details keys store
the highest fully-completed `vehicle.id`. Each UI button gets its own key so
serial and parallel runs of the "same" mode track progress independently
(starting Details Full ⚡ won't disturb the Details Full serial checkpoint).

Listing parallel runs additionally write a sidecar at
`backend/scraper_progress_<key>.txt` recording per-make status across all 8
workers — see `make_progress_path` and friends below. The single-key
breadcrumb in `scraper_checkpoint.txt` is last-writer-wins across workers, so
it is no longer the source of truth for resume; it stays as a human-visible
"last completed make" hint.
"""
import os
import threading
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
    "details_null_fix",
    "details_full_parallel",
    "details_full_make_parallel",
    "details_update_parallel",
    "details_null_fix_parallel",
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
    # Wipe the per-make sidecar too if this key has one (no-op for serial
    # keys that never wrote one). Keeps the UI "Clear" button single-action.
    p = CHECKPOINT_FILE.parent / f"scraper_progress_{key}.txt"
    if p.exists():
        p.unlink()
    tmp = p.with_suffix(p.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()


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


# ── Per-make progress sidecar (parallel listing runs) ─────────────────────
#
# When 8 workers run in parallel, the single-key checkpoint is last-writer-
# wins — 7 in-flight makes leave no trace if all workers crash together
# (e.g. Cloudflare blocks every tab). The sidecar below records each make's
# state independently so the next run can skip done makes, resume in-flight
# makes from the right page, and start fresh on makes that never ran.
#
# Format: one `name:status[:next_page]` line per make.
#   Audi:in_flight:13     ← pages 1..12 fully committed, resume from page 13
#   BMW:done              ← finished cleanly
#   (absent)              ← never started, run from page 1


def make_progress_path(mode_key: str) -> Path:
    return CHECKPOINT_FILE.parent / f"scraper_progress_{mode_key}.txt"


def read_make_progress(mode_key: str) -> dict[str, tuple[str, int]]:
    """Parse sidecar into `{make_name: (status, next_page)}`.

    `status` is `"done"` or `"in_flight"`. `next_page` is the page to resume
    from (1 for done — unused). Malformed lines are skipped silently.
    """
    p = make_progress_path(mode_key)
    if not p.exists():
        return {}
    out: dict[str, tuple[str, int]] = {}
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or ":" not in line:
            continue
        parts = line.split(":")
        # Make names can contain colons (e.g. "GWM (Great Wall Motor)" — none
        # currently, but be defensive). Status is always one of two literals
        # at a known index from the right.
        if len(parts) >= 3 and parts[-2] == "in_flight" and parts[-1].isdigit():
            name = ":".join(parts[:-2])
            out[name] = ("in_flight", int(parts[-1]))
        elif len(parts) >= 2 and parts[-1] == "done":
            name = ":".join(parts[:-1])
            out[name] = ("done", 1)
    return out


def write_make_progress(
    mode_key: str,
    data: dict[str, tuple[str, int]],
    lock: threading.Lock,
) -> None:
    """Atomic whole-file write under caller-supplied lock.

    Serializes `data` to a temp file then `os.replace`s it onto the target —
    atomic on both POSIX and Win32, so a torn write leaves the old file
    intact rather than producing a half-written progress file.
    """
    p = make_progress_path(mode_key)
    lines = []
    for name, (status, next_page) in sorted(data.items()):
        if status == "done":
            lines.append(f"{name}:done")
        elif status == "in_flight":
            lines.append(f"{name}:in_flight:{next_page}")
    payload = "\n".join(lines)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with lock:
        if not lines:
            if p.exists():
                p.unlink()
            if tmp.exists():
                tmp.unlink()
            return
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, p)


def update_make_progress(
    mode_key: str,
    make_name: str,
    status: str,
    next_page: int,
    lock: threading.Lock,
) -> None:
    """Read → mutate one entry → write, all under `lock`.

    Called by each worker once per page commit and once per make completion.
    """
    with lock:
        data = read_make_progress(mode_key)
        data[make_name] = (status, next_page)
        # Inline the write to avoid re-acquiring the lock.
        p = make_progress_path(mode_key)
        lines = []
        for name, (st, np) in sorted(data.items()):
            if st == "done":
                lines.append(f"{name}:done")
            elif st == "in_flight":
                lines.append(f"{name}:in_flight:{np}")
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text("\n".join(lines), encoding="utf-8")
        os.replace(tmp, p)


def clear_make_progress(mode_key: str) -> None:
    p = make_progress_path(mode_key)
    if p.exists():
        p.unlink()
    tmp = p.with_suffix(p.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()
