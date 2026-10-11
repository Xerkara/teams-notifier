import pytest
import requests

from teams_notifier.errors import GraphError, NetworkError
from teams_notifier.graph import GraphClient


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.headers = headers or {}
        self.text = str(self._body)

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make(responses, tokens=None):
    session = FakeSession(responses)
    sleeps = []
    seen = []

    def provider(force):
        seen.append(force)
        return "tok2" if force else "tok1"

    client = GraphClient(provider, session=session, sleep=sleeps.append)
    return client, session, sleeps, seen


def test_relative_path_gets_graph_root():
    client, session, _, _ = make([FakeResponse(body={"ok": 1})])
    assert client.get("/me") == {"ok": 1}
    assert session.calls[0]["url"] == "https://graph.microsoft.com/v1.0/me"
    assert session.calls[0]["headers"]["Authorization"] == "Bearer tok1"


def test_foreign_host_is_rejected_before_any_request():
    client, session, _, _ = make([])
    with pytest.raises(GraphError):
        client.get("https://evil.example.com/steal")
    assert session.calls == []


def test_http_scheme_rejected():
    client, session, _, _ = make([])
    with pytest.raises(GraphError):
        client.get("http://graph.microsoft.com/v1.0/me")
    assert session.calls == []


def test_throttling_honours_retry_after():
    client, _, sleeps, _ = make(
        [FakeResponse(429, headers={"Retry-After": "7"}), FakeResponse(body={"v": 1})]
    )
    assert client.get("/me") == {"v": 1}
    assert sleeps == [7.0]


def test_excessive_retry_after_gives_up():
    client, _, sleeps, _ = make([FakeResponse(429, headers={"Retry-After": "999"})])
    with pytest.raises(GraphError) as exc:
        client.get("/me")
    assert exc.value.code == "Throttled"
    assert sleeps == []


def test_401_refreshes_token_once():
    client, session, _, seen = make([FakeResponse(401), FakeResponse(body={"ok": 1})])
    assert client.get("/me") == {"ok": 1}
    assert seen == [False, True]
    assert session.calls[1]["headers"]["Authorization"] == "Bearer tok2"


def test_persistent_401_raises():
    client, _, _, _ = make(
        [FakeResponse(401, body={"error": {"code": "InvalidAuthenticationToken", "message": "x"}})] * 2
    )
    with pytest.raises(GraphError) as exc:
        client.get("/me")
    assert exc.value.status == 401


def test_error_body_is_parsed():
    client, _, _, _ = make(
        [FakeResponse(403, body={"error": {"code": "AccessDenied", "message": "nope"}})]
    )
    with pytest.raises(GraphError) as exc:
        client.get("/me")
    assert (exc.value.status, exc.value.code) == (403, "AccessDenied")


def test_network_errors_retry_then_raise():
    errors = [requests.ConnectionError("down")] * 6
    client, _, sleeps, _ = make(errors)
    with pytest.raises(NetworkError):
        client.get("/me")
    assert len(sleeps) == 5


def test_paging_follows_next_link():
    nxt = "https://graph.microsoft.com/v1.0/me/joinedTeams?$skiptoken=abc"
    client, session, _, _ = make(
        [
            FakeResponse(body={"value": [1, 2], "@odata.nextLink": nxt}),
            FakeResponse(body={"value": [3]}),
        ]
    )
    assert list(client.get_paged("/me/joinedTeams")) == [1, 2, 3]
    assert session.calls[1]["url"] == nxt


def test_delta_returns_items_and_delta_link():
    nxt = "https://graph.microsoft.com/v1.0/x/delta?page=2"
    done = "https://graph.microsoft.com/v1.0/x/delta?token=final"
    client, _, _, _ = make(
        [
            FakeResponse(body={"value": ["a"], "@odata.nextLink": nxt}),
            FakeResponse(body={"value": ["b"], "@odata.deltaLink": done}),
        ]
    )
    items, link = client.delta("/x/delta")
    assert items == ["a", "b"]
    assert link == done


def test_delta_without_delta_link_is_error():
    client, _, _, _ = make([FakeResponse(body={"value": []})])
    with pytest.raises(GraphError):
        client.delta("/x/delta")
