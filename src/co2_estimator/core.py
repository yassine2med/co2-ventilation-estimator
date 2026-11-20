"""Mass balance maths for a room with one CO2 sensor.

Model: dC/dt = N * g / V - ACH * (C - Cout), with C in ppm, V in m3,
g the CO2 a person breathes out (m3 of pure CO2 per hour) and ACH the air
changes per hour. Two uses:

* After people leave, N is 0 and C - Cout decays as exp(-ACH * t), so a
  straight line fit on ln(C - Cout) gives ACH.
* With ACH known, every pair of readings gives an occupancy estimate.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Seated adult at light activity breathes out about 0.3 L/min of CO2.
PER_PERSON_M3H = 0.018
DEFAULT_OUTDOOR_PPM = 420.0


@dataclass(frozen=True)
class Sample:
    time: datetime
    ppm: float


def load_samples(path: str | Path) -> list[Sample]:
    """Read a CSV with columns time (ISO 8601) and ppm. Raises ValueError on bad rows."""
    samples: list[Sample] = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not {"time", "ppm"} <= set(reader.fieldnames):
            raise ValueError("CSV needs columns: time, ppm")
        for number, row in enumerate(reader, start=2):
            try:
                samples.append(Sample(datetime.fromisoformat(row["time"].strip()), float(row["ppm"])))
            except (ValueError, AttributeError) as exc:
                raise ValueError(f"row {number}: cannot read {row}") from exc
    if len(samples) < 3:
        raise ValueError("need at least 3 samples")
    samples.sort(key=lambda s: s.time)
    return samples


def _hours(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 3600.0


def steady_level(samples: list[Sample], fraction: float = 0.2) -> float:
    """Mean of the highest share of readings (default top 20 percent), taken as the plateau."""
    count = max(1, int(len(samples) * fraction))
    top = sorted((s.ppm for s in samples), reverse=True)[:count]
    return sum(top) / len(top)


def decay_ach(samples: list[Sample], outdoor: float = DEFAULT_OUTDOOR_PPM) -> tuple[float, float]:
    """Air changes per hour from the falling part of the curve, plus the fit R squared.

    Uses the longest run of readings that keep falling and stay above outdoor + 50 ppm.
    """
    best: list[Sample] = []
    run: list[Sample] = []
    for s in samples:
        if s.ppm - outdoor < 50:
            run = []
            continue
        if run and s.ppm >= run[-1].ppm:
            run = []
        run.append(s)
        if len(run) > len(best):
            best = list(run)
    if len(best) < 3:
        raise ValueError("no falling run of at least 3 readings found; cannot fit decay")
    xs = [_hours(best[0].time, s.time) for s in best]
    ys = [math.log(s.ppm - outdoor) for s in best]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (my + slope * (x - mx))) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 if ss_tot == 0 else 1 - ss_res / ss_tot
    return -slope, r2


def occupancy_from_steady(
    plateau: float, volume: float, ach: float, outdoor: float = DEFAULT_OUTDOOR_PPM,
    per_person: float = PER_PERSON_M3H,
) -> float:
    """People needed to hold the room at a steady CO2 level."""
    if volume <= 0 or ach <= 0 or per_person <= 0:
        raise ValueError("volume, ach and per_person must be positive")
    return max(0.0, (plateau - outdoor) * ach * volume / (per_person * 1e6))


def occupancy_series(
    samples: list[Sample], volume: float, ach: float, outdoor: float = DEFAULT_OUTDOOR_PPM,
    per_person: float = PER_PERSON_M3H,
) -> list[tuple[datetime, float]]:
    """Occupancy estimate for each interval between readings, never below 0."""
    if volume <= 0 or ach <= 0 or per_person <= 0:
        raise ValueError("volume, ach and per_person must be positive")
    out = []
    for a, b in zip(samples, samples[1:]):
        dt = _hours(a.time, b.time)
        if dt <= 0:
            continue
        rate = (b.ppm - a.ppm) / dt
        mid = (a.ppm + b.ppm) / 2
        people = volume * (rate + ach * (mid - outdoor)) / (per_person * 1e6)
        out.append((b.time, max(0.0, people)))
    return out
