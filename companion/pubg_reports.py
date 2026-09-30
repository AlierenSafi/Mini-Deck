"""Post-match reports; local calendar days, roster relationships, no extra API calls."""

from datetime import datetime
import json
from pathlib import Path

HISTORY = Path(__file__).with_name("pubg-history.json")


def participant(stats):
    return {
        "name": stats.get("name", "?"),
        "kills": int(stats.get("kills", 0)),
        "assists": int(stats.get("assists", 0)),
        "damage": round(stats.get("damageDealt", 0)),
        "rank": int(stats.get("winPlace", 0)),
    }


def extract(match, account, match_id):
    included = match.get("included", [])
    people = {p.get("id"): p for p in included if p.get("type") == "participant"}
    own = next(
        (p for p in people.values() if p["attributes"]["stats"].get("playerId") == account), None
    )
    if own is None:
        return None
    stats = own["attributes"]["stats"]
    attrs = match["data"]["attributes"]
    ids = [own.get("id")]
    for roster in included:
        if roster.get("type") != "roster":
            continue
        members = [
            p["id"] for p in roster.get("relationships", {}).get("participants", {}).get("data", [])
        ]
        if own.get("id") in members:
            ids = members
            break
    team = [participant(people[i]["attributes"]["stats"]) for i in ids if i in people]
    team.sort(key=lambda p: (p["name"] != stats.get("name"), p["name"].casefold()))
    return dict(
        participant(stats),
        id=match_id,
        created=attrs["createdAt"],
        map=attrs.get("mapName", ""),
        mode=attrs.get("gameMode", ""),
        survival=round(stats.get("timeSurvived", 0)),
        team=team,
    )


def aggregate(matches, now=None):
    now = now or datetime.now().astimezone()

    def today(m):
        try:
            return (
                datetime.fromisoformat(m["created"].replace("Z", "+00:00"))
                .astimezone(now.tzinfo)
                .date()
                == now.date()
            )
        except (KeyError, ValueError):
            return False

    daily = [m for m in matches if today(m)]
    recent = sorted(matches, key=lambda m: m["created"], reverse=True)[:10]
    return {
        "history": recent,
        "daily": {
            "date": now.date().isoformat(),
            "matches": len(daily),
            "wins": sum(m["rank"] == 1 for m in daily),
            "kills": sum(m["kills"] for m in daily),
            "assists": sum(m.get("assists", 0) for m in daily),
            "damage": sum(m["damage"] for m in daily),
        },
    }


def archive(player, matches, path=HISTORY):
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stored = {}
    if stored.get("player") != player:
        stored = {"player": player, "matches": []}
    by_id = {m["id"]: m for m in stored["matches"]}
    by_id.update({m["id"]: m for m in matches if m})
    rows = sorted(by_id.values(), key=lambda m: m["created"], reverse=True)[:2000]
    value = {"player": player, "matches": rows}
    if value != stored:
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        temp.replace(path)
    return rows


def report_lines(match):
    summary = match.get("summary") or {}
    team = summary.get("team", [])
    pages = []
    for start in (0, 2):
        rows = []
        for index in range(start, start + 2):
            if index < len(team):
                p = team[index]
                rows += [p["name"], f"K {p['kills']}  A {p['assists']}", f"HASAR {p['damage']}"]
            else:
                rows += ["OYUNCU YOK", "", ""]
        pages.append(rows)
    d = match.get("daily", {})
    pages.append(
        [
            d.get("date", ""),
            f"MAC {d.get('matches', 0)}",
            f"ZAFER {d.get('wins', 0)}",
            f"OLDURME {d.get('kills', 0)}",
            f"ASIST {d.get('assists', 0)}",
            f"HASAR {d.get('damage', 0)}",
        ]
    )
    recent = match.get("history", [])
    avg = round(sum(m["damage"] for m in recent) / len(recent)) if recent else 0
    pages.append([f"{len(recent)} MAC / OLDURME", f"ORT HASAR {avg}", "", "", "", ""])
    if match.get("status") != 1:
        pages = [["VERI BEKLENIYOR"] + [""] * 5 for _ in pages]
    return pages
