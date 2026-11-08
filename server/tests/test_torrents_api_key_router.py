import asyncio
import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.main import app
from app.modules.auth.dependencies import get_auth_service
from app.modules.indexer_accounts.dependencies import get_indexer_accounts_service
from app.modules.indexer_definitions.dependencies import (
    get_indexer_definitions_service,
)
from app.modules.playback_histories.schemas.internal import PlaybackHistoryClientInfo
from app.modules.relay.dependencies import get_relay_service
from app.modules.stream import service as stream_service_module
from app.modules.stream.dependencies import get_stream_service
from app.modules.stream.schemas import StreamToken
from app.modules.stream.service import StreamService
from app.modules.torrents.api_key_router import MANUAL_ADD_CLIENT
from app.modules.torrents.dependencies import get_torrents_service
from app.modules.torrents.schemas.internal import TorrentWithRelay

INFO_HASH = "a" * 40
NOW = datetime.datetime(2026, 1, 1, 12, 0, 0)


def _pair() -> TorrentWithRelay:
    definition = SimpleNamespace(
        id="ncore",
        name="nCore",
        url="https://ncore.pro",
        details_path="/torrents.php?action=details&id=",
        requires_full_download=False,
        supports_totp=True,
    )
    torrent = SimpleNamespace(
        info_hash=INFO_HASH,
        torrent_id="1234567",
        is_persisted=False,
        full_download=True,
        updated_at=NOW,
        created_at=NOW,
        indexer_account=SimpleNamespace(indexer_definition=definition),
    )
    relay = SimpleNamespace(
        name="Film.2026.1080p",
        download_speed=0,
        upload_speed=0,
        downloaded=0,
        uploaded=0,
        total=1000,
    )
    return TorrentWithRelay(torrent=torrent, relay=relay)  # type: ignore[arg-type]


@pytest.fixture
def mocks():
    auth = MagicMock()
    auth.verify_api_key.return_value = SimpleNamespace(id="user123", role_id="admin")

    stream = MagicMock()
    stream.ensure_torrent = AsyncMock(return_value=(_pair(), 2))
    stream.save_playback_history = AsyncMock()

    torrents = MagicMock()
    torrents.update.return_value = _pair()
    torrents.get_torrents.return_value = [_pair()]
    torrents.get_by_info_hash.return_value = _pair()

    relay = MagicMock()
    relay.get_torrent_file.return_value = SimpleNamespace(
        name="Film.2026.1080p.mkv", torrent=SimpleNamespace(name="Film.2026.1080p")
    )

    definitions = MagicMock()
    definitions.get_list.return_value = [
        SimpleNamespace(
            id="ncore",
            url="https://ncore.pro",
            details_path="/torrents.php?action=details&id={torrent_id}",
        ),
        SimpleNamespace(
            id="bithumen",
            url="https://bithumen.be",
            details_path="/details.php?id={torrent_id}",
        ),
        SimpleNamespace(
            id="filelist",
            url="https://filelist.io",
            details_path="/details.php?id={torrent_id}",
        ),
    ]
    accounts = MagicMock()
    # filelist is a known tracker, but without an account here
    accounts.find_list.return_value = [
        SimpleNamespace(indexer_id="ncore"),
        SimpleNamespace(indexer_id="bithumen"),
    ]

    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_stream_service] = lambda: stream
    app.dependency_overrides[get_torrents_service] = lambda: torrents
    app.dependency_overrides[get_relay_service] = lambda: relay
    app.dependency_overrides[get_indexer_definitions_service] = lambda: definitions
    app.dependency_overrides[get_indexer_accounts_service] = lambda: accounts
    try:
        yield SimpleNamespace(auth=auth, stream=stream, torrents=torrents, relay=relay)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_add_by_torrent_id(client, mocks):
    """Kézi hozzáadás: relay-be kerül, teljes letöltés, lejátszási előzmény."""
    response = client.post(
        "/api/key123/torrents/add",
        json={"indexerId": "ncore", "torrentId": "1234567"},
    )

    assert response.status_code == 200
    assert response.json()["infoHash"] == INFO_HASH

    mocks.auth.verify_api_key.assert_called_once_with("key123", ["admin"])
    mocks.stream.ensure_torrent.assert_awaited_once_with(
        indexer_id="ncore", torrent_id="1234567", file_index=None
    )

    update = mocks.torrents.update.call_args.kwargs["payload"]
    assert update.model_fields_set == {"full_download"}
    assert update.full_download is True

    mocks.relay.get_torrent_file.assert_called_once_with(
        info_hash=INFO_HASH, file_index=2
    )
    history = mocks.stream.save_playback_history.await_args.kwargs
    assert history["stream_token"].indexer_id == "ncore"
    assert history["stream_token"].torrent_id == "1234567"
    assert history["stream_token"].file_index == 2
    assert history["client_info"].user_agent == MANUAL_ADD_CLIENT
    assert history["user_id"] == "user123"


