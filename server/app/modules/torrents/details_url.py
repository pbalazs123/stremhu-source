"""Indexer torrent adatlap link felismerése (pl. ncore.pro/torrents.php?action=details&id=123).

Az indexer definíciók saját `url` és `details_path` mintája alapján: a hosztnak pontosan egyeznie kell
(a "www." előtag nem számít), az útvonalnak és a többi paraméternek is, csak a {torrent_id} helye változhat.
"""

import re
from collections.abc import Iterable
from typing import Protocol
from urllib.parse import parse_qs, parse_qsl, urlsplit

TORRENT_ID_RE = r"[A-Za-z0-9_-]{1,64}"
PLACEHOLDER = "{torrent_id}"


class DetailsDefinition(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def url(self) -> str: ...

    @property
    def details_path(self) -> str: ...


def _host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host.removeprefix("www.")


def match_details_url(
    url: str, definitions: Iterable[DetailsDefinition]
) -> tuple[str, str] | None:
    """Visszaadja az (indexer_id, torrent_id) párt, vagy None-t, ha egyik definícióra sem illik."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    host = _host(url.strip())
    given = parse_qs(parts.query, keep_blank_values=True)

    for definition in definitions:
        if host != _host(definition.url):
            continue

        template_path, _, template_query = definition.details_path.partition("?")
        path_re = (
            "^"
            + re.escape(template_path).replace(
                re.escape(PLACEHOLDER), f"(?P<id>{TORRENT_ID_RE})"
            )
            + "/?$"
        )
        path_match = re.match(path_re, parts.path or "/")
        if not path_match:
            continue

        torrent_id = path_match.groupdict().get("id")
        matched = True
        for key, value in parse_qsl(template_query, keep_blank_values=True):
            values = given.get(key) or []
            if value == PLACEHOLDER:
                if len(values) != 1 or not re.fullmatch(TORRENT_ID_RE, values[0]):
                    matched = False
                    break
                torrent_id = values[0]
            elif values != [value]:
                matched = False
                break

        if matched and torrent_id:
            return definition.id, torrent_id

    return None
