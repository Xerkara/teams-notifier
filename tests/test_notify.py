import pytest
import requests

from teams_notifier.config import NtfyConfig
from teams_notifier.errors import NetworkError, NotifyError
from teams_notifier.notify import MAX_MESSAGE_BYTES, Notifier, generate_topic, split_message


class FakeResp:
    def __init__(self, status=200):
        self.status_code = status
        self.ok = status < 400


class FakeSession:
    def __init__(self, result=None):
        self.result = result or FakeResp()
        self.posts = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append({"url": url, "json": json, "headers": headers})
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def make(topic="gizli-topic", token="", server="https://ntfy.sh", session=None, **kw):
    session = session or FakeSession()
    return Notifier(NtfyConfig(server=server, topic=topic, token=token), session=session, **kw), session


def test_topic_is_long_and_unique():
    a, b = generate_topic(), generate_topic()
    assert a != b
    assert a.startswith("iyte-") and len(a) >= 32
    assert all(c.isalnum() or c in "-_" for c in a)


def test_json_payload_keeps_turkish_characters():
    n, s = make()
    n.send("📁 Fizik — yeni dosya", "Ödev şablonu.pdf", priority=4, tags=["file_folder"], click="https://x.example/f")
    post = s.posts[0]
    assert post["url"] == "https://ntfy.sh/"
    assert post["json"] == {
        "topic": "gizli-topic",
        "title": "📁 Fizik — yeni dosya",
        "message": "Ödev şablonu.pdf",
        "priority": 4,
        "tags": ["file_folder"],
        "click": "https://x.example/f",
    }


def test_token_sent_as_bearer_and_custom_server():
    n, s = make(token="tk_abc", server="https://ntfy.example.org/")
    n.send("t", "m")
    assert s.posts[0]["headers"]["Authorization"] == "Bearer tk_abc"
    assert s.posts[0]["url"] == "https://ntfy.example.org/"


def test_non_http_click_is_dropped():
    n, s = make()
    n.send("t", "m", click="javascript:alert(1)")
    assert "click" not in s.posts[0]["json"]


def test_priority_range_is_checked():
    n, _ = make()
    with pytest.raises(ValueError):
        n.send("t", "m", priority=6)


def test_missing_topic_raises():
    n, s = make(topic="")
    with pytest.raises(NotifyError):
        n.send("t", "m")
    assert s.posts == []


def test_http_error_does_not_leak_topic():
    n, _ = make(session=FakeSession(FakeResp(403)))
    with pytest.raises(NotifyError) as exc:
        n.send("t", "m")
    assert "gizli-topic" not in str(exc.value)


def test_network_error_is_wrapped():
    n, _ = make(session=FakeSession(requests.ConnectionError("down")))
    with pytest.raises(NetworkError):
        n.send("t", "m")


def test_dry_run_prints_and_sends_nothing():
    out = []
    n, s = make(dry_run=True, out=out.append)
    n.send("Başlık", "Mesaj")
    assert s.posts == []
    assert "Başlık" in out[0] and "Mesaj" in out[0]


def test_short_message_is_not_split():
    assert split_message("a\nb") == ["a\nb"]


def test_long_message_splits_on_lines_within_byte_limit():
    lines = [f"• Ödev dosyası {i} — Öğretmen" for i in range(400)]
    parts = split_message("\n".join(lines))
    assert len(parts) > 1
    assert all(len(p.encode("utf-8")) <= MAX_MESSAGE_BYTES for p in parts)
    assert "\n".join(parts) == "\n".join(lines)  # hiçbir satır kaybolmadı


def test_single_oversized_line_is_cut_at_char_boundary():
    parts = split_message("ş" * 5000, limit=1000)
    assert all(len(p.encode("utf-8")) <= 1000 for p in parts)
    assert "".join(parts) == "ş" * 5000


def test_multi_part_titles_are_numbered():
    n, s = make()
    text = "\n".join("x" * 100 for _ in range(100))
    count = n.send("Başlık", text)
    assert count == len(s.posts) > 1
    assert s.posts[0]["json"]["title"] == f"Başlık (1/{count})"
