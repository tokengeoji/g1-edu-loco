"""Shared run layout and manifest-based publication of completed data."""

import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path


RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
PARTS = {"state", "depth", "geometry"}


def run_path(root, run_id):
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("run_id must be 1–64 characters: letters, digits, '_' or '-'")
    return Path(root) / run_id


def recorded_frame_path(depth_path, sample):
    relative = Path(sample["file"])
    if len(relative.parts) != 2 or relative.parts[0] != "frames" or relative.suffix != ".npy":
        raise ValueError("invalid recorded frame path: %s" % relative)
    path = depth_path / relative
    if path.resolve().parent != depth_path.resolve() / "frames":
        raise ValueError("recorded frame path leaves the frames directory: %s" % relative)
    return path


def dump_line(handle, value):
    handle.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")


def write_json(path, value):
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, allow_nan=False, indent=2)
        handle.write("\n")


def read_json(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def read_jsonl(path):
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            try:
                yield json.loads(line)
            except ValueError as error:
                raise ValueError(f"{path}:{line_number}: invalid JSON record") from error


@contextmanager
def create_part(root, run_id, part, metadata):
    if part not in PARTS:
        raise ValueError(f"unknown run component: {part}")
    run = run_path(root, run_id)
    run.mkdir(parents=True, exist_ok=True)
    final = run / part
    lock = run / f".{part}.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise FileExistsError(f"recording already in progress, or an interrupted write: {lock}") from error
    os.close(fd)
    stage = None
    try:
        if final.exists() or final.is_symlink():
            raise FileExistsError(f"existing component preserved: {final}; choose a new run ID")
        stage = Path(tempfile.mkdtemp(prefix=f".{part}-", dir=run))
        yield stage
        manifest = dict(metadata)
        manifest.update(schema_version=1, run_id=run_id, part=part, complete=True)
        write_json(stage / "manifest.json", manifest)
        stage.rename(final)
    finally:
        if stage is not None and stage.exists():
            shutil.rmtree(stage)
        lock.unlink()
