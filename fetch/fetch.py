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

import case
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
        # Ordered by how we have gone against them rather than by how good they
        # are: a supporter leads with the scalps, not with the bogey side.
        "against_live_teams": sorted(
            ({"team": team, **tally(by_opponent.get(team, []))}
             for team in live_teams if team != club),
            key=lambda row: (
                0 if row["won"] > row["lost"] else (1 if not row["played"] else 2),
                -(row["won"] - row["lost"]),
                -row["won"],
            ),
        ),
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


def current_win_streak(games, club):
    """Consecutive wins running into this week, and when they last lost."""
    played = sorted(
        (g for g in games
         if g.get("complete") == 100 and club in (g.get("hteam"), g.get("ateam"))),
        key=lambda g: g.get("unixtime") or 0,
        reverse=True,
    )
    streak = 0
    last_loss = None
    for game in played:
        if game.get("winner") == club:
            streak += 1
        else:
            last_loss = game
            break
    note = None
    if last_loss:
        opponent = (last_loss["ateam"] if last_loss["hteam"] == club
                    else last_loss["hteam"])
        note = f"round {last_loss['round']} against {opponent}"
    return streak, note


def _season_summary(year):
    """Per-club counters for one season, cached in a compact form.

    Caching the raw fixture for sixteen seasons would put close to two megabytes
    of JSON in the repository for numbers that reduce to a handful of counters
    per club. Completed seasons never change, so the summary is derived once and
    kept; the current season is recomputed every run.
    """
    path = os.path.join(CACHE, f"summary-v2-{year}.json")
    if year < SEASON and os.path.exists(path):
        cached = read_json(path, None)
        if cached:
            return cached

    games = query("games", year=year)
    summary = {}

    def row(team):
        return summary.setdefault(team, {
            "played": 0, "won": 0, "finals": 0, "finals_won": 0,
            "grand_finals": 0, "flags": 0, "played_finals": 0,
        })

    for game in games:
        if game.get("complete") != 100 or not game.get("winner"):
            continue
        for team in (game["hteam"], game["ateam"]):
            entry = row(team)
            entry["played"] += 1
            if game.get("is_final"):
                entry["finals"] += 1
                entry["played_finals"] = 1
            if game.get("is_grand_final"):
                entry["grand_finals"] += 1
        row(game["winner"])["won"] += 1
        if game.get("is_final"):
            row(game["winner"])["finals_won"] += 1
        if game.get("is_grand_final"):
            row(game["winner"])["flags"] += 1

    if year < SEASON:
        write_json(path, summary)
    return summary


PRECEDENT_FROM = 2000        # as far back as Squiggle's archive reaches


FINALS_HISTORY_FROM = 2000    # the full reach of Squiggle's archive


def finals_head_to_head(club, club_id, order):
    """Every final we have played against the sides still standing.

    Deliberately wider than the Chris Scott era: a 69-point semi-final win over
    Fremantle in 2010 is still a thing that happened, and a supporter wants the
    whole story rather than the slice that starts in 2011.
    """
    meetings = {team: [] for team in order}

    for year in range(FINALS_HISTORY_FROM, SEASON + 1):
        if year == SEASON:
            games = query("games", year=year, team=club_id)
        else:
            games = cached_query(
                os.path.join(CACHE, f"games-{club}-{year}.json"),
                "games", year=year, team=club_id)

        for game in games:
            if not (game.get("is_final") and game.get("complete") == 100):
                continue
            at_home = game["hteam"] == club
            opponent = game["ateam"] if at_home else game["hteam"]
            if opponent not in meetings:
                continue
            meetings[opponent].append({
                "year": game["year"],
                "unixtime": game.get("unixtime") or 0,
                "stage": game.get("roundname"),
                "venue": model.canonical_venue(game.get("venue")),
                "at_home": at_home,
                "margin": (game["hscore"] - game["ascore"]) * (1 if at_home else -1),
                "won": game.get("winner") == club,
                "scott_era": game["year"] >= SCOTT_ERA_FROM,
            })

    rows = []
    for team in order:
        games = sorted(meetings[team], key=lambda g: -g["unixtime"])
        won = sum(1 for g in games if g["won"])
        wins = [g for g in games if g["won"]]
        rows.append({
            "team": team,
            "played": len(games),
            "won": won,
            "lost": len(games) - won,
            "win_rate": round(won / len(games), 4) if games else None,
            "biggest_win": max(wins, key=lambda g: g["margin"]) if wins else None,
            "most_recent": games[0] if games else None,
            "meetings": games,
        })
    return {"from_year": FINALS_HISTORY_FROM, "to_year": SEASON, "teams": rows}


