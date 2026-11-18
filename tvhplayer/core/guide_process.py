"""Run guide imports outside the UI's Python interpreter. No Qt imports."""

import multiprocessing
import tempfile
import time

from .errors import TvhError
from .guide_feeds import GuideCache, GuideError
from .guide_update import update_server_guide
from .tvh_admin import TvhAdmin

# Give cooperative cancellation time to close files before interrupting I/O.
CANCEL_GRACE = 2.0


def _update(server, cache, sources, choices, force, **callbacks):
    with TvhAdmin(server) as admin:
        return update_server_guide(admin, server, cache, sources, choices, force, **callbacks)


def _worker(pipe, stop, server, folder, work_folder, sources, choices, force, update):
    last_progress = 0.0

    def progress(done, total):
        nonlocal last_progress
        now = time.monotonic()
        if now - last_progress >= 0.1 or done == total:
            pipe.send(('progress', (done, total)))
            last_progress = now

    try:
        cache = GuideCache(folder, work_folder=work_folder)
        report = update(server, cache, sources, choices, force,
                        status=lambda message: pipe.send(('status', message)),
                        progress=progress, cancelled=stop.is_set)
        pipe.send(('done', (report, sources)))
    except Exception as exc:
        # Send only known exception categories, not arbitrary exception objects
        # that may be unpicklable or need constructor arguments on receipt.
        kind = 'guide' if isinstance(exc, GuideError) else 'server' if isinstance(exc, TvhError) else 'other'
        pipe.send(('failed', (kind, str(exc), sources)))
    finally:
        pipe.close()


def run_guide_update(server, cache, sources, choices, force=False, *,
                     status=lambda text: None, progress=lambda done, total: None,
                     cancelled=lambda: False, update=_update):
    """Wait on a spawned worker; call this from the job's monitoring thread.

    Source timestamps/errors are copied back even when the import fails. The
    parent owns temporary files so a cancelled or crashed worker leaves no
    partially written guide behind. Completed cache files remain reusable.
    """
    if cancelled():
        raise GuideError('Stopped.')
    ctx = multiprocessing.get_context('spawn')
    reader, writer = ctx.Pipe(duplex=False)
    stop = ctx.Event()
    cache.folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='guide-job-', dir=cache.folder) as work_folder:
        process = ctx.Process(target=_worker, args=(
            writer, stop, server, str(cache.folder), work_folder, sources, choices, force, update,
        ), name='guide-import', daemon=True)
        started = False
        try:
            process.start()
            started = True
            writer.close()
            stopping_at = None
            while True:
                if cancelled():
                    if stopping_at is None:
                        stop.set()
                        stopping_at = time.monotonic()
                    if time.monotonic() - stopping_at >= CANCEL_GRACE:
                        raise GuideError('Stopped.')
                if not reader.poll(0.05):
                    if not process.is_alive():
                        raise GuideError('The guide worker stopped unexpectedly.')
                    continue
                try:
                    kind, data = reader.recv()
                except EOFError:
                    raise GuideError('Stopped.' if stopping_at is not None else
                                     'The guide worker stopped unexpectedly.') from None
                if kind == 'status':
                    status(data)
                elif kind == 'progress':
                    progress(*data)
                elif kind in ('done', 'failed'):
                    updated = data[-1]
                    states = {(source.server, source.location): source for source in updated}
                    for source in sources:
                        state = states.get((source.server, source.location))
                        if state is not None:
                            source.updated, source.tried, source.error = state.updated, state.tried, state.error
                    if stopping_at is not None:
                        raise GuideError('Stopped.')
                    if kind == 'failed':
                        category, message, _sources = data
                        error = {'guide': GuideError, 'server': TvhError}.get(category, RuntimeError)
                        raise error(message)
                    return data[0]
        finally:
            if started:
                process.join(timeout=0.2)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=1)
                if process.is_alive():
                    process.kill()
                    process.join()
            reader.close()
            writer.close()
            process.close()
