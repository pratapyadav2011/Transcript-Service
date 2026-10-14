from app.services.resolver.html_scraper import extract_media_urls
from app.services.resolver.url_classifier import is_granicus_player


def test_legacy_granicus_media_player_is_classified():
    assert is_granicus_player(
        "https://sanfrancisco.granicus.com/MediaPlayer.php"
        "?view_id=10&clip_id=52945"
    )


def test_legacy_granicus_javascript_download_links_are_extracted():
    html = r'''
        downloadLinks = [[
          "https:\/\/archive-video.granicus.com\/sanfrancisco\/meeting.mp4",
          "https:\/\/archive-video.granicus.com\/sanfrancisco\/meeting.mp3"
        ]];
    '''

    assert extract_media_urls(html) == [
        "https://archive-video.granicus.com/sanfrancisco/meeting.mp4",
        "https://archive-video.granicus.com/sanfrancisco/meeting.mp3",
    ]


def test_granicus_videos_pages_are_classified_and_normalized():
    from app.services.resolver.granicus_resolver import normalize

    for url in (
        "https://danville-ca.granicus.com/videos/4093",
        "https://danville-ca.granicus.com/videos/4093/player",
    ):
        assert is_granicus_player(url)
        assert normalize(url) == "https://danville-ca.granicus.com/player/clip/4093"
    # Swagit uses the same /videos/{id} path on its own domain — not Granicus.
    assert not is_granicus_player("https://dublinca.new.swagit.com/videos/403163")
    assert normalize("https://danville-ca.granicus.com/player/clip/4093") == (
        "https://danville-ca.granicus.com/player/clip/4093"
    )