def _precedent_season(year):
    """What a season's finals say about sides in our position.

    Reduced to a few facts per year and cached, rather than keeping the whole
    fixture: who won the flag, where they finished, and how the semi-finals
    went. In a semi-final the home side is the beaten qualifying finalist and
    the away side is the elimination-final winner, which is exactly the seat
    Geelong are sitting in.
    """
    path = os.path.join(CACHE, f"precedent-v2-{year}.json")
    if year < SEASON and os.path.exists(path):
        cached = read_json(path, None)
        if cached:
            return cached

    games = query("games", year=year)
    ladder, semis, decider = {}, [], None

    for game in games:
        if game.get("complete") != 100:
            continue
        if not game.get("is_final"):
            for team, scored, conceded in (
                (game["hteam"], game["hscore"], game["ascore"]),
                (game["ateam"], game["ascore"], game["hscore"]),
            ):
                row = ladder.setdefault(team, {"points": 0, "for": 0, "against": 0})
                row["for"] += scored
                row["against"] += conceded
                row["points"] += 4 if game.get("winner") == team else (
                    0 if game.get("winner") else 2)
        else:
            name = (game.get("roundname") or "").lower()
            if game.get("is_grand_final"):
                decider = game
            elif "semi" in name:
                semis.append(game)

    ordered = sorted(ladder, key=lambda t: (
        -ladder[t]["points"], -(ladder[t]["for"] / max(ladder[t]["against"], 1))))

    grand_finalists = [decider["hteam"], decider["ateam"]] if decider else []
    premier = (decider or {}).get("winner")
    premier_path = []      # not `path`: that name is the cache file above
    if premier:
        for game in sorted(
            (g for g in games
             if g.get("is_final") and g.get("complete") == 100
             and premier in (g.get("hteam"), g.get("ateam"))),
            key=lambda g: g.get("unixtime") or 0,
        ):
            at_home = game["hteam"] == premier
            premier_path.append({
                "stage": game.get("roundname"),
                "opponent": game["ateam"] if at_home else game["hteam"],
                "at_home": at_home,
                "venue": game.get("venue"),
                "margin": (game["hscore"] - game["ascore"]) * (1 if at_home else -1),
            })

    result = {
        "premier_path": premier_path,
        "year": year,
        "premier": (decider or {}).get("winner"),
        "premier_position": (
            ordered.index(decider["winner"]) + 1
            if decider and decider.get("winner") in ordered else None),
        "grand_finalists": grand_finalists,
        "semis": [
            {"home": g["hteam"], "away": g["ateam"], "winner": g.get("winner")}
            for g in semis
        ],
    }
    if year < SEASON:
        write_json(path, result)
    return result


def precedent_for_our_position(club, ladder_position):
    """Sides who have stood exactly here before, and what happened to them."""
    seasons = [_precedent_season(y) for y in range(PRECEDENT_FROM, SEASON)]

    from_here, semi_played, semi_won = [], 0, 0
    winners_to_grand_final, winners_to_flag = 0, 0

    for season in seasons:
        if season["premier"] and season["premier_position"]:
            if season["premier_position"] >= (ladder_position or 5):
                from_here.append({
                    "year": season["year"],
                    "team": season["premier"],
                    "position": season["premier_position"],
                    "path": season.get("premier_path") or [],
                })
        for semi in season["semis"]:
            if not semi["winner"]:
                continue
            semi_played += 1
            # The away side is the elimination-final winner: our seat.
            if semi["winner"] == semi["away"]:
                semi_won += 1
            if semi["winner"] in season["grand_finalists"]:
                winners_to_grand_final += 1
                if semi["winner"] == season["premier"]:
                    winners_to_flag += 1

    from_here.sort(key=lambda row: -row["year"])
    return {
        "from_year": PRECEDENT_FROM,
        "to_year": SEASON - 1,
        "seasons": len(seasons),
        "ladder_position": ladder_position,
        "flags_from_here": from_here,
        "semi_finals": semi_played,
        "semi_finals_won_by_visitor": semi_won,
        "visitor_win_rate": round(semi_won / semi_played, 4) if semi_played else None,
        "semi_winners_to_grand_final": winners_to_grand_final,
        "semi_winners_to_flag": winners_to_flag,
        "flag_rate_after_winning_semi": (
            round(winners_to_flag / semi_played, 4) if semi_played else None),
    }


