"""`run` komutunun akışı: sınıfları eşitle, dosyaları tara, bildir, durumu kaydet."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from .classes import sync_teams
from .config import Config
from .errors import AuthRequired, GraphError, NotifyError
from .files import FileTracker, build_notifications
from .graph import GraphClient
from .notify import Notifier
from .state import State

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    teams: int = 0
    baselined: list[str] = field(default_factory=list)
    notifications: int = 0
    failed_teams: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed_teams


def run(cfg: Config, state: State, client: GraphClient, notifier: Notifier) -> RunResult:
    result = RunResult()
    tracker = FileTracker(client, state)
    excluded = {n.casefold() for n in cfg.files.exclude_classes}

    teams = sync_teams(client, state)
    result.teams = len(teams)

    for team_id, name in teams:
        if name.casefold() in excluded:
            continue
        try:
            scan = tracker.scan(team_id, name)
            for note in build_notifications(scan, notify_updates=cfg.files.notify_updates):
                notifier.send(
                    note.title, note.message,
                    priority=note.priority, tags=note.tags, click=note.click,
                )
                result.notifications += 1
            # Yalnızca bildirimler gittikten sonra: gönderim hata verirse bir
            # sonraki çalıştırmada aynı dosyalar yeniden bildirilir.
            tracker.commit(scan)
            if scan.baseline:
                result.baselined.append(name)
        except AuthRequired:
            raise
        except (GraphError, NotifyError) as exc:
            # Tek bir sınıftaki sorun (silinmiş grup, drive yok vb.) diğerlerini durdurmasın.
            log.error("Sınıf işlenemedi (%s): %s", team_id, exc)
            result.failed_teams.append(name)

    state.set_meta("last_run", datetime.now(cfg.tz).isoformat(timespec="seconds"))
    return result


def alert_auth_required(cfg: Config, state: State, notifier: Notifier) -> bool:
    """Oturum bittiyse günde en fazla bir kez telefona uyarı gönderir."""
    today = datetime.now(cfg.tz).date().isoformat()
    if state.get_meta("auth_alert_date") == today:
        return False
    notifier.send(
        "⚠️ Teams bildirimcisi",
        "Tekrar giriş yapman gerekiyor: `teams-notifier login`",
        priority=4,
        tags=("warning",),
    )
    state.set_meta("auth_alert_date", today)
    return True
