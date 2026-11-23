# Author: Codex (IIC)
"""Export recorded sport-service velocity windows and all 29 saved G1 motor slots."""
import argparse
import bisect
import csv
import json
import math
import os
import tempfile
from collections import Counter, defaultdict
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

NS = 1_000_000_000
SERVICE = "rt/api/sport/"
FILES = ("joint-feedback.csv", "joint-targets.csv", "joint-window-summary.csv", "movement-windows.json")
KINDS = {"rt/lowstate": "joints", "rt/lowcmd": "targets"}
# Historical ±0.15 m/s keyboard map used during the two 2026-11-23 captures.
# Equivalent labels describe requested vectors; DDS does not record physical key presses.
KEYS = {(0.15, 0, 0.3): "u", (0.15, 0, 0): "i|I", (0.15, 0, -0.3): "o",
        (0, 0, 0.3): "j", (0, 0, -0.3): "l", (-0.15, 0, -0.3): "m",
        (-0.15, 0, 0): ",|<", (-0.15, 0, 0.3): ".", (0.15, 0.10, 0): "U",
        (0.15, -0.10, 0): "O", (0, 0.10, 0): "J", (0, -0.10, 0): "L",
        (-0.15, 0.10, 0): "M", (-0.15, -0.10, 0): ">"}
PARALLEL = {4: "left_ankle_b", 5: "left_ankle_a", 10: "right_ankle_b", 11: "right_ankle_a",
            13: "waist_a", 14: "waist_b"}
EXPECTED_FIELDS = {"joints": ["q_rad", "dq_rad_s", "tau_est_Nm"],
                   "targets": ["mode", "q_rad", "dq_rad_s", "tau_Nm", "kp", "kd"]}


def records(path):
    with path.open() as f:
        for i, line in enumerate(f, 1):
            try:
                yield json.loads(line)
            except ValueError as e:
                raise ValueError(f"{path}:{i} contains invalid JSON") from e


def key_label(vector):
    return next((keys for default, keys in KEYS.items()
                 if all(math.isclose(x, y, abs_tol=1e-8, rel_tol=1e-7) for x, y in zip(vector, default))), "")


def movement(path):
    requests = []
    responses = defaultdict(list)
    for r in records(path):
        if r["api"] != 7105:
            continue
        if r["topic"] == SERVICE + "request":
            requests.append(r)
        if r["topic"] == SERVICE + "response":
            responses[r["id"]].append(r["code"])
    seen = Counter(r["id"] for r in requests)
    windows = []
    active = None
    for r in sorted(requests, key=lambda r: r["mono_ns"]):
        t, body = r["mono_ns"], r["body"]
        vec, duration = tuple(body["velocity"]), body["duration"]
        if len(vec) != 3 or not all(math.isfinite(v) for v in vec) or not math.isfinite(duration) or duration < 0:
            raise ValueError(f"Invalid velocity request {r['id']}")
        if active is not None and t >= active["end_ns"]:
            active = None
        if active is not None and vec != active["velocity"]:
            active.update(end_ns=t, ended_by="different_velocity" if any(vec) else "observed_zero")
            active = None
        if not any(vec):
            continue
        if active is None:
            active = dict(window=len(windows)+1, velocity=vec, key_equivalent=key_label(vec),
                          start_ns=t, utc_start=r["utc"], requests=[])
            windows.append(active)
        active.update(end_ns=t+round(duration*NS), ended_by="last_request_expiry")
        codes = responses.get(r["id"], [])
        matched = len(codes) == 1 and seen[r["id"]] == 1
        status = "matched" if matched else ("ambiguous" if codes else "unmatched")
        active["requests"].append(dict(id=r["id"], mono_ns=t, utc=r["utc"], duration_s=duration,
                                       response_match=status, code=codes[0] if matched else None))
    for w in windows:
        w["nominal_seconds"] = (w["end_ns"] - w["start_ns"])/NS
        w["utc_end_estimated"] = (datetime.fromisoformat(w["utc_start"]) +
                                  timedelta(seconds=w["nominal_seconds"])).isoformat(timespec="microseconds")
        w["request_count"] = len(w["requests"])
        w["response_counts"] = dict(Counter(str(r["code"]) if r["response_match"] == "matched"
                                            else r["response_match"] for r in w["requests"]))
        w["feedback_samples"] = w["target_samples"] = 0
    return windows


