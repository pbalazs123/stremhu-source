from types import SimpleNamespace

import pytest

from app.modules.torrents.details_url import match_details_url

NCORE = SimpleNamespace(
    id="ncore",
    url="https://ncore.pro",
    details_path="/torrents.php?action=details&id={torrent_id}",
)
BITHUMEN = SimpleNamespace(
    id="bithumen",
    url="https://bithumen.be",
    details_path="/details.php?id={torrent_id}",
)
PATH_STYLE = SimpleNamespace(
    id="pathy", url="https://tracker.example", details_path="/torrent/{torrent_id}"
)
DEFS = [NCORE, BITHUMEN, PATH_STYLE]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://ncore.pro/torrents.php?action=details&id=3920123",
            ("ncore", "3920123"),
        ),
        (
            "https://ncore.pro/torrents.php?id=3920123&action=details",
            ("ncore", "3920123"),
        ),
        ("http://www.ncore.pro/torrents.php?action=details&id=42", ("ncore", "42")),
        ("  https://NCORE.pro/torrents.php?action=details&id=42  ", ("ncore", "42")),
        (
            "https://ncore.pro/torrents.php?action=details&id=42#comments",
            ("ncore", "42"),
        ),
        ("https://bithumen.be/details.php?id=987654", ("bithumen", "987654")),
        ("https://bithumen.be/details.php?id=987654&hit=1", ("bithumen", "987654")),
        ("https://tracker.example/torrent/abc-123", ("pathy", "abc-123")),
        ("https://tracker.example/torrent/abc-123/", ("pathy", "abc-123")),
    ],
)
def test_recognised_links(url, expected):
    assert match_details_url(url, DEFS) == expected


@pytest.mark.parametrize(
    "url",
    [
        # other hosts, also lookalikes
        "https://evil.example/torrents.php?action=details&id=42",
        "https://ncore.pro.evil.example/torrents.php?action=details&id=42",
        "https://evil.example/?next=https://ncore.pro/torrents.php?action=details&id=42",
        "https://xncore.pro/torrents.php?action=details&id=42",
        # right host, wrong page
        "https://ncore.pro/torrents.php?action=download&id=42",
        "https://ncore.pro/torrents.php?id=42",
        "https://ncore.pro/other.php?action=details&id=42",
        "https://ncore.pro/torrents.php?action=details",
        "https://ncore.pro/torrents.php?action=details&id=",
        "https://ncore.pro/torrents.php?action=details&id=1&id=2",
        "https://ncore.pro/torrents.php?action=details&id=../../etc",
        "https://ncore.pro/torrents.php?action=details&action=x&id=42",
        "https://tracker.example/torrent/a/b",
        # not a web link at all
        "ftp://ncore.pro/torrents.php?action=details&id=42",
        "javascript:alert(1)",
        "ncore.pro/torrents.php?action=details&id=42",
        "",
    ],
)
def test_rejected_links(url):
    assert match_details_url(url, DEFS) is None


def test_only_given_definitions_count():
    """A hívó csak a beállított fiókú indexereket adja át: a többi linkje nem ismerhető fel."""
    url = "https://bithumen.be/details.php?id=987654"
    assert match_details_url(url, [NCORE]) is None
