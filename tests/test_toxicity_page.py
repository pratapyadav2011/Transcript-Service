import json
import time

import pytest
from fastapi.testclient import TestClient

from app.core import toxicity_store
from app.core.config import settings


class FakeRedis:
    """Just the commands toxicity_store uses."""

    def __init__(self):
        self.items = {}
        self.index = {}  # id -> ts

    def add(self, check_id, text="hello", source="api", ts=None, scores=None, expired=False):
        ts = ts if ts is not None else time.time()
        scores = scores or {"toxicity": 0.001, "insult": 0.0005, "male": 0.0001}
        top = max(scores, key=scores.get)
        self.index[check_id] = ts
        if not expired:
            self.items[toxicity_store.ITEM_PREFIX + check_id] = json.dumps({
                "id": check_id, "ts": ts, "source": source, "text": text,
                "chars": len(text), "batch_size": 1, "duration_ms": 12.3,
                "top_label": top, "top_score": scores[top], "scores": scores,
            })

    def _newest_first(self):
        return [i for i, _ in sorted(self.index.items(), key=lambda kv: kv[1], reverse=True)]

    def zrevrange(self, key, start, end):
        return self._newest_first()[start:end + 1]

    def zcard(self, key):
        return len(self.index)

    def zcount(self, key, lo, hi):
        return sum(1 for ts in self.index.values() if ts >= lo)

    def mget(self, keys):
        return [self.items.get(k) for k in keys]

    def get(self, key):
        return self.items.get(key)


@pytest.fixture
def fake(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(toxicity_store, "get_redis", lambda: r)
    return r


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "API_SERVICE_TOKEN", "")  # auth off
    from app.main import app
    return TestClient(app)


def test_lists_newest_first_and_pages(fake):
    for i in range(5):
        fake.add(f"c{i}", ts=1000 + i)
    page, cursor = toxicity_store.list_checks(limit=2)
    assert [c["id"] for c in page] == ["c4", "c3"]
    page, cursor = toxicity_store.list_checks(limit=2, cursor=cursor)
    assert [c["id"] for c in page] == ["c2", "c1"]
    page, cursor = toxicity_store.list_checks(limit=2, cursor=cursor)
    assert [c["id"] for c in page] == ["c0"]
    assert cursor is None


def test_no_next_page_when_last_item_fills_page(fake):
    fake.add("a", ts=1)
    fake.add("b", ts=2)
    page, cursor = toxicity_store.list_checks(limit=2)
    assert len(page) == 2 and cursor is None


def test_skips_expired_entries(fake):
    fake.add("live", ts=2)
    fake.add("gone", ts=3, expired=True)
    page, _ = toxicity_store.list_checks()
    assert [c["id"] for c in page] == ["live"]


def test_filters(fake):
    fake.add("clean", text="Thanks for the update", ts=1)
    fake.add("rude", text="You IDIOT", ts=2, scores={"toxicity": 0.99, "insult": 0.97})
    fake.add("mine", text="testing idiot", source="manual", ts=3, scores={"toxicity": 0.6})
    ids = lambda **kw: [c["id"] for c in toxicity_store.list_checks(**kw)[0]]
    assert ids(q="idiot") == ["mine", "rude"]
    assert ids(source="manual") == ["mine"]
    assert ids(source="api") == ["rude", "clean"]
    assert ids(min_score=0.5) == ["mine", "rude"]
    assert ids(min_score=0.85) == ["rude"]


def test_identity_labels_do_not_count_toward_min_score(fake):
    fake.add("x", scores={"toxicity": 0.01, "male": 0.95})
    assert toxicity_store.list_checks(min_score=0.5)[0] == []


def test_page_escapes_comment_text(fake, client):
    fake.add("xss", text="<script>alert(1)</script>")
    body = client.get("/toxicity").text
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body
    detail = client.get("/toxicity/xss").text
    assert "<script>alert(1)</script>" not in detail


def test_detail_page_and_missing_check(fake, client):
    fake.add("abc", text="you are a complete idiot", scores={"toxicity": 0.997, "insult": 0.996, "male": 0.002})
    page = client.get("/toxicity/abc")
    assert page.status_code == 200
    assert "you are a complete idiot" in page.text
    assert "0.9970" in page.text
    assert client.get("/toxicity/nope").status_code == 404


def test_test_box_shows_scores_and_triggers_refresh(fake, client, monkeypatch):
    monkeypatch.setattr(toxicity_store, "score_manual", lambda text: (
        [{"label": "toxicity", "score": 0.99}, {"label": "male", "score": 0.01}], "new123"))
    resp = client.post("/htmx/toxicity/test", data={"text": "hi"})
    assert resp.status_code == 200
    assert "0.9900" in resp.text and "/toxicity/new123" in resp.text
    assert resp.headers["HX-Trigger"] == "toxChecked"


def test_test_box_reports_scorer_errors(fake, client, monkeypatch):
    def boom(text):
        raise toxicity_store.ScorerError("scorer unreachable")
    monkeypatch.setattr(toxicity_store, "score_manual", boom)
    resp = client.post("/htmx/toxicity/test", data={"text": "hi"})
    assert "scorer unreachable" in resp.text
    assert "HX-Trigger" not in resp.headers
    assert "Enter some text" in client.post("/htmx/toxicity/test", data={"text": "  "}).text