def dominance_since(from_year, club):
    """How the club stacks up against the whole competition since `from_year`.

    The Chris Scott era in league-wide context: not just what Geelong have done,
    but whether anybody has done it better.
    """
    totals = {}
    for year in range(from_year, SEASON + 1):
        for team, counters in _season_summary(year).items():
            entry = totals.setdefault(team, {
                "played": 0, "won": 0, "finals": 0, "finals_won": 0,
                "grand_finals": 0, "flags": 0, "finals_series": 0,
            })
            for key in ("played", "won", "finals", "finals_won",
                        "grand_finals", "flags"):
                entry[key] += counters.get(key, 0)
            entry["finals_series"] += counters.get("played_finals", 0)

    table = []
    for team, entry in totals.items():
        if not entry["played"]:
            continue
        table.append({
            "team": team,
            "played": entry["played"],
            "won": entry["won"],
            "lost": entry["played"] - entry["won"],
            "win_rate": round(entry["won"] / entry["played"], 4),
            "finals": entry["finals"],
            "finals_won": entry["finals_won"],
            "finals_win_rate": round(
                entry["finals_won"] / entry["finals"], 4) if entry["finals"] else 0.0,
            "finals_series": entry["finals_series"],
            "grand_finals": entry["grand_finals"],
            "flags": entry["flags"],
        })
    table.sort(key=lambda row: -row["win_rate"])

    def position_of(value, key):
        """Competition ranking: clubs level on a count share the better place.

        Two clubs on three premierships are both third, not third and fourth,
        and a rank computed one way while the list is ordered another is how
        you end up telling someone they are third in a table that shows them
        fourth.
        """
        return 1 + sum(1 for row in table if row[key] > value)

    def rank_by(key):
        us_row = next((row for row in table if row["team"] == club), None)
        return position_of(us_row[key], key) if us_row else None

    us = next((row for row in table if row["team"] == club), None)
    runner_up = next((row for row in table if row["team"] != club), None)

    def leaderboard(key, label, unit):
        ordered = sorted(table, key=lambda row: (-row[key], row["team"]))
        top = ordered[:4]
        if not any(row["team"] == club for row in top):
            us_row = next((r for r in ordered if r["team"] == club), None)
            if us_row:
                top = top[:3] + [us_row]
        return {
            "key": key,
            "label": label,
            "unit": unit,
            "our_rank": rank_by(key),
            "rows": [
                {
                    "team": row["team"],
                    "value": row[key],
                    "position": position_of(row[key], key),
                    "shared": sum(1 for other in table
                                  if other[key] == row[key]) > 1,
                }
                for row in top
            ],
        }

    return {
        "from_year": from_year,
        "to_year": SEASON,
        "club": us,
        "next_best": runner_up,
        "table": table[:8],
        "ranks": {
            "win_rate": rank_by("win_rate"),
            "finals": rank_by("finals"),
            "finals_won": rank_by("finals_won"),
            "finals_series": rank_by("finals_series"),
            "grand_finals": rank_by("grand_finals"),
            "flags": rank_by("flags"),
        },
        "leaderboards": [
            leaderboard("finals_series", "Finals campaigns", "seasons"),
            leaderboard("finals_won", "Finals won", "wins"),
            leaderboard("flags", "Premierships", "flags"),
        ],
        "clubs_compared": len(table),
    }


def season_series(games, club, opponent):
    """This season's meetings between the two, most recent first."""
    if not opponent:
        return []
    meetings = [
        g for g in games
        if g.get("complete") == 100 and not g.get("is_final")
        and {g.get("hteam"), g.get("ateam")} == {club, opponent}
    ]
    meetings.sort(key=lambda g: g.get("unixtime") or 0, reverse=True)
    rows = []
    for game in meetings:
        at_home = game["hteam"] == club
        rows.append({
            "round": game["round"],
            "venue": model.canonical_venue(game.get("venue")),
            "club_is_home": at_home,
            "our_score": game["hscore"] if at_home else game["ascore"],
            "their_score": game["ascore"] if at_home else game["hscore"],
            "margin": (game["hscore"] - game["ascore"]) * (1 if at_home else -1),
        })
    return rows


