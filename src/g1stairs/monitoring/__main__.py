"""CLI for passive G1 monitoring."""

import argparse
import json
import math
import sys
import time
from contextlib import ExitStack
from pathlib import Path

from g1stairs.session import create_part, dump_line, read_json, read_jsonl, run_path

from .dashboard import Live, Recording, serve
from .telemetry import TEMPERATURE_PERIOD_S, TOPIC, Receiver, Temperatures, serialize, subscribe
from .teleop_trace import record_teleop


ROBOT_PROFILE = "g1-29"


def positive(value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("expected a finite positive number")
    return value


def positive_int(value):
    value = int(value)
    if value < 1:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return value


def session_directory(args):
    return run_path(args.runs_dir, args.run) / "state"


def wait_for_first(receiver, seconds):
    item = receiver.wait(seconds)
    if item is None:
        raise RuntimeError("No {} samples in {} s. Check the chosen NIC and DDS domain.".format(
            TOPIC, seconds
        ))
    return item


def probe(args):
    receiver = Receiver(capacity=1)
    with subscribe(args.nic, args.domain, receiver):
        received_ns, message = wait_for_first(receiver, args.timeout_s)
        sample = serialize(message, received_ns)
    print(json.dumps({"topic": TOPIC, "profile": ROBOT_PROFILE, "sample": sample}, allow_nan=False))


def record(args):
    metadata = {
        "source": "unitree",
        "clock_domain": "host_monotonic_ns",
        "profile": ROBOT_PROFILE,
        "dds_topic": TOPIC,
        "dds_domain": args.domain,
        "duration_requested_s": args.seconds,
        "temperature_period_s": TEMPERATURE_PERIOD_S,
    }
    temperatures = Temperatures()
    receiver = Receiver()
    with create_part(args.runs_dir, args.run, "state", metadata) as path:
        with ExitStack() as subscriptions:
            subscriptions.enter_context(subscribe(args.nic, args.domain, receiver))
            trace = subscriptions.enter_context(record_teleop(path, metadata)) if args.with_teleop else None
            if trace is not None:
                print("7105 요청·보행 상태 구독 시작 · 첫 LowState 표본 대기", flush=True)
            sample = wait_for_first(receiver, args.timeout_s)
            first_ns = sample[0]
            start_ns = max(first_ns, trace.ready_ns) if trace is not None else first_ns
            end_ns = start_ns + max(1, int(args.seconds * 1_000_000_000))
            count = 0
            last_ns = first_ns
            max_gap_ns = 0
            with (path / "samples.jsonl").open("w", encoding="utf-8") as stream:
                while sample is not None and sample[0] < end_ns:
                    received_ns, message = sample
                    dump_line(stream, serialize(message, received_ns, temperatures))
                    if trace is not None:
                        trace.drain()
                    count += 1
                    max_gap_ns = max(max_gap_ns, received_ns - last_ns)
                    last_ns = received_ns
                    remaining = (end_ns - time.monotonic_ns()) / 1_000_000_000
                    sample = receiver.wait(max(0, remaining))
        _, dropped = receiver.snapshot()
        metadata.update({
            "sample_count": count,
            "first_host_rx_monotonic_ns": first_ns,
            "last_host_rx_monotonic_ns": last_ns,
            "max_internal_sample_gap_ns": max_gap_ns,
            "end_without_sample_ns": end_ns - last_ns,
            "dropped_in_application_queue": dropped,
            "measured_recorded_sample_hz": (count - 1) * 1e9 / (last_ns - first_ns)
            if last_ns > first_ns else None,
        })
    print(session_directory(args))


def inspect(args):
    path = session_directory(args)
    metadata = read_json(path / "manifest.json")
    first = last = None
    count = 0
    for sample in read_jsonl(path / "samples.jsonl"):
        if first is None:
            first = sample
        last = sample
        count += 1
    print(json.dumps({
        "source": metadata["source"],
        "metadata": metadata,
        "parsed_sample_count": count,
        "first_sample": first,
        "last_sample": last,
    }, indent=2, allow_nan=False))


def dashboard(args):
    if args.run is not None:
        return serve(Recording(session_directory(args)), args.bind, args.port)

    receiver = Receiver(capacity=0)
    with subscribe(args.nic, args.domain, receiver):
        serve(Live(receiver, args.stale_after_s), args.bind, args.port)


def parser():
    config = argparse.ArgumentParser(prog="g1 monitor", description=__doc__)
    action = config.add_subparsers(dest="action", required=True)

    for name, command in (
        ("probe", probe), ("record", record),
        ("inspect", inspect), ("serve", dashboard),
    ):
        sub = action.add_parser(name)
        sub.set_defaults(command=command)
        sub.add_argument("--runs-dir", type=Path, default=Path("runs"))
        if name != "probe":
            sub.add_argument("--run", required=name != "serve")
        if name in ("probe", "record", "serve"):
            sub.add_argument("--nic", help="DDS network interface (default: Unitree SDK selection)")
            sub.add_argument("--domain", type=int, help="DDS domain ID (default: Unitree SDK domain 0)")
        if name in ("probe", "record"):
            sub.add_argument("--timeout-s", type=positive, default=5.0)
        if name == "record":
            sub.add_argument("--seconds", type=positive, default=10.0)
            sub.add_argument("--with-teleop", action="store_true",
                             help="also record received Move/stop requests and HG gait state transitions")
        if name == "serve":
            sub.add_argument("--bind", default="127.0.0.1")
            sub.add_argument("--port", type=positive_int, default=8765)
            sub.add_argument("--stale-after-s", type=positive, default=1.0)
    return config


def main():
    config = parser()
    args = config.parse_args()
    if args.action == "serve" and args.run is not None:
        if args.nic is not None or args.domain is not None:
            config.error("--nic and --domain only apply to live monitoring")
    elif args.action in ("probe", "record", "serve"):
        if args.domain is None:
            args.domain = 0
        if args.domain < 0:
            config.error("--domain must be nonnegative")
    try:
        args.command(args)
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError, ValueError) as exc:
        print("monitoring: {}".format(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