def test_add_with_options(client, mocks):
    response = client.post(
        "/api/key123/torrents/add",
        json={
            "indexerId": "ncore",
            "torrentId": "1234567",
            "fileIndex": 0,
            "fullDownload": False,
            "isPersisted": True,
        },
    )

    assert response.status_code == 200
    mocks.stream.ensure_torrent.assert_awaited_once_with(
        indexer_id="ncore", torrent_id="1234567", file_index=0
    )
    update = mocks.torrents.update.call_args.kwargs["payload"]
    assert update.model_fields_set == {"full_download", "is_persisted"}
    assert update.full_download is False
    assert update.is_persisted is True


@pytest.mark.parametrize(
    ("url", "indexer_id", "torrent_id"),
    [
        (
            "https://ncore.pro/torrents.php?action=details&id=3920123",
            "ncore",
            "3920123",
        ),
        ("https://bithumen.be/details.php?id=987654", "bithumen", "987654"),
    ],
)
def test_add_by_link(client, mocks, url, indexer_id, torrent_id):
    response = client.post("/api/key123/torrents/add", json={"url": url})

    assert response.status_code == 200
    mocks.stream.ensure_torrent.assert_awaited_once_with(
        indexer_id=indexer_id, torrent_id=torrent_id, file_index=None
    )
    token = mocks.stream.save_playback_history.await_args.kwargs["stream_token"]
    assert (token.indexer_id, token.torrent_id) == (indexer_id, torrent_id)


@pytest.mark.parametrize(
    "body",
    [
        # a tracker without an account, by link and by id
        {"url": "https://filelist.io/details.php?id=55"},
        {"indexerId": "filelist", "torrentId": "55"},
        # not a details page of any tracker
        {"url": "https://evil.example/details.php?id=55"},
        {"url": "https://ncore.pro/torrents.php?action=download&id=55"},
    ],
)
def test_add_refuses_unknown_tracker_or_link(client, mocks, body):
    response = client.post("/api/key123/torrents/add", json=body)

    assert response.status_code == 400
    mocks.stream.ensure_torrent.assert_not_awaited()


@pytest.mark.parametrize(
    "body",
    [
        {"indexerId": "ncore", "torrentId": "../1"},
        # both ways at once, or neither, or only half of the id pair
        {
            "url": "https://ncore.pro/torrents.php?action=details&id=1",
            "indexerId": "ncore",
            "torrentId": "1",
        },
        {},
        {"indexerId": "ncore"},
        {"torrentId": "1"},
        {"url": "x" * 501},
        {"indexerId": "ncore", "torrentId": ""},
        {"indexerId": "NCORE!", "torrentId": "1"},
        {"indexerId": "ncore", "torrentId": "1", "fileIndex": -1},
    ],
)
def test_add_rejects_bad_input(client, mocks, body):
    response = client.post("/api/key123/torrents/add", json=body)

    assert response.status_code == 422
    mocks.stream.ensure_torrent.assert_not_awaited()


def test_wrong_api_key_is_refused(client, mocks):
    mocks.auth.verify_api_key.side_effect = HTTPException(401, "invalid")

    assert client.get("/api/bad/torrents/").status_code == 401
    assert (
        client.post(
            "/api/bad/torrents/add", json={"indexerId": "ncore", "torrentId": "1"}
        ).status_code
        == 401
    )
    assert client.delete(f"/api/bad/torrents/{INFO_HASH}").status_code == 401
    mocks.stream.ensure_torrent.assert_not_awaited()
    mocks.torrents.delete.assert_not_called()


