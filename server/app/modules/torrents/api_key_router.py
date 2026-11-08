"""Torrentek kezelése API kulccsal (admin), munkamenet nélkül.

Ugyanazok a műveletek, mint a /torrents útvonalakon, plusz a kézi hozzáadás:
egy indexer torrent (pl. nCore ID) a relay-be kerül, mintha elindították
volna (lejátszási előzmény is készül), de adatot nem streamel.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.modules.auth.dependencies import ApiKeyGuard
from app.modules.playback_histories.schemas.internal import PlaybackHistoryClientInfo
from app.modules.relay.dependencies import get_relay_service
from app.modules.relay.service import RelayService
from app.modules.roles.constants import UserRoleKey
from app.modules.stream.dependencies import get_stream_service
from app.modules.stream.schemas import StreamToken
from app.modules.stream.service import StreamService
from app.modules.torrents.dependencies import get_torrents_service
from app.modules.torrents.schemas.api import (
    TorrentAddRequest,
    TorrentResponse,
    TorrentUpdateRequest,
)
from app.modules.torrents.schemas.internal import TorrentUpdate
from app.modules.torrents.service import TorrentsService
from app.modules.users.models import UserModel

MANUAL_ADD_CLIENT = "StremHU manual add"

router = APIRouter(
    prefix="/{api_key}/torrents",
    tags=["Torrents"],
)

AdminByApiKey = Annotated[UserModel, Depends(ApiKeyGuard([UserRoleKey.ADMIN]))]


@router.get(
    "/",
    response_model=list[TorrentResponse],
)
def get_list_with_api_key(
    torrents_service: Annotated[TorrentsService, Depends(get_torrents_service)],
    _: AdminByApiKey,
):
    return [
        TorrentResponse.from_torrent_with_relay(torrent_pair)
        for torrent_pair in torrents_service.get_torrents()
    ]


@router.post(
    "/add",
    response_model=TorrentResponse,
)
async def add_with_api_key(
    request: Request,
    payload: TorrentAddRequest,
    stream_service: Annotated[StreamService, Depends(get_stream_service)],
    torrents_service: Annotated[TorrentsService, Depends(get_torrents_service)],
    relay_service: Annotated[RelayService, Depends(get_relay_service)],
    user: AdminByApiKey,
):
    torrent_with_relay, file_index = await stream_service.ensure_torrent(
        indexer_id=payload.indexer_id,
        torrent_id=payload.torrent_id,
        file_index=payload.file_index,
    )

    changes: dict[str, bool] = {"full_download": payload.full_download}
    if payload.is_persisted is not None:
        changes["is_persisted"] = payload.is_persisted
    torrent_with_relay = torrents_service.update(
        info_hash=torrent_with_relay.info_hash,
        payload=TorrentUpdate.model_validate(changes),
    )

    # Lejátszási előzmény, ahogy egy elindított streamnél: a kézi hozzáadás
    # így ugyanúgy látszik (és pl. egy debrid sidecar is felveszi).
    file = relay_service.get_torrent_file(
        info_hash=torrent_with_relay.info_hash,
        file_index=file_index,
    )
    await stream_service.save_playback_history(
        stream_token=StreamToken(
            indexer_id=payload.indexer_id,
            torrent_id=payload.torrent_id,
            file_index=file_index,
            playback_id=uuid.uuid4().hex,
        ),
        client_info=PlaybackHistoryClientInfo(
            user_agent=MANUAL_ADD_CLIENT,
            ip=request.client.host if request.client else None,
        ),
        user_id=user.id,
        file=file,
    )

    return TorrentResponse.from_torrent_with_relay(torrent_with_relay)


@router.get(
    "/{info_hash}",
    response_model=TorrentResponse,
)
def get_one_with_api_key(
    info_hash: str,
    torrents_service: Annotated[TorrentsService, Depends(get_torrents_service)],
    _: AdminByApiKey,
):
    return TorrentResponse.from_torrent_with_relay(
        torrents_service.get_by_info_hash(info_hash)
    )


@router.put(
    "/{info_hash}",
    response_model=TorrentResponse,
)
def update_with_api_key(
    info_hash: str,
    payload: TorrentUpdateRequest,
    torrents_service: Annotated[TorrentsService, Depends(get_torrents_service)],
    _: AdminByApiKey,
):
    torrent_pair = torrents_service.update(
        info_hash=info_hash,
        payload=TorrentUpdate.model_validate(
            payload.model_dump(exclude_unset=True),
        ),
    )
    return TorrentResponse.from_torrent_with_relay(torrent_pair)


@router.delete(
    "/{info_hash}",
    status_code=204,
)
def delete_with_api_key(
    info_hash: str,
    torrents_service: Annotated[TorrentsService, Depends(get_torrents_service)],
    _: AdminByApiKey,
):
    torrents_service.delete(info_hash=info_hash)
