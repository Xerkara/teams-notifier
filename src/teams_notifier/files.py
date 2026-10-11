"""Sınıf dosyalarını delta ile izler: baseline, yeni/güncellenen dosya tespiti, bildirim metni.

İki aşamalı çalışır: `scan` Graph'tan okur ve durumu DEĞİŞTİRMEZ; bildirim başarıyla
gönderildikten sonra `commit` durumu yazar. Gönderim başarısız olursa bir sonraki
çalıştırmada aynı dosyalar yine "yeni" görünür, bildirim kaybolmaz.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .errors import GraphError
from .graph import GraphClient
from .state import State

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FileChange:
    item_id: str
    name: str
    folder: str  # kanal/klasör yolu, örn. "General/Hafta 1"
    ctag: str
    last_modified: str
    web_url: str
    author: str
    status: str  # 'new' | 'updated' | 'unchanged' | 'deleted'


@dataclass
class TeamScan:
    team_id: str
    team_name: str
    delta_link: str
    baseline: bool  # True ise bu bir ilk tarama: kaydedilir, bildirilmez
    changes: list[FileChange] = field(default_factory=list)

    def new_files(self) -> list[FileChange]:
        return [] if self.baseline else [c for c in self.changes if c.status == "new"]

    def updated_files(self) -> list[FileChange]:
        return [] if self.baseline else [c for c in self.changes if c.status == "updated"]


def _folder_of(item: dict) -> str:
    """parentReference.path ('/drives/b!x/root:/General/Hafta 1') -> 'General/Hafta 1'."""
    path = (item.get("parentReference") or {}).get("path") or ""
    _, sep, rest = path.partition("root:")
    return rest.strip("/") if sep else ""


def _person(item: dict, key: str) -> str:
    return ((item.get(key) or {}).get("user") or {}).get("displayName") or ""


def _is_file(item: dict) -> bool:
    # Klasörler, kök ve OneNote defterleri (package) atlanır.
    return "file" in item and "folder" not in item and "root" not in item


class FileTracker:
    def __init__(self, client: GraphClient, state: State):
        self._client = client
        self._state = state

    @staticmethod
    def _delta_path(team_id: str) -> str:
        return f"/groups/{team_id}/drive/root/delta"

    def _fetch(self, team_id: str) -> tuple[list[dict], str]:
        link = self._state.get_delta_link(team_id)
        if link:
            try:
                return self._client.delta(link)
            except GraphError as exc:
                if exc.status != 410:
                    raise
                # Delta token geçersiz: baştan tara. Bilinen dosyalar 'unchanged'
                # çıkacağı için bildirim tekrarlanmaz.
                log.warning("Delta token süresi dolmuş, baştan taranıyor: %s", team_id)
        return self._client.delta(self._delta_path(team_id))

    def scan(self, team_id: str, team_name: str) -> TeamScan:
        items, delta_link = self._fetch(team_id)

        # Delta aynı öğeyi birden çok kez döndürebilir; sonuncusu geçerli.
        latest: dict[str, dict] = {}
        for item in items:
            if item.get("id"):
                latest[item["id"]] = item

        scan = TeamScan(
            team_id=team_id,
            team_name=team_name,
            delta_link=delta_link,
            baseline=not self._state.is_team_baselined(team_id),
        )
        for item_id, item in latest.items():
            if "deleted" in item:
                scan.changes.append(
                    FileChange(item_id, item.get("name", ""), "", "", "", "", "", "deleted")
                )
                continue
            if not _is_file(item):
                continue
            ctag = item.get("cTag") or ""
            modified = item.get("lastModifiedDateTime") or ""
            status = self._state.peek_file(
                team_id, item_id, ctag=ctag, last_modified=modified
            )
            author = (
                _person(item, "createdBy")
                if status == "new"
                else _person(item, "lastModifiedBy") or _person(item, "createdBy")
            )
            scan.changes.append(
                FileChange(
                    item_id=item_id,
                    name=item.get("name") or "(adsız)",
                    folder=_folder_of(item),
                    ctag=ctag,
                    last_modified=modified,
                    web_url=item.get("webUrl") or "",
                    author=author,
                    status=status,
                )
            )
        return scan

    def commit(self, scan: TeamScan) -> None:
        """Taramayı kalıcı yapar. Bildirimler gönderildikten SONRA çağrılmalı."""
        for change in scan.changes:
            if change.status == "deleted":
                self._state.forget_file(scan.team_id, change.item_id)
            else:
                self._state.record_file(
                    scan.team_id,
                    change.item_id,
                    name=change.name,
                    parent_path=change.folder,
                    ctag=change.ctag,
                    last_modified=change.last_modified,
                    web_url=change.web_url,
                )
        self._state.set_delta_link(scan.team_id, scan.delta_link)
        if scan.baseline:
            self._state.mark_team_baselined(scan.team_id)


@dataclass(frozen=True)
class FileNotification:
    title: str
    message: str
    priority: int
    tags: tuple[str, ...]
    click: str | None


def _describe(change: FileChange, with_author: bool = True) -> str:
    where = f"{change.folder}/{change.name}" if change.folder else change.name
    if with_author and change.author:
        return f"{where} — {change.author}"
    return where


def _build(
    team: str, files: list[FileChange], *, icon: str, noun: str, priority: int, tag: str
) -> FileNotification:
    if len(files) == 1:
        f = files[0]
        title = f"{icon} {team} — {noun.format(n='')}"
        lines = [f.name]
        if f.folder:
            lines.append(f"Klasör: {f.folder}")
        if f.author:
            lines.append(f"Kişi: {f.author}")
        message, click = "\n".join(lines), f.web_url or None
    else:
        title = f"{icon} {team} — {noun.format(n=f'{len(files)} ')}".strip()
        message = "\n".join("• " + _describe(f) for f in files)
        click = None
    return FileNotification(title, message, priority, (tag,), click)


def build_notifications(scan: TeamScan, *, notify_updates: bool = False) -> list[FileNotification]:
    """Bir sınıf için bildirimleri hazırlar: yeni dosyalar tek bildirimde gruplanır."""
    out: list[FileNotification] = []
    new = scan.new_files()
    if new:
        out.append(
            _build(scan.team_name, new, icon="📁", noun="{n}yeni dosya", priority=3, tag="file_folder")
        )
    updated = scan.updated_files() if notify_updates else []
    if updated:
        out.append(
            _build(
                scan.team_name, updated, icon="🔄", noun="{n}dosya güncellendi",
                priority=2, tag="arrows_counterclockwise",
            )
        )
    return out
