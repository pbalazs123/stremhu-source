from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.modules.indexer_definitions.schemas.api import IndexerDefinitionResponse
from app.modules.torrents.schemas.internal import TorrentWithRelay


class TorrentResponse(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )

    info_hash: str
    indexer_definition: IndexerDefinitionResponse
    torrent_id: str
    name: str
    download_speed: int
    upload_speed: int
    downloaded: int
    uploaded: int
    total: int
    is_persisted: bool
    full_download: bool | None
    updated_at: datetime
    created_at: datetime

    @classmethod
    def from_torrent_with_relay(
        cls,
        torrent_with_relay: TorrentWithRelay,
    ) -> "TorrentResponse":
        return cls(
            info_hash=torrent_with_relay.info_hash,
            indexer_definition=IndexerDefinitionResponse.model_validate(
                torrent_with_relay.torrent.indexer_account.indexer_definition
            ),
            torrent_id=torrent_with_relay.torrent.torrent_id,
            name=torrent_with_relay.relay.name,
            download_speed=torrent_with_relay.relay.download_speed,
            upload_speed=torrent_with_relay.relay.upload_speed,
            downloaded=torrent_with_relay.relay.downloaded,
            uploaded=torrent_with_relay.relay.uploaded,
            total=torrent_with_relay.relay.total,
            is_persisted=torrent_with_relay.torrent.is_persisted,
            full_download=torrent_with_relay.torrent.full_download,
            updated_at=torrent_with_relay.torrent.updated_at,
            created_at=torrent_with_relay.torrent.created_at,
        )


class TorrentAddRequest(BaseModel):
    """Torrent hozzáadása az indexer azonosítója alapján (pl. nCore torrent ID)."""

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )

    indexer_id: str = Field(pattern=r"^[a-z0-9_-]{1,32}$")
    torrent_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    # None: a legnagyobb videófájl
    file_index: int | None = Field(default=None, ge=0)
    full_download: bool = True
    is_persisted: bool | None = None


class TorrentUpdateRequest(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )

    is_persisted: bool | None = None
    full_download: bool | None = None
