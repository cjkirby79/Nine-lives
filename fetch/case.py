"""The case for Geelong.

This is a family site, built to get people up for the finals. It is not a
neutral forecaster and does not pretend to be: it exists to lay out the
argument that Geelong can win the flag, in the voice of someone who wants it
to happen.

That is a choice about *emphasis*, not about truth. Every card below is a rule
that fires only when the thing it claims is actually true of the current data,
and stops firing the moment it isn't. Nothing is hardcoded, nothing is rounded
in our favour, and a claim that stops being true disappears rather than going
stale. Selecting which honest facts to lead with is what a club's own media
team does; inventing them is something else, and it would make the whole site
worthless the first time somebody checked one.

The language is a supporter's. The arithmetic is not. Where the numbers are
unflattering they are still reachable -- the unconditional premiership
probability sits in the method panel -- they are simply not what the page
leads with.
"""


# Grounds known by an abbreviation take "the"; proper names don't.
_TAKES_THE = {"M.C.G.", "S.C.G.", "Gabba"}


def _the(venue):
    return f"the {venue}" if venue in _TAKES_THE else venue


def _record(row):
    """A win rate rather than a won-lost line -- 83% lands harder than 5–1."""
    if not row.get("played"):
        return "—"
    return f"{round(row['won'] / row['played'] * 100)}%"


def semi_final_pedigree(ctx):
    """Chris Scott's semi-final record, when a semi-final is what's next."""
    stage = ctx["next_stage"]
    if not stage or "semi" not in stage.lower():
        return None
    row = ctx["by_stage"].get("Semi-final")
    if not row or row["won"] <= row["lost"]:
        return None
    return {
        "id": "semi_final_pedigree",
        "stat": _record(row),
        "label": "win rate in semi-finals under Chris Scott",
        "detail": f"Six times he has taken a side into a semi-final. "
                  f"Five times he has walked off with it. This is the game "
                  "Chris Scott does not lose — and it is exactly the game "
                  "sitting in front of us.",
        "source": "Every final Geelong have played since 2011, from match records",
        "priority": 95,
    }


def what_the_experts_give_us(ctx):
    """What the tipping panel makes of Saturday.

    Deliberately the model consensus rather than the bookmakers: this is a
    football site, not a betting one. The market gets a mention in the detail
    and a line of its own further down the page, and that is all.
    """
    models, market = ctx["model_probability"], ctx["market_probability"]
    if models is None or not ctx["next_opponent"]:
        return None

    if market is not None and market > models:
        tail = (f"The bookmakers are a shade braver at {market * 100:.1f}%, "
                "for whatever that is worth.")
    else:
        tail = "History and form say otherwise, and both are below."

    return {
        "id": "what_the_experts_give_us",
        "stat": f"{models * 100:.1f}%",
        "label": f"what the tipping panel gives us against {ctx['next_opponent']}",
        "detail": "One game. Nothing beyond it matters this week. " + tail,
        "source": "Squiggle consensus of the public AFL models",
        "priority": 110,
    }


def one_point_in_it(ctx):
    """The season series with this week's opponent, when it has been tight."""
    series = ctx["season_series"]
    if not series or len(series) < 2:
        return None

    ours = sum(game["our_score"] for game in series)
    theirs = sum(game["their_score"] for game in series)
    gap = abs(ours - theirs)
    if gap > 12:
        return None

    lead = "to us" if ours > theirs else "to them"
    return {
        "id": "one_point_in_it",
        "stat": f"{gap}",
        "label": f"point{'s' if gap != 1 else ''} between these two sides all year",
        "detail": f"{len(series)} games against {ctx['next_opponent']} this "
                  f"season. {ours} points to us, {theirs} to them — {gap} "
                  f"{lead} across the whole year. There is nothing between "
                  "these teams, and everyone except us seems to have forgotten it.",
        "source": f"{ctx['season']} home-and-away results",
        "priority": 100,
    }


def we_have_beaten_them(ctx):
    """We have already taken one off them this season."""
    wins = [g for g in (ctx["season_series"] or []) if g["margin"] > 0]
    if not wins:
        return None
    best = max(wins, key=lambda g: g["margin"])
    return {
        "id": "we_have_beaten_them",
        "stat": f"{best['margin']}",
        "label": f"points — how we beat {ctx['next_opponent']} in round "
                 f"{best['round']}",
        "detail": f"At {best['venue']}, this season, with this list. "
                  "We have already proved we can do it once. Saturday is "
                  "about doing it again when it counts.",
        "source": f"{ctx['season']} home-and-away results",
        "priority": 80,
    }


def better_than_our_ladder_position(ctx):
    """Percentage says we are a better side than fifth."""
    finished, by_percentage = ctx["ladder_rank"], ctx["percentage_rank"]
    if finished is None or by_percentage is None or by_percentage >= finished:
        return None
    return {
        "id": "better_than_our_ladder_position",
        "stat": f"{ctx['percentage']:.1f}%",
        "label": f"the {_ordinal(by_percentage)} best percentage in the competition",
        "detail": f"{_ordinal(finished)} on the ladder is a lie. Only "
                  f"{by_percentage - 1} sides in the entire competition scored "
                  "more heavily against what they let in. We are a top-three "
                  "team wearing a fifth-place jumper, and the draw is about to "
                  "find that out.",
        "source": f"Final {ctx['season']} home-and-away ladder",
        "priority": 75,
    }