@dataclass
class Range:
    low: float = math.inf
    high: float = -math.inf

    def take(self, value):
        if value is not None:
            self.low = min(self.low, value)
            self.high = max(self.high, value)

    def values(self, factor=1):
        if self.low == math.inf:
            return None, None, None
        return self.low * factor, self.high * factor, (self.high - self.low) * factor


@dataclass
class Stats:
    q: Range = field(default_factory=Range)
    dq: Range = field(default_factory=Range)
    torque: Range = field(default_factory=Range)
    target: Range = field(default_factory=Range)
    first_q: tuple = ()
    last_q: tuple = ()
    feedback_n: int = 0
    target_n: int = 0

    def take(self, kind, ns, vals):
        if kind == "targets":
            self.target_n += 1
            self.target.take(vals[1])
            return
        self.feedback_n += 1
        q, dq, tau = vals
        self.q.take(q)
        self.dq.take(dq)
        self.torque.take(tau)
        if q is not None:
            if not self.first_q or ns < self.first_q[0]:
                self.first_q = (ns, q)
            if not self.last_q or ns >= self.last_q[0]:
                self.last_q = (ns, q)

    def values(self):
        deg = 180/math.pi
        low, high, _ = self.dq.values(deg)
        peak = None if low is None else max(abs(low), abs(high))
        net = (self.last_q[1] - self.first_q[1])*deg if self.last_q else None
        return [self.feedback_n, self.target_n, *self.q.values(deg), net, peak,
                *self.torque.values()[:2], *self.target.values(deg)]


def name_for(names, index, mode):
    if mode == 0 or index not in PARALLEL:
        return names[index]
    return PARALLEL[index] if mode == 1 else f"motor_{index}"


