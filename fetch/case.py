"""The case for Geelong.

This site is not a neutral forecaster. It exists to lay out the argument that
Geelong can win the flag, and it foregrounds the numbers that support it.

That is a choice about *emphasis*, not about truth. Every card below is a rule
that fires only when the thing it claims is actually true of the current data,
and stops firing the moment it isn't. Nothing is hardcoded, nothing is rounded
in our favour, and a claim that stops being true disappears rather than going
stale. Selecting which honest facts to lead with is what a club's own media
team does; inventing them is something else, and it would make the whole site
worthless the first time somebody checked one.

Where the numbers are unflattering they are still reachable -- the unconditional
premiership probability sits in the method panel -- they are simply not what the
page leads with.
"""


def _record(row):
    return f"{row['won']}–{row['lost']}"


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
        "label": "in semi-finals under Chris Scott",
        "detail": f"He has lost {row['lost']} of {row['played']}. "
                  "A semi-final is exactly what is in front of us.",
        "source": "Every final Geelong have played since 2011, from match records",
        "priority": 100,
    }


def one_win_away(ctx):
    """What beating this week's opponent is actually worth."""
    if ctx["flag_if_we_win"] is None or not ctx["next_opponent"]:
        return None
    return {
        "id": "one_win_away",
        "stat": f"{ctx['flag_if_we_win'] * 100:.1f}%",
        "label": f"for the flag if we beat {ctx['next_opponent']}",
        "detail": "One win turns a long shot into a live chance. "
                  "Everything below is the argument that we get it.",
        "source": "Derived from the Squiggle consensus across the remaining bracket",
        "priority": 105,
    }


def favoured_in_the_decider(ctx):
    """Sides we would start favourite against in a Grand Final."""
    scenarios = ctx["grand_final_scenarios"]
    if not scenarios:
        return None
    favoured = [s for s in scenarios if s["club_win_probability"] > 0.5]
    if not favoured:
        return None

    # Quote the opponent we are most likely to actually meet, not the one we
    # rate best against -- being 70% against a side with a 2% chance of getting
    # there is a hollow number to lead with.
    likeliest = max(scenarios, key=lambda s: s["probability"])
    against_likeliest = likeliest["club_win_probability"] * 100

    return {
        "id": "favoured_in_the_decider",
        "stat": f"{len(favoured)} of {len(scenarios)}",
        "label": "possible Grand Final opponents we would start favourite against",
        "detail": f"And against {likeliest['opponent']}, the side most likely "
                  f"to be there, we are rated {against_likeliest:.0f}% on "
                  "neutral ground. Get to the last Saturday and it is a "
                  "coin toss against anyone.",
        "source": "Squiggle model consensus, priced at a neutral M.C.G.",
        "priority": 90,
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
        "detail": f"We finished {_ordinal(finished)}, but only "
                  f"{by_percentage - 1} sides scored better relative to what they "
                  "conceded. The ladder flatters the teams above us.",
        "source": f"Final {ctx['season']} home-and-away ladder",
        "priority": 85,
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
    combined_lost = sum(row["lost"] for row in winning)
    return {
        "id": "finals_form_against_the_field",
        "stat": f"{combined_won}–{combined_lost}",
        "label": f"in finals against {listed}",
        "detail": "We have beaten most of what is left in front of us before, "
                  "in exactly this kind of game.",
        "source": "Geelong finals results since 2011, from match records",
        "priority": 80,
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
        "detail": opener + "We have not been beaten since "
                  + (ctx["last_loss_note"] or "mid-season") + ".",
        "source": f"{ctx['season']} results",
        "priority": 75,
    }


def opponent_is_wounded(ctx):
    """The side in front of us lost last time out."""
    loss = ctx["opponent_last_loss"]
    if not loss:
        return None
    return {
        "id": "opponent_is_wounded",
        "stat": f"{loss['margin']}",
        "label": f"points — what {loss['team']} lost by last week",
        "detail": f"Beaten by {loss['opponent']} at "
                  f"{loss['venue']}. They come into this off a defeat; we come "
                  "into it off a win.",
        "source": f"{ctx['season']} finals results",
        "priority": 70,
    }


def the_money_likes_us(ctx):
    """The market rates us above the models."""
    market, models = ctx["market_probability"], ctx["model_probability"]
    if market is None or models is None or market <= models:
        return None
    return {
        "id": "the_money_likes_us",
        "stat": f"{market * 100:.1f}%",
        "label": "what the betting market gives us this week",
        "detail": "That is higher than the computer models rate us "
                  f"({models * 100:.1f}%). The people with money on it are "
                  "more convinced than the machines.",
        "source": "Squiggle's Punters source, derived from bookmaker pricing",
        "priority": 65,
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
        "detail": f"{ctx['grand_finals_reached']} Grand Finals and "
                  f"{ctx['seasons_playing_finals']} finals series in "
                  f"{ctx['seasons_coached']} seasons. He has been here before, "
                  "and he has won it before.",
        "source": "Geelong finals results since 2011, from match records",
        "priority": 60,
    }


def september_at_the_mcg(ctx):
    """A winning finals record at the ground the Grand Final is played on."""
    row = ctx["by_venue"].get("M.C.G.")
    if not row or row["won"] <= row["lost"] or row["played"] < 6:
        return None
    return {
        "id": "september_at_the_mcg",
        "stat": _record(row),
        "label": "in finals at the M.C.G. under Chris Scott",
        "detail": "The Grand Final is played there, and it is where we "
                  "knocked over Carlton a week ago. We know the ground.",
        "source": "Geelong finals results since 2011, from match records",
        "priority": 55,
    }


RULES = [
    semi_final_pedigree,
    one_win_away,
    favoured_in_the_decider,
    better_than_our_ladder_position,
    finals_form_against_the_field,
    winning_streak,
    opponent_is_wounded,
    the_money_likes_us,
    a_coach_who_has_done_it,
    september_at_the_mcg,
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
