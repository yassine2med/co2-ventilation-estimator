"""Command line entry: ach, occupancy and report."""
from __future__ import annotations

import argparse
import sys

from .core import (
    DEFAULT_OUTDOOR_PPM,
    PER_PERSON_M3H,
    decay_ach,
    load_samples,
    occupancy_from_steady,
    occupancy_series,
    steady_level,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="co2_estimator", description="Estimate air changes and occupancy from a CO2 curve."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("file", help="CSV with columns time,ppm")
        p.add_argument("--outdoor", type=float, default=DEFAULT_OUTDOOR_PPM, help="outdoor CO2 in ppm (default 420)")

    ach = sub.add_parser("ach", help="air changes per hour from the decay after people leave")
    common(ach)
    occ = sub.add_parser("occupancy", help="occupancy per interval, with ACH given")
    common(occ)
    occ.add_argument("--volume", type=float, required=True, help="room volume in m3")
    occ.add_argument("--ach", type=float, required=True, help="air changes per hour")
    occ.add_argument("--per-person", type=float, default=PER_PERSON_M3H, help="CO2 m3/h per person")
    rep = sub.add_parser("report", help="fit ACH from the decay, then estimate peak occupancy")
    common(rep)
    rep.add_argument("--volume", type=float, required=True, help="room volume in m3")
    rep.add_argument("--per-person", type=float, default=PER_PERSON_M3H, help="CO2 m3/h per person")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Exit 0 on success, 2 on bad input or when no decay can be fitted."""
    args = build_parser().parse_args(argv)
    try:
        samples = load_samples(args.file)
        if args.command == "ach":
            value, r2 = decay_ach(samples, args.outdoor)
            print(f"ACH {value:.2f} per hour (fit R2 {r2:.3f})")
        elif args.command == "occupancy":
            for when, people in occupancy_series(samples, args.volume, args.ach, args.outdoor, args.per_person):
                print(f"{when:%H:%M}  {people:5.1f} people")
        else:
            value, r2 = decay_ach(samples, args.outdoor)
            plateau = steady_level(samples)
            people = occupancy_from_steady(plateau, args.volume, value, args.outdoor, args.per_person)
            print(f"ACH from decay       {value:.2f} per hour (R2 {r2:.3f})")
            print(f"Plateau CO2          {plateau:.0f} ppm")
            print(f"Peak occupancy       {people:.1f} people")
            print(f"Outdoor air per head {value * args.volume / max(people, 1e-9):.1f} m3/h")
    except FileNotFoundError:
        print(f"error: file not found: {args.file}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
