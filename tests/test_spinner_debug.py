import threading
import time

from tvhplayer import spinner_debug


def test_off_unless_asked(monkeypatch):
    monkeypatch.delenv(spinner_debug.DEBUG_ENV, raising=False)
    assert not spinner_debug.enabled()
    monkeypatch.setenv(spinner_debug.DEBUG_ENV, '0')
    assert not spinner_debug.enabled()
    monkeypatch.setenv(spinner_debug.DEBUG_ENV, '1')
    assert spinner_debug.enabled()


def test_module_hooks_do_nothing_when_off(monkeypatch):
    monkeypatch.setattr(spinner_debug, '_watch', None)
    spinner_debug.started()
    spinner_debug.tick()
    spinner_debug.painted(1.0)
    spinner_debug.stopped()


def test_faulthandler_dump_comes_with_the_late_tick():
    out = []
    watch = spinner_debug.SpinnerWatch(out=out.append)
    watch.started()
    watch.tick()
    time.sleep(spinner_debug.FAULT_SECONDS + 0.05)
    watch.tick()
    watch.stopped()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not any('stopped after' in line for line in out):
        time.sleep(0.01)
    report = next(line for line in out if line.startswith('tick late'))
    assert 'faulthandler, all threads' in report
    assert 'test_faulthandler_dump_comes_with_the_late_tick' in report


def test_on_time_ticks_are_not_reported():
    out = []
    watch = spinner_debug.SpinnerWatch(out=out.append)
    watch.started()
    for _ in range(5):
        time.sleep(0.016)
        watch.tick()
    watch.stopped()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not any('stopped after' in line for line in out):
        time.sleep(0.01)
    assert not any(line.startswith('tick late') for line in out)
    assert '0 late' in out[-1]


def test_threads_in_blocking_calls_are_marked_waiting():
    event = threading.Event()
    waiter = threading.Thread(target=event.wait, name='sleeper')
    waiter.start()
    try:
        time.sleep(0.02)
        text = spinner_debug.format_late(0.2, [spinner_debug.snapshot()])
    finally:
        event.set()
        waiter.join()
    assert 'sleeper: waiting at' in text
