"""Aşama 1 — İzin testi.

Device code ile giriş yapar ve Graph çağrılarının hangisinin çalıştığını raporlar.
Token yalnızca bellekte tutulur, diske yazılmaz.

Kullanım:
    python scripts/permission_test.py --client-id <ID> [--with-posts]
Varsayılan client ID: Microsoft Graph Command Line Tools (Seçenek B).
"""
from __future__ import annotations

import argparse
import sys

import msal
import requests

GRAPH = "https://graph.microsoft.com/v1.0"
GRAPH_CLI_CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"

BASE_SCOPES = [
    "User.Read",
    "Team.ReadBasic.All",
    "Files.Read.All",
    "EduAssignments.ReadBasic",
]
POST_SCOPES = ["ChannelMessage.Read.All"]


def login(app: msal.PublicClientApplication, scopes: list[str]) -> dict:
    flow = app.initiate_device_flow(scopes=scopes)
    if "user_code" not in flow:
        return {"error": flow.get("error"), "error_description": flow.get("error_description")}
    print("\n" + "=" * 60)
    print(flow["message"])
    print("=" * 60, flush=True)
    return app.acquire_token_by_device_flow(flow)


def call(token: str, path: str, label: str) -> dict | None:
    r = requests.get(
        f"{GRAPH}{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if r.ok:
        print(f"  [OK ] {label}  ({r.status_code})")
        return r.json()
    try:
        err = r.json().get("error", {})
        detail = f"{err.get('code')}: {err.get('message')}"
    except ValueError:
        detail = r.text[:200]
    print(f"  [HATA] {label}  ({r.status_code}) -> {detail}")
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-id", default=GRAPH_CLI_CLIENT_ID)
    ap.add_argument("--tenant", default="organizations")
    ap.add_argument("--with-posts", action="store_true", help="ChannelMessage.Read.All iznini de dene")
    ap.add_argument("--scopes", help="Virgülle ayrılmış izin listesi (varsayılanı geçersiz kılar)")
    args = ap.parse_args()

    app = msal.PublicClientApplication(
        args.client_id, authority=f"https://login.microsoftonline.com/{args.tenant}"
    )

    if args.scopes:
        scopes = [s.strip() for s in args.scopes.split(",") if s.strip()]
    else:
        scopes = BASE_SCOPES + (POST_SCOPES if args.with_posts else [])
    print(f"Client ID : {args.client_id}")
    print(f"İstenen izinler: {', '.join(scopes)}")
    result = login(app, scopes)

    if "access_token" not in result:
        print("\nGiriş BAŞARISIZ:")
        print(f"  {result.get('error')}: {result.get('error_description')}")
        print("\nAşama 1 durma noktası: temel izinler alınamadı. B planını konuşalım.")
        return 2

    token = result["access_token"]
    print(f"\nGiriş başarılı. Verilen izinler: {result.get('scope')}\n")

    print("Çağrılar:")
    me = call(token, "/me", "GET /me")
    if me:
        print(f"      hesap: {me.get('userPrincipalName')}")

    teams = call(token, "/me/joinedTeams", "GET /me/joinedTeams")
    team_list = (teams or {}).get("value", [])
    print(f"      sınıf/takım sayısı: {len(team_list)}")
    for t in team_list:
        print(f"      - {t.get('displayName')}")

    classes = call(token, "/education/me/classes", "GET /education/me/classes")
    if classes:
        print(f"      eğitim sınıfı sayısı: {len(classes.get('value', []))}")

    if team_list:
        first = team_list[0]
        print(f"\n  İlk sınıf üzerinde deneme: {first.get('displayName')}")
        tid = first["id"]
        call(token, f"/groups/{tid}/drive", "GET /groups/{id}/drive")
        d = call(token, f"/groups/{tid}/drive/root/delta?$top=5", "GET /groups/{id}/drive/root/delta")
        if d:
            print(f"      ilk sayfada öğe: {len(d.get('value', []))}")
        call(token, f"/teams/{tid}/channels", "GET /teams/{id}/channels")
        if args.with_posts:
            ch = call(token, f"/teams/{tid}/channels", "(kanal listesi, post testi için)")
            chans = (ch or {}).get("value", [])
            if chans:
                call(
                    token,
                    f"/teams/{tid}/channels/{chans[0]['id']}/messages?$top=1",
                    "GET /teams/{id}/channels/{id}/messages",
                )

    asg = call(token, "/education/me/assignments", "GET /education/me/assignments")
    asg_list = (asg or {}).get("value", [])
    print(f"      ödev sayısı: {len(asg_list)}")
    if asg_list:
        a = asg_list[0]
        call(
            token,
            f"/education/classes/{a['classId']}/assignments/{a['id']}/submissions",
            "GET .../assignments/{id}/submissions",
        )

    print("\nBitti. Yukarıdaki [HATA] satırlarını (özellikle 403 / consent) bana ilet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
