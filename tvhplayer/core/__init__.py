"""TVHeadend client backends (HTTP JSON and HTSP)."""

from .backend import TvhBackend, create_backend
from .config import ConfigStore
from .dvr import RecordingFile
from .errors import TvhError, TvhAuthError, TvhConnectionError
from .models import (
    AutorecEntry,
    AutorecSpec,
    Channel,
    ChannelTag,
    ConnectionStatus,
    ContentType,
    DvrConfig,
    DvrCutpoint,
    DvrEntry,
    DvrEntryUpdate,
    EpgEvent,
    EpgQuery,
    InputStatus,
    ServerActivity,
    ServerConfig,
    StreamProfile,
    SubscriptionStatus,
    TimerecEntry,
    TimerecSpec,
)
from .mpv_player import MpvPlayer
from .player import Player
from .recorder import LocalRecorder

__all__ = [
    'TvhBackend',
    'create_backend',
    'ConfigStore',
    'LocalRecorder',
    'Player',
    'MpvPlayer',
    'RecordingFile',
    'TvhError',
    'TvhAuthError',
    'TvhConnectionError',
    'AutorecEntry',
    'AutorecSpec',
    'Channel',
    'ChannelTag',
    'ConnectionStatus',
    'ContentType',
    'DvrConfig',
    'DvrCutpoint',
    'DvrEntry',
    'DvrEntryUpdate',
    'EpgEvent',
    'EpgQuery',
    'InputStatus',
    'ServerActivity',
    'ServerConfig',
    'StreamProfile',
    'SubscriptionStatus',
    'TimerecEntry',
    'TimerecSpec',
]
