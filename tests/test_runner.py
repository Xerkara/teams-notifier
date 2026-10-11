import pytest

from teams_notifier.config import NtfyConfig, load_config
from teams_notifier.errors import AuthRequired, GraphError, NotifyError
from teams_notifier.notify import Notifier
from teams_notifier.runner import alert_auth_required, run
from teams_notifier.state import State

from test_files import file_item


class FakeGraph:
    def __init__(self, teams, deltas):
        self.teams = teams
        self.deltas = deltas  # team_id -> list of (items, link) | Exception

    def get_paged(self, path, params=None):
        assert path == "/me/joinedTeams"
        return iter(self.teams)

    def delta(self, path_or_url, params=None):
        team_id = path_or_url.split("/groups/")[1].split("/")[0] if "/groups/" in path_or_url else None
        item = self.deltas[team_id].pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class RecordingNotifier(Notifier):
    def __init__(self, fail=False):
        super().__init__(NtfyConfig(topic="t"), dry_run=True, out=lambda _: None)
        self.sent = []
        self.fail = fail

    def send(self, title, message, **kw):
        if self.fail:
            raise NotifyError("ntfy 500")
        self.sent.append((title, message))
        return 1


@pytest.fixture
def cfg(tmp_path):
    return load_config(tmp_path / "yok.toml")


@pytest.fixture
def state(tmp_path):
    with State(tmp_path / "s.db") as s:
        yield s


TEAMS = [{"id": "t1", "displayName": "Fizik 101"}, {"id": "t2", "displayName": "Kimya"}]


def link(n, team="t1"):
    return f"https://graph.microsoft.com/v1.0/groups/{team}/drive/root/delta?token={n}"


def test_first_run_baselines_everything_without_notifying(cfg, state):
    g = FakeGraph(TEAMS, {"t1": [([file_item("a", "a.pdf")], link(1))], "t2": [([file_item("b", "b.pdf")], link(1, "t2"))]})
    n = RecordingNotifier()
    result = run(cfg, state, g, n)
    assert n.sent == [] and result.notifications == 0
    assert sorted(result.baselined) == ["Fizik 101", "Kimya"]
    assert state.count_files() == 2
    assert state.get_meta("last_run")


def test_second_run_notifies_only_new_file(cfg, state):
    g = FakeGraph(TEAMS, {
        "t1": [([file_item("a", "a.pdf")], link(1)), ([file_item("c", "yeni.pdf")], link(2))],
        "t2": [([], link(1, "t2")), ([], link(2, "t2"))],
    })
    run(cfg, state, g, RecordingNotifier())
    n = RecordingNotifier()
    result = run(cfg, state, g, n)
    assert [t for t, _ in n.sent] == ["📁 Fizik 101 — yeni dosya"]
    assert result.notifications == 1 and result.baselined == []


def test_failed_notification_is_retried_next_run(cfg, state):
    g = FakeGraph([TEAMS[0]], {"t1": [([], link(1)), ([file_item("c", "x.pdf")], link(2)), ([file_item("c", "x.pdf")], link(2))]})
    run(cfg, state, g, RecordingNotifier())
    failing = RecordingNotifier(fail=True)
    result = run(cfg, state, g, failing)
    assert result.failed_teams == ["Fizik 101"] and not result.ok
    n = RecordingNotifier()
    run(cfg, state, g, n)
    assert len(n.sent) == 1


def test_one_broken_team_does_not_stop_the_others(cfg, state):
    g = FakeGraph(TEAMS, {"t1": [GraphError(404, "NotFound", "no drive")], "t2": [([file_item("b", "b.pdf")], link(1, "t2"))]})
    result = run(cfg, state, g, RecordingNotifier())
    assert result.failed_teams == ["Fizik 101"]
    assert result.baselined == ["Kimya"]


def test_auth_required_propagates(cfg, state):
    g = FakeGraph([TEAMS[0]], {"t1": [AuthRequired("bitti")]})
    with pytest.raises(AuthRequired):
        run(cfg, state, g, RecordingNotifier())


def test_excluded_class_is_skipped(tmp_path, state):
    p = tmp_path / "c.toml"
    p.write_text('[files]\nexclude_classes = ["kimya"]\n', encoding="utf-8")
    g = FakeGraph(TEAMS, {"t1": [([], link(1))]})  # t2 için delta çağrısı olursa KeyError
    result = run(load_config(p), state, g, RecordingNotifier())
    assert result.teams == 2 and result.baselined == ["Fizik 101"]


def test_auth_alert_is_sent_once_per_day(cfg, state):
    n = RecordingNotifier()
    assert alert_auth_required(cfg, state, n) is True
    assert alert_auth_required(cfg, state, n) is False
    assert len(n.sent) == 1 and "login" in n.sent[0][1]
