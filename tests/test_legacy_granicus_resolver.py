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
