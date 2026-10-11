"""Kullanıcının üye olduğu sınıfların (Teams ekipleri) listesi."""
from __future__ import annotations

from .graph import GraphClient
from .state import State


def sync_teams(client: GraphClient, state: State) -> list[tuple[str, str]]:
    """Güncel sınıf listesini çeker, state'e işler; [(team_id, ad)] döner."""
    teams: list[tuple[str, str]] = []
    for item in client.get_paged("/me/joinedTeams"):
        team_id = item.get("id")
        if not team_id:
            continue
        name = item.get("displayName") or team_id
        state.upsert_team(team_id, name)
        teams.append((team_id, name))
    return teams
