#!/usr/bin/env python3
"""Pull everything Nine Lives needs from Squiggle and write it to data/.

Run by GitHub Actions on a schedule. The site never calls an API itself -- the
browser only ever reads the JSON this produces.

The important guarantee: a failed run must never blank the page. On any error
data/state.json is left exactly as it was and only data/status.json is
rewritten, so the site keeps rendering the last good numbers with their real
age showing.
"""

import json
import os
import sys
import traceback
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import model
from squiggle import SquiggleError, cached_query, query

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
CACHE = os.path.join(DATA, "cache")

STATE_PATH = os.path.join(DATA, "state.json")
HISTORY_PATH = os.path.join(DATA, "history.json")
STATUS_PATH = os.path.join(DATA, "status.json")

SEASON = int(os.environ.get("NINE_LIVES_SEASON", datetime.now(timezone.utc).year))
CLUB = os.environ.get("NINE_LIVES_CLUB", "Geelong")

# Chris Scott's first season in charge of Geelong. A matter of record, not a
# statistic -- every number in the panel it labels is computed from match data.
SCOTT_ERA_FROM = 2011

SQUIGGLE_AGGREGATE = 8   # Squiggle's consensus of the public models it tracks
SQUIGGLE_PUNTERS = 5     # derived from bookmaker pricing -- the market's view

HISTORY_LIMIT = 2000
HISTORY_MIN_CHANGE = 0.0001
HISTORY_MAX_GAP_SECONDS = 6 * 3600
FAILURE_ALARM_THRESHOLD = 4   # ~2 hours of failed half-hourly runs


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return fallback


def write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, path)


# --- Chris Scott era ------------------------------------------------------

def scott_era_record(club, club_id, live_teams):
    """Every final Geelong have played since 2011, counted from match records.

    Past seasons never change, so they're cached on disk and fetched once. Only
    the current season is re-pulled each run.
    """
    finals = []
    for year in range(SCOTT_ERA_FROM, SEASON + 1):
        if year == SEASON:
            games = query("games", year=year, team=club_id)
        else:
            games = cached_query(
                os.path.join(CACHE, f"games-{club}-{year}.json"),
                "games", year=year, team=club_id,
            )
        finals.extend(
            g for g in games
            if g.get("is_final") and g.get("complete") == 100 and g.get("winner")
        )

    def tally(rows):
        wins = sum(1 for g in rows if g["winner"] == club)
        return {"played": len(rows), "won": wins, "lost": len(rows) - wins}

    def stage_of(game):
        name = (game.get("roundname") or "").lower()
        if game.get("is_grand_final") or "grand final" in name:
            return "Grand Final"
        if "preliminary" in name:
            return "Preliminary final"
        if "semi" in name:
            return "Semi-final"
        if "qualifying" in name:
            return "Qualifying final"
        # Squiggle labels the opening weekend "Finals Week 1" without saying
        # whether a given game was a qualifying or an elimination final, so
        # don't pretend to know which.
        return "Week 1 final"

    by_stage, by_venue, by_opponent, by_year = {}, {}, {}, {}
    for game in finals:
        opponent = game["ateam"] if game["hteam"] == club else game["hteam"]
        by_stage.setdefault(stage_of(game), []).append(game)
        by_venue.setdefault(
            model.canonical_venue(game.get("venue")) or "Unknown", []).append(game)
        by_opponent.setdefault(opponent, []).append(game)
        by_year.setdefault(game["year"], []).append(game)

    margins = [
        (g["hscore"] - g["ascore"]) * (1 if g["hteam"] == club else -1)
        for g in finals
    ]

    return {
        "from_year": SCOTT_ERA_FROM,
        "to_year": SEASON,
        "overall": tally(finals),
        "seasons_playing_finals": len(by_year),
        "grand_finals_reached": len(by_stage.get("Grand Final", [])),
        "average_margin": round(sum(margins) / len(margins), 1) if margins else None,
        "by_stage": [
            {"stage": stage, **tally(rows)}
            for stage, rows in sorted(by_stage.items(), key=lambda kv: -len(kv[1]))
        ],
        "by_venue": [
            {"venue": venue, **tally(rows)}
            for venue, rows in sorted(by_venue.items(), key=lambda kv: -len(kv[1]))
        ],
        # Only clubs still alive in this year's series -- the ones that matter.
        "against_live_teams": [
            {"team": team, **tally(by_opponent.get(team, []))}
            for team in live_teams if team != club
        ],
        "recent": [
            {
                "year": g["year"],
                "stage": stage_of(g),
                "opponent": g["ateam"] if g["hteam"] == club else g["hteam"],
                "result": "W" if g["winner"] == club else "L",
                "margin": (g["hscore"] - g["ascore"]) * (1 if g["hteam"] == club else -1),
                "venue": model.canonical_venue(g.get("venue")),
            }
            for g in sorted(finals, key=lambda g: g.get("unixtime") or 0, reverse=True)[:8]
        ],
    }