def export(raw, stage, meta, ended):
    names = meta["joint_indices"]
    if len(names) != 29 or len(set(names)) != 29 or any(meta[k] != fields for k, fields in EXPECTED_FIELDS.items()):
        raise ValueError("Unexpected 29-slot layout or field schema in capture.json")
    windows = movement(raw / "rpc.jsonl")
    starts = [w["start_ns"] for w in windows]
    stats = [defaultdict(Stats) for w in windows]
    sample_counts, row_counts = Counter(), Counter()
    modes_seen = set()
    common = ["utc", "monotonic_ns", "source_tick", "window", "key_equivalent", "index", "joint",
              "mode_pr", "mode_machine"]
    with ExitStack() as files:
        writers = {}
        for kind, filename in zip(KINDS.values(), FILES[:2]):
            writers[kind] = csv.writer(files.enter_context((stage / filename).open("x", newline="")))
            writers[kind].writerow(common + meta[kind])
        for record in records(raw / "motors.jsonl"):
            kind = KINDS[record["topic"]]
            slots, ns, mode = record[kind], record["mono_ns"], record["mode_pr"]
            if len(slots) != len(names):
                raise ValueError(f"{kind} sample {ns} has {len(slots)} slots")
            modes_seen.add(mode)
            pos = bisect.bisect_right(starts, ns) - 1
            w = windows[pos] if pos >= 0 and ns < windows[pos]["end_ns"] else None
            if w:
                w["feedback_samples" if kind == "joints" else "target_samples"] += 1
            sample_counts[kind] += 1
            base = [record["utc"], ns, record.get("tick"), w["window"] if w else None,
                    w["key_equivalent"] if w else None]
            for i, values in enumerate(slots):
                if len(values) != len(meta[kind]):
                    raise ValueError(f"{kind} sample {ns}, slot {i} has invalid field count")
                name = name_for(names, i, mode)
                writers[kind].writerow([*base, i, name, mode, record.get("mode_machine"), *values])
                row_counts[kind] += 1
                if w:
                    stats[pos][(i, name)].take(kind, ns, values)
    for k in KINDS.values():
        if row_counts[k] != len(names)*sample_counts[k]:
            raise ValueError(f"Exported slot count mismatch: {k}")
    header = ["window", "key_equivalent", "utc_start", "utc_end_estimated", "start_ns", "end_ns_exclusive",
              "vx_m_s", "vy_m_s", "yaw_rad_s", "duration_s", "ended_by", "request_count", "response_counts",
              "index", "joint", "group", "feedback_samples", "target_samples", "measured_min_deg",
              "measured_max_deg", "measured_span_deg", "measured_net_change_deg", "peak_abs_dq_deg_s",
              "measured_tau_est_min_Nm", "measured_tau_est_max_Nm", "target_min_deg", "target_max_deg",
              "target_span_deg"]
    with (stage / FILES[2]).open("x", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for w, sample in zip(windows, stats):
            if not sample:
                # No sampled representation within this window; retain 29 empty indices.
                default = next(iter(modes_seen)) if len(modes_seen) == 1 else -1
                for i in range(len(names)):
                    sample[(i, name_for(names, i, default))] = Stats()
            if (sum(s.feedback_n for s in sample.values()) != w["feedback_samples"]*len(names)
                    or sum(s.target_n for s in sample.values()) != w["target_samples"]*len(names)):
                raise ValueError(f"Window slot count mismatch: {w['window']}")
            base = [w["window"], w["key_equivalent"], w["utc_start"], w["utc_end_estimated"],
                    w["start_ns"], w["end_ns"], *w["velocity"], w["nominal_seconds"], w["ended_by"],
                    w["request_count"], json.dumps(w["response_counts"], separators=(",", ":"))]
            for (i, name), s in sorted(sample.items()):
                writer.writerow([*base, i, name, "leg" if i < 12 else "waist" if i < 15 else "arm", *s.values()])
    counts = {k: {"samples":sample_counts[k], "csv_slot_rows":row_counts[k]} for k in KINDS.values()}
    report = dict(source_files=["capture.json", "capture-end.json", "motors.jsonl", "rpc.jsonl"],
                  method="Recorded sport/7105 requested intervals [start,end), bounded by each last request's "
                         "finite duration, observed zero, or direction change. Response codes reflect matched "
                         "RPC IDs. Termination need not imply physical stop. Key labels are equivalent default "
                         "vectors, not observed keypresses. Blank labels mean no matching default vector. "
                         "Nonempty rows with null measurements count as samples. UTC end is estimated from "
                         "first-request UTC and monotonic duration. Empty measurements remain blank.",
                  counts=counts, queue_drops=ended.get("queue_drops"), windows=windows)
    (stage / FILES[3]).write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return counts, len(windows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    path = args.run.resolve(strict=True)
    if not (path / "capture-end.json").is_file():
        parser.error("capture-end.json missing; recording has not finished")
    ended = json.loads((path/"capture-end.json").read_text())
    if not ended.get("end_utc"):
        parser.error("capture-end.json does not mark completion")
    if any(os.path.lexists(path/name) for name in FILES):
        parser.error("one or more output files already exist; no changes made")
    meta = json.loads((path/"capture.json").read_text())
    raw_files = [path/n for n in ("rpc.jsonl", "motors.jsonl")]
    def signatures():
        return [(s.st_size, s.st_mtime_ns, s.st_ino) for s in map(os.stat, raw_files)]
    before = signatures()
    with tempfile.TemporaryDirectory(dir=path, prefix=".joint-export-") as tmp:
        stage = Path(tmp)
        counts, windows = export(path, stage, meta, ended)
        if before != signatures():
            parser.error("an input file changed during export")
        published = []
        try:
            for name in FILES:
                os.link(stage/name, path/name)  # Publish exclusively, even with two concurrent CLI invocations.
                published.append(name)
        except BaseException:
            for name in reversed(published):
                if (path/name).samefile(stage/name):
                    (path/name).unlink()
            raise
    print(json.dumps({"directory":str(path), "windows":windows, "counts":counts}))


if __name__ == "__main__":
    main()
