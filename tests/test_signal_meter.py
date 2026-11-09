import os
import types

from tvhplayer.core.playback_status import SIGNAL_FAIR, SIGNAL_GOOD, SIGNAL_NONE, SIGNAL_POOR
from tvhplayer.core.signal import (
    UNRATED,
    Reading,
    SignalReadings,
    better,
    level_from_percent,
    signal_readings,
    snr_db_percent,
)


def tuner(signal=None, signal_scale=0, snr=None, snr_scale=0):
    return types.SimpleNamespace(signal=signal, signal_scale=signal_scale, snr=snr, snr_scale=snr_scale)


def test_relative_readings_from_a_real_hdhomerun():
    # status/inputs on 554 MHz: strength 74%, quality 84%.
    readings = signal_readings(tuner(48495, 1, 55049, 1))
    assert readings.strength == Reading(74, '74%', SIGNAL_GOOD)
    assert readings.quality == Reading(84, '84%', SIGNAL_GOOD)
    assert readings.describe() == 'Strength 74% (good), quality 84% (good)'
    # No station: some strength, no quality.
    readings = signal_readings(tuner(26214, 1, 0, 1))
    assert readings.strength == Reading(40, '40%', SIGNAL_FAIR)
    assert readings.quality == Reading(0, '0%', SIGNAL_NONE)
    assert readings.describe() == 'Strength 40% (fair), quality 0%'


def test_absolute_readings():
    readings = signal_readings(tuner(-61000, 2, 15000, 2))
    # A strength in dBm is shown, not judged: tuners report it on different footings.
    assert readings.strength == Reading(65, '-61 dBm', UNRATED)
    assert readings.quality == Reading(60, '15.0 dB', SIGNAL_GOOD)
    assert readings.describe() == 'Strength -61 dBm, quality 15.0 dB (good)'


def test_snr_bar_lengths_meet_the_level_thresholds():
    assert snr_db_percent(0) == 0
    assert level_from_percent(snr_db_percent(7.9)) == SIGNAL_POOR
    assert level_from_percent(snr_db_percent(8)) == SIGNAL_FAIR
    assert level_from_percent(snr_db_percent(14.9)) == SIGNAL_FAIR
    assert level_from_percent(snr_db_percent(15)) == SIGNAL_GOOD
    assert snr_db_percent(30) == 100 and snr_db_percent(45) == 100


def test_no_readings_for_iptv_or_no_tuner():
    assert not signal_readings(None)
    assert not signal_readings(tuner())
    assert signal_readings(tuner()).describe() == ''


def test_better_prefers_quality_then_strength():
    weak = SignalReadings(Reading(80, '80%', SIGNAL_GOOD), Reading(10, '10%', SIGNAL_POOR))
    locked = SignalReadings(Reading(50, '50%', SIGNAL_FAIR), Reading(70, '70%', SIGNAL_GOOD))
    assert better(weak, locked) is locked
    assert better(locked, weak) is locked
    assert better(SignalReadings(), weak) is weak


def test_signal_meter_shows_bars_numbers_and_words():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication

    from tvhplayer.signal_meter import LEVEL_COLORS, SignalMeter

    from PyQt6.QtWidgets import QVBoxLayout, QWidget

    app = QApplication.instance() or QApplication([])
    page = QWidget()
    meter = SignalMeter()
    QVBoxLayout(page).addWidget(meter)
    page.show()
    # No reading yet: no meter.
    assert not meter.isVisible()
    meter.set_readings(signal_readings(tuner(26214, 1, 0, 1)))
    assert meter.isVisible()
    assert meter.strength.number.text() == '40%' and meter.quality.number.text() == '0%'
    assert meter.strength.bar.percent() == 40
    assert meter.strength.bar.fill_color() == LEVEL_COLORS[SIGNAL_FAIR]
    assert meter.quality.bar.fill_color() == LEVEL_COLORS[SIGNAL_NONE]
    assert meter.accessibleName() == 'Strength 40% (fair), quality 0%'
    # A tuner with only a quality reading shows only that one.
    meter.set_readings(signal_readings(tuner(snr=55049, snr_scale=1)))
    assert not meter.strength.isVisibleTo(meter) and meter.quality.isVisibleTo(meter)
    page.grab()
    page.close()
    app.processEvents()
