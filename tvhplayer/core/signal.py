"""Signal strength and quality of a tuner, as numbers and bar lengths. No Qt imports.

``signal_readings`` turns a Tvheadend ``status/inputs`` row into two
``Reading`` values that ``signal_meter.SignalMeter`` draws as coloured bars
with their numbers. Levels are the ones playback uses (``playback_status``),
so a bar's colour and the words elsewhere in the app agree.

Tvheadend gives each reading on a scale: relative (65535 = 100%), absolute
(signal in 0.001 dBm, SNR in 0.001 dB), or none.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .playback_status import (
    PERCENT_FAIR,
    PERCENT_GOOD,
    RELATIVE_FULL,
    SIGNAL_FAIR,
    SIGNAL_GOOD,
    SIGNAL_NONE,
    SIGNAL_POOR,
    SNR_DB_FAIR,
    SNR_DB_GOOD,
)

SCALE_RELATIVE = 1
SCALE_ABSOLUTE = 2
# SNR in dB to bar length, through the same points as the levels: fair at
# SNR_DB_FAIR is PERCENT_FAIR long, good at SNR_DB_GOOD is PERCENT_GOOD long.
SNR_DB_FULL = 30
# Absolute strength in dBm to bar length. Tuners differ in what is good, so
# the bar is not judged: it is drawn in a neutral colour.
DBM_EMPTY = -100
DBM_FULL = -40
# Not judged: an absolute strength, which tuners report on different footings.
UNRATED = ''


@dataclass(frozen=True)
class Reading:
    """One reading: bar length 0-100, the number as shown, and its level."""

    percent: int
    text: str
    level: str


@dataclass(frozen=True)
class SignalReadings:
    strength: Optional[Reading] = None
    quality: Optional[Reading] = None

    def __bool__(self):
        return self.strength is not None or self.quality is not None

    def describe(self) -> str:
        """The readings in words, for assistive technology and plain text."""
        parts = []
        for name, reading in (('strength', self.strength), ('quality', self.quality)):
            if reading is not None:
                level = f' ({reading.level})' if reading.level not in (UNRATED, SIGNAL_NONE) else ''
                parts.append(f'{name} {reading.text}{level}')
        text = ', '.join(parts)
        return text[:1].upper() + text[1:]


def level_from_percent(percent: int) -> str:
    if percent <= 0:
        return SIGNAL_NONE
    if percent >= PERCENT_GOOD:
        return SIGNAL_GOOD
    if percent >= PERCENT_FAIR:
        return SIGNAL_FAIR
    return SIGNAL_POOR


def _clamp(value: float) -> int:
    return max(0, min(100, round(value)))


def snr_db_percent(snr_db: float) -> int:
    """Bar length for an SNR in dB, through the level thresholds."""
    points = ((0, 0), (SNR_DB_FAIR, PERCENT_FAIR), (SNR_DB_GOOD, PERCENT_GOOD), (SNR_DB_FULL, 100))
    if snr_db <= 0:
        return 0
    for (low_db, low_pct), (high_db, high_pct) in zip(points, points[1:]):
        if snr_db <= high_db:
            # Rounded down: rounding up could lift a reading just under a
            # threshold into the next level.
            return max(0, min(100, math.floor(low_pct + (snr_db - low_db) * (high_pct - low_pct) / (high_db - low_db) + 1e-9)))
    return 100


def _relative(value: int) -> Reading:
    percent = _clamp(value * 100 / RELATIVE_FULL)
    return Reading(percent, f'{percent}%', level_from_percent(percent))


def strength_reading(value, scale) -> Optional[Reading]:
    if value is None:
        return None
    if scale == SCALE_RELATIVE:
        return _relative(value)
    if scale == SCALE_ABSOLUTE:
        dbm = value / 1000
        percent = _clamp((dbm - DBM_EMPTY) * 100 / (DBM_FULL - DBM_EMPTY))
        return Reading(percent, f'{dbm:.0f} dBm', UNRATED)
    return None


def quality_reading(value, scale) -> Optional[Reading]:
    if value is None:
        return None
    if scale == SCALE_RELATIVE:
        return _relative(value)
    if scale == SCALE_ABSOLUTE:
        snr_db = value / 1000
        percent = snr_db_percent(snr_db)
        return Reading(percent, f'{snr_db:.1f} dB', level_from_percent(percent))
    return None


def signal_readings(tuner) -> SignalReadings:
    """Strength and quality (SNR) of a tuner from ``status/inputs``; empty for IPTV, which has neither."""
    if tuner is None:
        return SignalReadings()
    return SignalReadings(
        strength=strength_reading(tuner.signal, tuner.signal_scale),
        quality=quality_reading(tuner.snr, tuner.snr_scale),
    )


def better(old: SignalReadings, new: SignalReadings) -> SignalReadings:
    """The better of two readings of one frequency: by quality, then by strength."""
    def key(readings):
        return (readings.quality.percent if readings.quality else -1,
                readings.strength.percent if readings.strength else -1)
    return new if key(new) >= key(old) else old
