from app.services.downloader.direct_downloader import _granicus_referer, _header_variants


def test_granicus_archive_url_derives_tenant_referer():
    url = (
        "https://archive-video.granicus.com/danville-ca/"
        "danville-ca_d91f53aa-c091-463d-81b7-880557bd5cca.mp4"
    )

    assert _granicus_referer(url) == "https://danville-ca.granicus.com/"


def test_non_granicus_url_has_no_derived_referer():
    assert _granicus_referer("https://example.com/video.mp4") is None


def test_header_variants_include_supplied_and_derived_referers():
    variants = _header_variants(
        "https://danville-ca.granicus.com/player/clip/4036",
        "https://danville-ca.granicus.com/",
    )

    assert [headers.get("Referer") for headers in variants] == [
        None,
        "https://danville-ca.granicus.com/player/clip/4036",
        "https://danville-ca.granicus.com/",
    ]
