import sqlite3

from teams_notifier.state import MIGRATIONS, State


def test_schema_is_created_and_versioned(tmp_path):
    path = tmp_path / "state.db"
    with State(path):
        pass
    db = sqlite3.connect(path)
    assert db.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"meta", "teams", "delta_links", "files", "sent_reminders"} <= tables


def test_reopening_does_not_remigrate(tmp_path):
    path = tmp_path / "state.db"
    with State(path) as s:
        s.set_meta("k", "v")
    with State(path) as s:
        assert s.get_meta("k") == "v"


def test_meta_overwrite_and_default(tmp_path):
    with State(tmp_path / "s.db") as s:
        assert s.get_meta("x") is None
        assert s.get_meta("x", "d") == "d"
        s.set_meta("x", "1")
        s.set_meta("x", "2")
        assert s.get_meta("x") == "2"


def test_upsert_team_reports_new_only_once(tmp_path):
    with State(tmp_path / "s.db") as s:
        assert s.upsert_team("t1", "Fizik") is True
        assert s.upsert_team("t1", "Fizik 101") is False
        assert [r["display_name"] for r in s.list_teams()] == ["Fizik 101"]


def test_baseline_flag(tmp_path):
    with State(tmp_path / "s.db") as s:
        s.upsert_team("t1", "Fizik")
        assert s.is_team_baselined("t1") is False
        s.mark_team_baselined("t1")
        assert s.is_team_baselined("t1") is True
        assert s.is_team_baselined("unknown") is False


def test_delta_link_roundtrip(tmp_path):
    with State(tmp_path / "s.db") as s:
        assert s.get_delta_link("t1") is None
        s.set_delta_link("t1", "https://graph.microsoft.com/a")
        s.set_delta_link("t1", "https://graph.microsoft.com/b")
        assert s.get_delta_link("t1") == "https://graph.microsoft.com/b"
        s.clear_delta_link("t1")
        assert s.get_delta_link("t1") is None


def test_record_file_new_unchanged_updated(tmp_path):
    with State(tmp_path / "s.db") as s:
        kw = dict(name="a.pdf", ctag="c1", last_modified="2026-01-01T00:00:00Z")
        assert s.record_file("t1", "i1", **kw) == "new"
        assert s.record_file("t1", "i1", **kw) == "unchanged"
        kw["ctag"] = "c2"
        assert s.record_file("t1", "i1", **kw) == "updated"
        assert s.count_files("t1") == 1


def test_same_item_id_in_other_team_is_separate(tmp_path):
    with State(tmp_path / "s.db") as s:
        assert s.record_file("t1", "i1", name="a") == "new"
        assert s.record_file("t2", "i1", name="a") == "new"
        assert s.count_files() == 2
