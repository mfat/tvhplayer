"""TVHeadend client backends (HTTP JSON and HTSP)."""

from .backend import TvhBackend, create_backend
from .config import ConfigStore
from .dvr import RecordingFile
from .errors import TvhError, TvhAuthError, TvhConnectionError
from .models import (
    AutorecEntry,
    AutorecSpec,
    Channel,
    DvrConfig,
    DvrCutpoint,
    DvrEntry,
    DvrEntryUpdate,
    EpgEvent,
    ServerConfig,
    TimerecEntry,
    TimerecSpec,
)
from .recorder import LocalRecorder

__all__ = [
    'TvhBackend',
    'create_backend',
    'ConfigStore',
    'LocalRecorder',
    'RecordingFile',
    'TvhError',
    'TvhAuthError',
    'TvhConnectionError',
    'AutorecEntry',
    'AutorecSpec',
    'Channel',
    'DvrConfig',
    'DvrCutpoint',
    'DvrEntry',
    'DvrEntryUpdate',
    'EpgEvent',
    'ServerConfig',
    'TimerecEntry',
    'TimerecSpec',
]
