import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy.exc import OperationalError

from app.modules.playback_histories.schemas.internal import PlaybackHistoryClientInfo
from app.modules.stream import service as stream_service_module
from app.modules.stream.schemas import StreamToken
from app.modules.stream.service import StreamService


def _service() -> StreamService:
    return StreamService(
        torrents_service=MagicMock(),
        torrent_files_service=MagicMock(),
        indexers_service=MagicMock(),
        relay_service=MagicMock(),
        isolated_torrent_files_service=MagicMock(),
    )


def _history_args():
    return dict(
        stream_token=StreamToken(
            indexer_id="ncore", torrent_id="1", file_index=0, playback_id="p1"
        ),
        client_info=PlaybackHistoryClientInfo(user_agent="test", ip=None),
        user_id="u1",
        file=SimpleNamespace(name="a.mkv", torrent=SimpleNamespace(name="A")),
    )


def _locked():
    return OperationalError("INSERT", {}, Exception("database is locked"))


def test_retries_when_database_is_locked(monkeypatch):
    """Foglalt SQLite esetén újrapróbál: az előzmény nem veszhet el csendben."""
    monkeypatch.setattr(stream_service_module, "PLAYBACK_HISTORY_RETRY_DELAYS", (0, 0))
    attempts = [_locked(), _locked(), None]
    with patch.object(
        StreamService, "_save_playback_history", side_effect=attempts
    ) as save:
        asyncio.run(_service().save_playback_history(**_history_args()))
    assert save.call_count == 3


def test_gives_up_after_retries_without_raising(monkeypatch):
    monkeypatch.setattr(stream_service_module, "PLAYBACK_HISTORY_RETRY_DELAYS", (0, 0))
    with patch.object(
        StreamService, "_save_playback_history", side_effect=_locked()
    ) as save:
        asyncio.run(_service().save_playback_history(**_history_args()))
    assert save.call_count == 3


def test_other_errors_are_not_retried(monkeypatch):
    monkeypatch.setattr(stream_service_module, "PLAYBACK_HISTORY_RETRY_DELAYS", (0, 0))
    broken = OperationalError("INSERT", {}, Exception("no such table"))
    with patch.object(
        StreamService, "_save_playback_history", side_effect=broken
    ) as save:
        asyncio.run(_service().save_playback_history(**_history_args()))
    assert save.call_count == 1
