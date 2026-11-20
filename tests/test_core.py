import math
from datetime import datetime, timedelta

import pytest

from co2_estimator import (
    Sample,
    decay_ach,
    load_samples,
    occupancy_from_steady,
    occupancy_series,
    steady_level,
)
from co2_estimator.cli import main

T0 = datetime(2026, 1, 5, 9, 0)


def decay_curve(ach, start=2000, out=420, minutes=5, count=12):
    return [
        Sample(T0 + timedelta(minutes=minutes * i), out + (start - out) * math.exp(-ach * minutes * i / 60))
        for i in range(count)
    ]


def write_csv(path, samples):
    lines = ["time,ppm"] + [f"{s.time:%Y-%m-%dT%H:%M},{s.ppm:.1f}" for s in samples]
    path.write_text("\n".join(lines) + "\n")


def test_decay_recovers_exact_ach():
    ach, r2 = decay_ach(decay_curve(2.5))
    assert ach == pytest.approx(2.5, rel=1e-6)
    assert r2 == pytest.approx(1.0)


def test_decay_uses_custom_outdoor():
    samples = decay_curve(1.0, out=500)
    ach, _ = decay_ach(samples, outdoor=500)
    assert ach == pytest.approx(1.0, rel=1e-6)


def test_decay_ignores_rising_part():
    rising = [Sample(T0 - timedelta(minutes=5 * i), 700 + 100 * (4 - i)) for i in range(4, 0, -1)]
    ach, _ = decay_ach(rising + decay_curve(1.5))
    assert ach == pytest.approx(1.5, rel=1e-6)


def test_decay_needs_a_falling_run():
    flat = [Sample(T0 + timedelta(minutes=5 * i), 900 + 10 * i) for i in range(6)]
    with pytest.raises(ValueError):
        decay_ach(flat)


def test_decay_stops_near_outdoor_level():
    samples = decay_curve(3.0, count=40)
    ach, _ = decay_ach(samples)
    assert ach == pytest.approx(3.0, rel=0.01)


def test_steady_level_top_fraction():
    samples = [Sample(T0 + timedelta(minutes=i), p) for i, p in enumerate([500, 600, 1000, 1200, 700, 800, 900, 650, 550, 520])]
    assert steady_level(samples, 0.2) == pytest.approx(1100)


def test_steady_level_at_least_one():
    samples = [Sample(T0 + timedelta(minutes=i), p) for i, p in enumerate([500, 900, 700])]
    assert steady_level(samples, 0.1) == 900


def test_occupancy_from_steady_known_case():
    # 20 people, 0.018 m3/h each, 100 m3, 2 ACH: rise = 20*0.018e6/(2*100) = 1800 ppm
    assert occupancy_from_steady(2220, 100, 2.0) == pytest.approx(20.0)


def test_occupancy_never_negative():
    assert occupancy_from_steady(400, 100, 2.0) == 0.0


@pytest.mark.parametrize("volume,ach", [(0, 1), (100, 0), (-5, 1)])
def test_bad_parameters_rejected(volume, ach):
    with pytest.raises(ValueError):
        occupancy_from_steady(1000, volume, ach)
    with pytest.raises(ValueError):
        occupancy_series(decay_curve(1.0), volume, ach)


def test_series_is_zero_for_empty_decaying_room():
    series = occupancy_series(decay_curve(2.0, count=6), 120, 2.0)
    assert all(p < 0.5 for _, p in series)


def test_series_estimates_constant_occupancy():
    ach, vol, people, out = 2.0, 100.0, 10, 420.0
    c, samples = 600.0, []
    for i in range(30):
        samples.append(Sample(T0 + timedelta(minutes=i), c))
        dt = 1 / 60
        c += (people * 0.018e6 / vol - ach * (c - out)) * dt
    series = occupancy_series(samples, vol, ach)
    assert series[-1][1] == pytest.approx(people, rel=0.05)


def test_load_samples_sorts_and_validates(tmp_path):
    f = tmp_path / "a.csv"
    f.write_text("time,ppm\n2026-01-05T09:10,800\n2026-01-05T09:00,900\n2026-01-05T09:05,850\n")
    samples = load_samples(f)
    assert [s.ppm for s in samples] == [900, 850, 800]


def test_load_samples_bad_row(tmp_path):
    f = tmp_path / "a.csv"
    f.write_text("time,ppm\nnot-a-time,800\nx,1\ny,2\n")
    with pytest.raises(ValueError):
        load_samples(f)


def test_load_samples_missing_columns(tmp_path):
    f = tmp_path / "a.csv"
    f.write_text("when,co2\n1,2\n")
    with pytest.raises(ValueError):
        load_samples(f)


def test_cli_ach_and_exit_codes(tmp_path, capsys):
    f = tmp_path / "d.csv"
    write_csv(f, decay_curve(2.0))
    assert main(["ach", str(f)]) == 0
    assert "ACH 2.00" in capsys.readouterr().out
    assert main(["ach", str(tmp_path / "missing.csv")]) == 2


def test_cli_report_on_example(capsys):
    assert main(["report", "examples/classroom.csv", "--volume", "150"]) == 0
    out = capsys.readouterr().out
    assert "Peak occupancy" in out


def test_cli_help_exits_zero():
    with pytest.raises(SystemExit) as info:
        main(["--help"])
    assert info.value.code == 0
