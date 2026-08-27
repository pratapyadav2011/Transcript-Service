from unittest.mock import patch

from app.services.resolver.media_resolver import resolve_candidates
from app.services.resolver.url_classifier import is_vimeo_url
from app.services.resolver.vimeo_resolver import resolve


PUBLIC_URL = "https://vimeo.com/1220976784?share=copy"
PLAYER_URL = "https://player.vimeo.com/video/1220976784?h=e62369f18d"


def test_vimeo_urls_are_classified():
    assert is_vimeo_url(PUBLIC_URL)
    assert is_vimeo_url(PLAYER_URL)
    assert not is_vimeo_url("https://example.com/video/1220976784")


def test_vimeo_page_resolves_embedded_player_with_privacy_hash():
    page = f'<iframe src="{PLAYER_URL}&amp;autoplay=0"></iframe>'

    with patch("app.services.resolver.vimeo_resolver.fetch_text", return_value=page):
        assert resolve(PUBLIC_URL) == f"{PLAYER_URL}&autoplay=0"


def test_media_resolver_uses_vimeo_player_url():
    with patch("app.services.resolver.vimeo_resolver.fetch_text", return_value=PLAYER_URL):
        assert resolve_candidates(PUBLIC_URL) == [PLAYER_URL]


def test_vimeo_player_url_does_not_require_page_fetch():
    with patch("app.services.resolver.vimeo_resolver.fetch_text") as fetch:
        assert resolve(PLAYER_URL) == PLAYER_URL
        fetch.assert_not_called()