# --- Fixture handling -----------------------------------------------------

def fixture_provisionality(game, finals_games):
    """Flag fixtures the AFL hasn't actually confirmed yet.

    Squiggle carries a placeholder for finals whose details aren't announced --
    the AFL only sets each week's venues and times once the previous week
    finishes. Two tells, both self-clearing once the real fixture lands:
    the venue isn't the home side's finals ground, or two games in the same
    round share an identical kickoff.
    """
    reasons = []
    home = game.get("hteam")
    expected = model.FINALS_HOME_VENUE.get(home)
    if home and expected and game.get("venue") and game["venue"] != expected:
        reasons.append(
            f"venue shown is {game['venue']}, but {home} would host at {expected}"
        )
    clashes = [
        g for g in finals_games
        if g["id"] != game["id"]
        and g.get("round") == game.get("round")
        and g.get("date") == game.get("date")
    ]
    if clashes:
        reasons.append("another game in this round carries the identical kickoff time")
    return reasons


def collect():
    teams = query("teams", year=SEASON)
    team_ids = {t["name"]: t["id"] for t in teams}
    if CLUB not in team_ids:
        raise SquiggleError(f"{CLUB} not in Squiggle's team list for {SEASON}")

    standings = query("standings", year=SEASON)
    games = query("games", year=SEASON)
    aggregate_tips = query("tips", year=SEASON, source=SQUIGGLE_AGGREGATE)
    market_tips = query("tips", year=SEASON, source=SQUIGGLE_PUNTERS)
    power_rows = query("power", year=SEASON, source=SQUIGGLE_AGGREGATE)
    sources = query("sources")

    powers = {row["team"]: float(row["power"]) for row in power_rows}
    tips_by_game = {t["gameid"]: t for t in aggregate_tips if t.get("gameid")}
    market_by_game = {t["gameid"]: t for t in market_tips if t.get("gameid")}

    calibration = model.fit_calibration(games, aggregate_tips, powers)

    seeds = {row["rank"]: row["name"] for row in standings}
    finals_games = [g for g in games if g.get("is_final")]
    if not finals_games:
        raise SquiggleError(f"no finals fixtured for {SEASON} yet")

    bracket = model.Bracket(seeds, finals_games, tips_by_game)
    outcomes = model.enumerate_bracket(bracket, calibration, powers)
    report = model.premiership_report(outcomes, CLUB)
    field = model.field_probabilities(outcomes)
    live_teams = [row["team"] for row in field]

    # --- next fixture ---
    upcoming = sorted(
        (g for g in games
         if g.get("complete") != 100 and CLUB in (g.get("hteam"), g.get("ateam"))),
        key=lambda g: g.get("unixtime") or 0,
    )
    next_fixture = None
    if upcoming:
        game = upcoming[0]
        home, away = game["hteam"], game["ateam"]
        opponent = away if home == CLUB else home
        published, _ = bracket.published_probability(home, away)
        club_probability = None
        if published is not None:
            club_probability = published if home == CLUB else 1.0 - published
        next_fixture = {
            "game_id": game["id"],
            "stage": game.get("roundname"),
            "home": home,
            "away": away,
            "opponent": opponent,
            "club_is_home": home == CLUB,
            "venue": game.get("venue"),
            "start_utc": datetime.fromtimestamp(
                game["unixtime"], tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            "local_time": game.get("localtime"),
            "timezone": game.get("tz"),
            "club_win_probability": round(club_probability, 6) if club_probability is not None else None,
            "provisional_reasons": fixture_provisionality(game, finals_games),
        }

    # --- market view of the same fixture ---
    market = None
    if next_fixture:
        tip = market_by_game.get(next_fixture["game_id"])
        if tip:
            try:
                home_confidence = float(tip["hconfidence"]) / 100.0
                market = {
                    "club_win_probability": round(
                        home_confidence if next_fixture["club_is_home"]
                        else 1.0 - home_confidence, 6),
                    "expected_margin_to_club": round(
                        float(tip["hmargin"]) * (1 if next_fixture["club_is_home"] else -1), 2),
                    "updated": tip.get("updated"),
                    "source": "Squiggle 'Punters' source, derived from bookmaker pricing",
                }
            except (TypeError, ValueError, KeyError):
                market = None

    # --- bracket for display ---
    known = outcomes["known"]
    display_bracket = []
    state = {}
    for node in model.NODE_ORDER:
        pair = bracket.participants(node, state)
        entry = {"node": node, "stage": model.NODE_STAGE[node]}
        if pair:
            home, away = pair
            game = bracket.game_for(home, away)
            entry.update({
                "home": home, "away": away,
                "venue": (game or {}).get("venue") or bracket.venue_for(node, home),
                "date": (game or {}).get("date"),
                "complete": bool(game and game.get("complete") == 100),
                "home_score": (game or {}).get("hscore"),
                "away_score": (game or {}).get("ascore"),
                "winner": known.get(node),
                "involves_club": CLUB in (home, away),
                "provisional_reasons": fixture_provisionality(game, finals_games) if game and game.get("complete") != 100 else [],
            })
        else:
            entry.update({
                "home": None, "away": None,
                "club_appearance_probability": round(
                    outcomes["appear"][node].get(CLUB, 0.0), 6),
            })
        if node in known:
            state[node] = known[node]
        display_bracket.append(entry)

    ladder = [
        {"rank": r["rank"], "team": r["name"], "wins": r["wins"], "losses": r["losses"],
         "draws": r["draws"], "percentage": round(r["percentage"], 1), "points": r["pts"]}
        for r in sorted(standings, key=lambda r: r["rank"])
    ]

    return {
        "generated_at": now_iso(),
        "season": SEASON,
        "club": CLUB,
        "source": {
            "name": "Squiggle API",
            "url": "https://api.squiggle.com.au/",
            "models_aggregated": len(sources),
            "note": "Squiggle publishes no premiership probability. "
                    "The headline is derived -- see method.",
        },
        "headline": report,
        "method": {
            "description": (
                "Every remaining path through the finals bracket is enumerated "
                "exhaustively and the paths ending in a premiership are summed. "
                "Fixtures Squiggle has already tipped use its published consensus "
                "verbatim; the rest use a conversion fitted to Squiggle's own "
                "published margins and confidences this season."
            ),
            "calibration": calibration.as_dict(),
        },
        "next_fixture": next_fixture,
        "market": market,
        "bracket": display_bracket,
        "field": field,
        "scott_era": scott_era_record(CLUB, team_ids[CLUB], live_teams),
        "ladder": ladder,
    }


def update_history(state):
    history = read_json(HISTORY_PATH, [])
    if not isinstance(history, list):
        history = []
    probability = state["headline"]["probability"]
    entry = {
        "at": state["generated_at"],
        "probability": probability,
        "market_next_game": (state.get("market") or {}).get("club_win_probability"),
        "next_opponent": (state.get("next_fixture") or {}).get("opponent"),
    }

    if history:
        previous = history[-1]
        moved = abs(previous.get("probability", 0) - probability) >= HISTORY_MIN_CHANGE
        try:
            gap = (datetime.fromisoformat(entry["at"])
                   - datetime.fromisoformat(previous["at"])).total_seconds()
        except (ValueError, KeyError):
            gap = HISTORY_MAX_GAP_SECONDS + 1
        # Half-hourly runs would otherwise bloat the repo with identical rows.
        if not moved and gap < HISTORY_MAX_GAP_SECONDS:
            return history
    history.append(entry)
    return history[-HISTORY_LIMIT:]


def main():
    status = read_json(STATUS_PATH, {})
    status["last_attempt"] = now_iso()
    status["runs"] = status.get("runs", 0) + 1

    try:
        state = collect()
    except Exception as exc:                      # noqa: BLE001 - any failure is a stale-data event
        status["consecutive_failures"] = status.get("consecutive_failures", 0) + 1
        status["last_error"] = f"{type(exc).__name__}: {exc}"
        write_json(STATUS_PATH, status)
        print(f"fetch failed: {status['last_error']}", file=sys.stderr)
        traceback.print_exc()
        print("data/state.json left untouched -- the site will show stale data.",
              file=sys.stderr)
        # Don't redden the Actions log for a single blip, but do shout if the
        # source has been unreachable for a couple of hours.
        return 1 if status["consecutive_failures"] >= FAILURE_ALARM_THRESHOLD else 0

    write_json(HISTORY_PATH, update_history(state))
    write_json(STATE_PATH, state)
    status["last_success"] = state["generated_at"]
    status["consecutive_failures"] = 0
    status["last_error"] = None
    write_json(STATUS_PATH, status)

    headline = state["headline"]["probability"]
    print(f"{CLUB} premiership probability: {headline:.2%}")
    fixture = state.get("next_fixture")
    if fixture:
        print(f"next: {fixture['stage']} v {fixture['opponent']} at {fixture['venue']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