def test_list_get_update_delete(client, mocks):
    listed = client.get("/api/key123/torrents/")
    assert listed.status_code == 200
    assert [t["infoHash"] for t in listed.json()] == [INFO_HASH]

    one = client.get(f"/api/key123/torrents/{INFO_HASH}")
    assert one.status_code == 200
    assert one.json()["name"] == "Film.2026.1080p"

    updated = client.put(
        f"/api/key123/torrents/{INFO_HASH}", json={"isPersisted": True}
    )
    assert updated.status_code == 200
    payload = mocks.torrents.update.call_args.kwargs["payload"]
    assert payload.model_fields_set == {"is_persisted"}

    deleted = client.delete(f"/api/key123/torrents/{INFO_HASH}")
    assert deleted.status_code == 204
    mocks.torrents.delete.assert_called_once_with(info_hash=INFO_HASH)


def _stream_service(torrent_file, existing=None):
    torrents = MagicMock()
    torrents.find_by_id.return_value = existing
    torrent_files = MagicMock()
    torrent_files.find_by_id.return_value = torrent_file
    service = StreamService(
        torrents_service=torrents,
        torrent_files_service=torrent_files,
        indexers_service=MagicMock(),
        relay_service=MagicMock(),
        isolated_torrent_files_service=MagicMock(),
    )
    return service, torrent_files


def _video(size, is_video=True):
    return SimpleNamespace(size=size, is_video=is_video)


def test_ensure_torrent_picks_largest_video():
    torrent_file = SimpleNamespace(
        info=SimpleNamespace(
            files=[_video(10), _video(999, is_video=False), _video(500), _video(20)]
        )
    )
    service, _ = _stream_service(torrent_file)
    created = _pair()

    with patch.object(StreamService, "_create_torrent", return_value=created) as make:
        pair, index = asyncio.run(service.ensure_torrent("ncore", "1", None))

    assert index == 2
    assert pair is created
    make.assert_called_once_with(torrent_file=torrent_file, file_index=2)


def test_ensure_torrent_without_video_is_refused():
    torrent_file = SimpleNamespace(
        info=SimpleNamespace(files=[_video(10, is_video=False)])
    )
    service, _ = _stream_service(torrent_file)

    with pytest.raises(HTTPException) as e:
        asyncio.run(service.ensure_torrent("ncore", "1", None))
    assert e.value.status_code == 400


def test_ensure_torrent_existing_keeps_stream_path_unchanged():
    """Ha a torrent már a relay-ben van és van file_index, nem nyúl a .torrent fájlhoz."""
    existing = _pair()
    service, torrent_files = _stream_service(None, existing=existing)

    pair, index = asyncio.run(service.ensure_torrent("ncore", "1", 3))

    assert pair is existing
    assert index == 3
    torrent_files.find_by_id.assert_not_called()


def _history_args():
    return dict(
        stream_token=StreamToken(
            indexer_id="ncore", torrent_id="1", file_index=0, playback_id="p1"
        ),
        client_info=PlaybackHistoryClientInfo(user_agent="test", ip=None),
        user_id="u1",
        file=SimpleNamespace(name="a.mkv", torrent=SimpleNamespace(name="A")),
    )


def test_playback_history_retries_when_database_is_locked(monkeypatch):
    """Foglalt SQLite esetén újrapróbál: az előzmény nem veszhet el csendben."""
    monkeypatch.setattr(stream_service_module, "PLAYBACK_HISTORY_RETRY_DELAYS", (0, 0))
    service, _ = _stream_service(None)
    locked = OperationalError("INSERT", {}, Exception("database is locked"))
    with patch.object(
        StreamService, "_save_playback_history", side_effect=[locked, locked, None]
    ) as save:
        asyncio.run(service.save_playback_history(**_history_args()))
    assert save.call_count == 3


def test_playback_history_gives_up_after_retries(monkeypatch):
    monkeypatch.setattr(stream_service_module, "PLAYBACK_HISTORY_RETRY_DELAYS", (0, 0))
    service, _ = _stream_service(None)
    locked = OperationalError("INSERT", {}, Exception("database is locked"))
    with patch.object(
        StreamService, "_save_playback_history", side_effect=locked
    ) as save:
        # logs, never raises
        asyncio.run(service.save_playback_history(**_history_args()))
    assert save.call_count == 3


def test_playback_history_other_errors_are_not_retried(monkeypatch):
    monkeypatch.setattr(stream_service_module, "PLAYBACK_HISTORY_RETRY_DELAYS", (0, 0))
    service, _ = _stream_service(None)
    broken = OperationalError("INSERT", {}, Exception("no such table"))
    with patch.object(
        StreamService, "_save_playback_history", side_effect=broken
    ) as save:
        asyncio.run(service.save_playback_history(**_history_args()))
    assert save.call_count == 1