def last_defeat(games, team):
    """That side's most recent match, if they lost it."""
    played = sorted(
        (g for g in games
         if g.get("complete") == 100 and team in (g.get("hteam"), g.get("ateam"))),
        key=lambda g: g.get("unixtime") or 0,
        reverse=True,
    )
    if not played:
        return None
    game = played[0]
    if game.get("winner") == team:
        return None
    at_home = game["hteam"] == team
    return {
        "team": team,
        "opponent": game["ateam"] if at_home else game["hteam"],
        "margin": abs(game["hscore"] - game["ascore"]),
        "venue": model.canonical_venue(game.get("venue")),
    }


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

    # --- what the tipping panel makes of it ---
    # This is not a betting site. The bookmakers get one line among the experts,
    # not the headline.
    expert_tips = []
    if next_fixture:
        for tip in query("tips", game=next_fixture["game_id"]):
            try:
                home_confidence = float(tip["hconfidence"]) / 100.0
                margin = float(tip["hmargin"])
            except (TypeError, ValueError, KeyError):
                continue
            ours = home_confidence if next_fixture["club_is_home"] else 1 - home_confidence
            expert_tips.append({
                "source": tip.get("source"),
                "club_probability": round(ours, 6),
                "club_margin": round(margin * (1 if next_fixture["club_is_home"] else -1), 1),
                "is_market": tip.get("sourceid") == SQUIGGLE_PUNTERS,
                "is_consensus": tip.get("sourceid") == SQUIGGLE_AGGREGATE,
                "tips_club": ours > 0.5,
                "updated": tip.get("updated"),
            })
        # Consensus first, then the individual models, then the bookmakers
        # last. Sorting purely on who rates us highest floated the betting line
        # to the top of the page, which is the opposite of the intent.
        expert_tips.sort(key=lambda row: (
            0 if row["is_consensus"] else (2 if row["is_market"] else 1),
            -row["club_probability"],
        ))

    expert_panel = {
        "tips": expert_tips,
        "counted": len(expert_tips),
        "tipping_club": sum(1 for t in expert_tips if t["tips_club"]),
        "best": expert_tips[0] if expert_tips else None,
        "consensus": next((t for t in expert_tips if t["is_consensus"]), None),
        "market": next((t for t in expert_tips if t["is_market"]), None),
    }

    # --- the last Saturday in September ---
    decider = next((g for g in finals_games if g.get("is_grand_final")), None)
    if decider is None:
        decider = next((g for g in finals_games
                        if "grand final" in (g.get("roundname") or "").lower()), None)
    grand_final = None
    if decider and decider.get("unixtime"):
        grand_final = {
            "venue": decider.get("venue"),
            "start_utc": datetime.fromtimestamp(
                decider["unixtime"], tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            "local_time": decider.get("localtime"),
            "timezone": decider.get("tz"),
            "complete": decider.get("complete") == 100,
            "winner": decider.get("winner"),
        }

    # --- path to glory ---
    # Every scheduled final still to come, what it is worth to us, and -- if we
    # win this week -- who we would get next and where.
    games_by_id = {g["id"]: g for g in games}
    fixtures = model.fixture_impact(bracket, calibration, powers, CLUB)
    for row in fixtures:
        game = games_by_id.get(row["game_id"]) or {}
        row["start_utc"] = (
            datetime.fromtimestamp(game["unixtime"], tz=timezone.utc)
            .isoformat().replace("+00:00", "Z") if game.get("unixtime") else None
        )
        row["local_time"] = game.get("localtime")
        row["timezone"] = game.get("tz")
        row["provisional_reasons"] = fixture_provisionality(game, finals_games) if game else []
        row["away_probability"] = round(1.0 - row["home_probability"], 6)

        tip = market_by_game.get(row["game_id"])
        row["market_home_probability"] = None
        if tip:
            try:
                row["market_home_probability"] = round(float(tip["hconfidence"]) / 100.0, 6)
            except (TypeError, ValueError, KeyError):
                pass
        row.pop("unixtime", None)

        # Which way we want it to go. Below about a tenth of a point the
        # honest answer is that it makes no difference to us.
        if row["involves_club"]:
            row["we_want"] = CLUB
        elif row["club_swing"] * 100 < 0.1:
            row["we_want"] = None
        else:
            row["we_want"] = (row["home"]
                              if row["club_if_home_wins"] > row["club_if_away_wins"]
                              else row["away"])

    steps = report["steps"]
    live_now = [f for f in fixtures if f.get("in_progress")]
    path_to_glory = {
        "fixtures": fixtures,
        # Every probability on this page is a pre-match consensus. If a game is
        # being played right now, the numbers can't know about it.
        "games_in_progress": len(live_now),
        "live_disclaimer": (
            "A final is being played right now. Every probability here is the "
            "pre-match consensus and takes no account of the live score."
        ) if live_now else None,
        # The step after the one we're playing now: who we'd meet if we win.
        "if_we_win": steps[1] if len(steps) > 1 else None,
        "final_step": steps[-1] if steps else None,
        "playing_now": steps[0] if steps else None,
    }

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
            # How many more wins until we are in this one. Reads better than a
            # probability to anyone who just wants to know what has to happen.
            step_nodes = [step["node"] for step in steps]
            entry.update({
                "home": None, "away": None,
                "club_appearance_probability": round(
                    outcomes["appear"][node].get(CLUB, 0.0), 6),
                "club_wins_away": (
                    step_nodes.index(node) if node in step_nodes else None),
            })
        if node in known:
            state[node] = known[node]
        display_bracket.append(entry)

    # --- the case for Geelong ---
    # Which honest facts to lead with is an editorial choice; whether each one
    # is true is not. Every card is a rule that fires only while it holds.
    era = scott_era_record(CLUB, team_ids[CLUB], live_teams)
    ranked_by_percentage = sorted(standings, key=lambda r: -r["percentage"])
    club_row = next((r for r in standings if r["name"] == CLUB), None)
    streak, last_loss_note = current_win_streak(games, CLUB)
    club_semi = next((f for f in fixtures if f["involves_club"]), None)

    case_context = {
        "season": SEASON,
        "next_stage": (next_fixture or {}).get("stage"),
        "next_opponent": (next_fixture or {}).get("opponent"),
        "by_stage": {row["stage"]: row for row in era["by_stage"]},
        "by_venue": {row["venue"]: row for row in era["by_venue"]},
        "against_live_teams": era["against_live_teams"],
        "grand_finals_reached": era["grand_finals_reached"],
        "seasons_playing_finals": era["seasons_playing_finals"],
        "seasons_coached": SEASON - SCOTT_ERA_FROM + 1,
        "next_venue": (next_fixture or {}).get("venue"),
        "next_venue_provisional": bool(
            (next_fixture or {}).get("provisional_reasons")),
        "season_series": season_series(
            games, CLUB, (next_fixture or {}).get("opponent")),
        "flag_if_we_win": (
            (club_semi["club_if_home_wins"] if club_semi["home"] == CLUB
             else club_semi["club_if_away_wins"]) if club_semi else None
        ),
        "grand_final_scenarios": next(
            (s["scenarios"] for s in steps if s["node"] == "GF"), []),
        "ladder_rank": club_row["rank"] if club_row else None,
        "percentage_rank": next(
            (i for i, r in enumerate(ranked_by_percentage, 1) if r["name"] == CLUB),
            None),
        "percentage": club_row["percentage"] if club_row else None,
        "win_streak": streak,
        # Needed before we may claim the best run of form left in the draw.
        "rival_streaks": {
            team: current_win_streak(games, team)[0]
            for team in live_teams if team != CLUB
        },
        "last_loss_note": last_loss_note,
        "opponent_last_loss": last_defeat(games, (next_fixture or {}).get("opponent")),
        "market_probability": (market or {}).get("club_win_probability"),
        "model_probability": (next_fixture or {}).get("club_win_probability"),
    }
    case_cards = case.build_case(case_context)

    # Next opponent first, then who we could meet in a prelim, then the rest.
    head_to_head_order = []
    if next_fixture:
        head_to_head_order.append(next_fixture["opponent"])
    for step in steps[1:]:
        for scenario in step.get("scenarios", []):
            if scenario["opponent"] not in head_to_head_order:
                head_to_head_order.append(scenario["opponent"])
    for team in live_teams:
        if team != CLUB and team not in head_to_head_order:
            head_to_head_order.append(team)

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
        "grand_final": grand_final,
        "experts": expert_panel,
        "path_to_glory": path_to_glory,
        "market": market,
        "bracket": display_bracket,
        "field": field,
        "finals_head_to_head": finals_head_to_head(
            CLUB, team_ids[CLUB], head_to_head_order),
        "scott_era": era,
        "dominance": dominance_since(SCOTT_ERA_FROM, CLUB),
        "precedent": precedent_for_our_position(
            CLUB, club_row["rank"] if club_row else None),
        "case": case_cards,
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
        # The page leads with this week's market price, so that is what the
        # movement shown underneath the headline has to be tracking.
        "market_next_game": (state.get("market") or {}).get("club_win_probability"),
        "models_next_game": (state.get("next_fixture") or {}).get("club_win_probability"),
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
