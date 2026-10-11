import pytest

from teams_notifier.errors import GraphError
from teams_notifier.files import FileTracker, build_notifications
from teams_notifier.state import State

DELTA_LINK = "https://graph.microsoft.com/v1.0/groups/t1/drive/root/delta?token=A"
DELTA_LINK_2 = "https://graph.microsoft.com/v1.0/groups/t1/drive/root/delta?token=B"


def file_item(item_id, name, ctag="c1", modified="2026-01-01T00:00:00Z", folder="General", author="Ayşe Hoca"):
    return {
        "id": item_id,
        "name": name,
        "file": {"mimeType": "application/pdf"},
        "cTag": ctag,
        "lastModifiedDateTime": modified,
        "webUrl": f"https://school.sharepoint.com/{name}",
        "parentReference": {"path": f"/drives/b!xyz/root:/{folder}" if folder else "/drives/b!xyz/root:"},
        "createdBy": {"user": {"displayName": author}},
        "lastModifiedBy": {"user": {"displayName": author}},
    }


class FakeClient:
    """delta(path_or_url) çağrılarını sırayla yanıtlar."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def delta(self, path_or_url, params=None):
        self.calls.append(path_or_url)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def state(tmp_path):
    with State(tmp_path / "s.db") as s:
        s.upsert_team("t1", "Fizik 101")
        yield s


def do_scan(state, *responses):
    client = FakeClient(*responses)
    tracker = FileTracker(client, state)
    scan = tracker.scan("t1", "Fizik 101")
    return tracker, scan, client


def test_first_scan_is_baseline_and_silent(state):
    tracker, scan, client = do_scan(state, ([file_item("i1", "a.pdf"), file_item("i2", "b.pdf")], DELTA_LINK))
    assert scan.baseline is True
    assert scan.new_files() == []
    assert build_notifications(scan) == []
    assert client.calls == ["/groups/t1/drive/root/delta"]
    tracker.commit(scan)
    assert state.count_files("t1") == 2
    assert state.is_team_baselined("t1") is True
    assert state.get_delta_link("t1") == DELTA_LINK


def test_scan_alone_does_not_change_state(state):
    _, scan, _ = do_scan(state, ([file_item("i1", "a.pdf")], DELTA_LINK))
    assert state.count_files("t1") == 0
    assert state.get_delta_link("t1") is None
    assert state.is_team_baselined("t1") is False


def baselined(state, items=()):
    tracker, scan, _ = do_scan(state, (list(items), DELTA_LINK))
    tracker.commit(scan)


def test_new_file_after_baseline_is_reported_with_link_and_details(state):
    baselined(state, [file_item("i1", "a.pdf")])
    tracker, scan, client = do_scan(state, ([file_item("i2", "Hafta1.pdf", folder="General/Notlar")], DELTA_LINK_2))
    assert client.calls == [DELTA_LINK]  # kayıtlı delta link kullanıldı
    [note] = build_notifications(scan)
    assert note.title == "📁 Fizik 101 — yeni dosya"
    assert "Hafta1.pdf" in note.message and "General/Notlar" in note.message and "Ayşe Hoca" in note.message
    assert note.click == "https://school.sharepoint.com/Hafta1.pdf"


def test_multiple_new_files_are_grouped_in_one_notification(state):
    baselined(state)
    _, scan, _ = do_scan(state, ([file_item("i1", "a.pdf"), file_item("i2", "b.pdf"), file_item("i3", "c.pdf")], DELTA_LINK_2))
    [note] = build_notifications(scan)
    assert note.title == "📁 Fizik 101 — 3 yeni dosya"
    assert note.message.count("•") == 3
    assert note.click is None


def test_no_duplicate_notification_after_commit(state):
    baselined(state)
    tracker, scan, _ = do_scan(state, ([file_item("i1", "a.pdf")], DELTA_LINK_2))
    assert len(scan.new_files()) == 1
    tracker.commit(scan)
    # Aynı öğe delta'da tekrar gelirse yeni sayılmaz.
    _, scan2, _ = do_scan(state, ([file_item("i1", "a.pdf")], DELTA_LINK_2))
    assert scan2.new_files() == []


def test_uncommitted_scan_is_reported_again(state):
    """Bildirim gönderilemeyip commit atlanırsa dosya kaybolmamalı."""
    baselined(state)
    _, scan1, _ = do_scan(state, ([file_item("i1", "a.pdf")], DELTA_LINK_2))
    assert len(scan1.new_files()) == 1
    _, scan2, _ = do_scan(state, ([file_item("i1", "a.pdf")], DELTA_LINK_2))
    assert len(scan2.new_files()) == 1


def test_folders_and_onenote_packages_are_ignored(state):
    baselined(state)
    items = [
        {"id": "f1", "name": "Hafta 1", "folder": {"childCount": 2}, "parentReference": {"path": "/drives/x/root:"}},
        {"id": "r", "name": "root", "root": {}, "folder": {}},
        {"id": "p1", "name": "Defter", "package": {"type": "oneNote"}},
    ]
    _, scan, _ = do_scan(state, (items, DELTA_LINK_2))
    assert scan.changes == []


def test_deleted_item_is_forgotten_not_notified(state):
    baselined(state, [file_item("i1", "a.pdf")])
    assert state.count_files("t1") == 1
    tracker, scan, _ = do_scan(state, ([{"id": "i1", "deleted": {}}], DELTA_LINK_2))
    assert build_notifications(scan) == []
    tracker.commit(scan)
    assert state.count_files("t1") == 0


def test_updated_file_only_notified_when_enabled(state):
    baselined(state, [file_item("i1", "a.pdf")])
    _, scan, _ = do_scan(state, ([file_item("i1", "a.pdf", ctag="c2", modified="2026-02-01T00:00:00Z")], DELTA_LINK_2))
    assert scan.new_files() == []
    assert build_notifications(scan) == []
    [note] = build_notifications(scan, notify_updates=True)
    assert note.title == "🔄 Fizik 101 — dosya güncellendi"
    assert note.priority == 2


def test_duplicate_item_in_delta_uses_last_occurrence(state):
    baselined(state)
    first = file_item("i1", "eski.pdf")
    last = file_item("i1", "yeni-ad.pdf")
    _, scan, _ = do_scan(state, ([first, last], DELTA_LINK_2))
    [change] = scan.new_files()
    assert change.name == "yeni-ad.pdf"


def test_expired_delta_token_restarts_without_renotifying(state):
    baselined(state, [file_item("i1", "a.pdf")])
    gone = GraphError(410, "resyncRequired", "delta expired")
    full = [file_item("i1", "a.pdf"), file_item("i2", "b.pdf")]
    _, scan, client = do_scan(state, gone, (full, DELTA_LINK_2))
    assert client.calls == [DELTA_LINK, "/groups/t1/drive/root/delta"]
    assert [c.name for c in scan.new_files()] == ["b.pdf"]  # a.pdf zaten biliniyor


def test_other_graph_errors_propagate(state):
    baselined(state)
    with pytest.raises(GraphError):
        do_scan(state, GraphError(403, "Forbidden", "no"))


def test_root_level_file_has_empty_folder(state):
    baselined(state)
    _, scan, _ = do_scan(state, ([file_item("i1", "a.pdf", folder="")], DELTA_LINK_2))
    assert scan.new_files()[0].folder == ""