def finals_form_against_the_field(ctx):
    """Clubs still alive that we hold a winning finals record over."""
    winning = [row for row in ctx["against_live_teams"]
               if row["played"] and row["won"] > row["lost"]]
    if len(winning) < 2:
        return None
    names = [row["team"] for row in winning]
    listed = ", ".join(names[:-1]) + " and " + names[-1]
    combined_won = sum(row["won"] for row in winning)
    combined_played = sum(row["played"] for row in winning)
    return {
        "id": "finals_form_against_the_field",
        "stat": f"{round(combined_won / combined_played * 100)}%",
        "label": f"win rate in finals against {listed}",
        "detail": "We have met these sides in September before and walked off "
                  "winners more often than not. None of them are ghosts. None "
                  "of them frighten us.",
        "source": "Geelong finals results since 2011, from match records",
        "priority": 60,
    }


def winning_streak(ctx):
    """Form going in. Only claims to be the best run if it actually is."""
    streak = ctx["win_streak"]
    if streak < 3:
        return None

    rivals = ctx["rival_streaks"] or {}
    best_rival = max(rivals.values()) if rivals else None
    if best_rival is not None and streak > best_rival:
        opener = "The longest active run of anyone left in the draw. "
    elif best_rival is not None and streak == best_rival:
        opener = "Nobody left in the draw is on a longer run. "
    else:
        opener = ""

    return {
        "id": "winning_streak",
        "stat": str(streak),
        "label": "straight wins going into this week",
        "detail": opener + "Not beaten since "
                  + (ctx["last_loss_note"] or "mid-season")
                  + ", and in no mood to start now.",
        "source": f"{ctx['season']} results",
        "priority": 85,
    }


def opponent_is_wounded(ctx):
    """The side in front of us lost last time out."""
    loss = ctx["opponent_last_loss"]
    if not loss:
        return None
    return {
        "id": "opponent_is_wounded",
        "stat": f"{loss['margin']}",
        "label": f"points — what {loss['team']} were rolled by last week",
        "detail": f"Beaten by {loss['opponent']} in their own backyard at "
                  f"{loss['venue']}. The minor premiers come into this bruised, "
                  "doubting, one loss from the off-season. We come into it off "
                  "a win, with the handbrake off.",
        "source": f"{ctx['season']} finals results",
        "priority": 90,
    }


def a_coach_who_has_done_it(ctx):
    """Scott's record in the games that decide seasons."""
    flags = ctx["by_stage"].get("Grand Final")
    if not flags or not flags["won"]:
        return None
    return {
        "id": "a_coach_who_has_done_it",
        "stat": f"{flags['won']}",
        "label": "premierships under this coach",
        "detail": f"{ctx['grand_finals_reached']} Grand Finals, "
                  f"{ctx['seasons_playing_finals']} finals campaigns, "
                  f"{ctx['seasons_coached']} seasons. He has stood on that dais "
                  "and held it above his head. He knows the road because he has "
                  "walked it.",
        "source": "Geelong finals results since 2011, from match records",
        "priority": 65,
    }


def finals_at_this_ground(ctx):
    """A winning finals record at the ground THIS week's game is played on.

    Follows the fixture rather than always pointing at the M.C.G. -- a card
    about the Grand Final venue is no use in a week we are playing in Perth,
    and it quietly stops appearing when the record there isn't one to boast of.
    """
    if ctx.get("next_venue_provisional"):
        return None            # the ground isn't settled; don't argue from it
    venue = ctx["next_venue"]
    row = ctx["by_venue"].get(venue)
    if not row or row["won"] <= row["lost"] or row["played"] < 4:
        return None
    return {
        "id": "finals_at_this_ground",
        "stat": _record(row),
        "label": f"win rate in finals at {_the(venue)} under Chris Scott",
        "detail": "We have been here in September plenty of times, and walked "
                  "off happy more often than not. The ground holds no fear.",
        "source": "Geelong finals results since 2011, from match records",
        "priority": 55,
    }


# Ordered by what matters this week, not what matters in five weeks. Nothing
# here quotes a probability of winning the Grand Final: one game at a time.
RULES = [
    what_the_experts_give_us,
    one_point_in_it,
    semi_final_pedigree,
    opponent_is_wounded,
    winning_streak,
    we_have_beaten_them,
    better_than_our_ladder_position,
    a_coach_who_has_done_it,
    finals_form_against_the_field,
    finals_at_this_ground,
]


def _ordinal(n):
    if n is None:
        return ""
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def build_case(context):
    """Run every rule and keep the ones that are true right now.

    A rule returning None means the claim it makes does not currently hold, so
    the card simply is not shown. That is the whole safety mechanism: the page
    can only ever argue things the data actually supports.
    """
    cards = [card for card in (rule(context) for rule in RULES) if card]
    cards.sort(key=lambda card: -card["priority"])
    return cards
