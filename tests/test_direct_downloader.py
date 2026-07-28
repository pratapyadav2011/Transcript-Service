from app.services.downloader.direct_downloader import _granicus_referer


def test_granicus_archive_url_derives_tenant_referer():
    url = (
        "https://archive-video.granicus.com/danville-ca/"
        "danville-ca_d91f53aa-c091-463d-81b7-880557bd5cca.mp4"
    )

    assert _granicus_referer(url) == "https://danville-ca.granicus.com/"


def test_non_granicus_url_has_no_derived_referer():
    assert _granicus_referer("https://example.com/video.mp4") is None
