from app.services.resolver import granicus_resolver
from app.tasks import fastpath


def _vtt(start_hms: str, cues: int = 30) -> str:
    h, m, s = (int(x) for x in start_hms.split(":"))
    base = h * 3600 + m * 60 + s
    lines = ["WEBVTT", ""]
    for i in range(cues):
        a, b = base + i * 5, base + i * 5 + 4
        fmt = lambda t: f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}.000"
        lines += [f"{fmt(a)} --> {fmt(b)}", f"Council member {i} spoke about the agenda item.", ""]
    return "\n".join(lines)


def _run(monkeypatch, vtt):
    monkeypatch.setattr(granicus_resolver, "fetch_captions", lambda url: vtt)
    saved = {}
    monkeypatch.setattr(fastpath, "_finalize",
                        lambda *a: saved.setdefault("text", a[5]) and {"status": "done"})
    logs = []
    result = fastpath.try_granicus_captions("job", lambda step, m: logs.append(m),
                                            "https://danville-ca.granicus.com/videos/4093",
                                            "", "", "system")
    return result, saved.get("text"), logs


def test_full_caption_track_is_used(monkeypatch):
    result, text, _ = _run(monkeypatch, _vtt("00:00:05"))
    assert result == {"status": "done"}
    assert "Council member 0 spoke" in text


def test_empty_caption_file_falls_back_to_audio(monkeypatch):
    result, _, logs = _run(monkeypatch, "WEBVTT\n\n")
    assert result is None
    assert any("empty" in m for m in logs)


def test_late_starting_fragment_falls_back_to_audio(monkeypatch):
    result, _, logs = _run(monkeypatch, _vtt("01:47:39"))
    assert result is None
    assert any("1:47:39" in m and "partial" in m for m in logs)


def test_clip_id_from_all_url_forms():
    for url in ("https://danville-ca.granicus.com/videos/4093",
                "https://danville-ca.granicus.com/videos/4093/player",
                "https://danville-ca.granicus.com/player/clip/4093?view_id=1",
                "https://danville-ca.granicus.com/MediaPlayer.php?view_id=1&clip_id=4093"):
        assert granicus_resolver.clip_id(url) == "4093"


def test_captions_with_a_large_gap_fall_back_to_audio(monkeypatch):
    first_hour = _vtt("00:00:05", cues=20)
    after_gap = _vtt("01:30:00", cues=20).replace("WEBVTT\n\n", "")
    result, _, logs = _run(monkeypatch, first_hour + "\n" + after_gap)
    assert result is None
    assert any("missing from 0:01:44 to 1:30:00" in m for m in logs)


def test_short_recess_gap_is_accepted(monkeypatch):
    before = _vtt("00:00:05", cues=20)
    after_recess = _vtt("00:15:00", cues=20).replace("WEBVTT\n\n", "")
    result, _, _ = _run(monkeypatch, before + "\n" + after_recess)
    assert result == {"status": "done"}
