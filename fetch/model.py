"""Turning Squiggle's published numbers into a premiership probability.

Squiggle has no premiership-probability endpoint, so the headline number has to
be derived. Two rules govern everything here:

  1. Where Squiggle has already published a probability for a real fixture, use
     it verbatim. Don't second-guess it.
  2. Where it hasn't -- the preliminary final and grand final, whose opponents
     aren't known yet -- fall back to a conversion fitted against Squiggle's own
     published output, so the scale is learned rather than assumed. This matters:
     Squiggle's power ratings are not expressed in points (Geelong 62.0 v
     Fremantle 61.8, yet Squiggle tips Fremantle by 11.4), so any hardcoded
     scale factor would be an invention.

The bracket is then enumerated exhaustively -- every remaining combination of
outcomes, roughly 128 leaves -- and the paths where Geelong win the flag are
summed. That is exact arithmetic over the fixture tree, not a Monte Carlo
simulation.
"""

import math

# --- Reference data -------------------------------------------------------
# Geography, not statistics. Used to work out who is travelling and who is at
# home, which the fitted model prices separately.

TEAM_STATE = {
    "Adelaide": "SA", "Brisbane Lions": "QLD", "Carlton": "VIC",
    "Collingwood": "VIC", "Essendon": "VIC", "Fremantle": "WA",
    "Geelong": "VIC", "Gold Coast": "QLD", "Greater Western Sydney": "NSW",
    "Hawthorn": "VIC", "Melbourne": "VIC", "North Melbourne": "VIC",
    "Port Adelaide": "SA", "Richmond": "VIC", "St Kilda": "VIC",
    "Sydney": "NSW", "West Coast": "WA", "Western Bulldogs": "VIC",
}

VENUE_STATE = {
    "M.C.G.": "VIC", "Docklands": "VIC", "Kardinia Park": "VIC",
    "Adelaide Oval": "SA", "Norwood Oval": "SA", "Barossa Park": "SA",
    "Perth Stadium": "WA", "Hands Oval": "WA",
    "S.C.G.": "NSW", "Sydney Showground": "NSW",
    "Manuka Oval": "ACT", "Gabba": "QLD", "Carrara": "QLD",
    "York Park": "TAS", "Bellerive Oval": "TAS",
    "Marrara Oval": "NT", "Traeger Park": "NT",
}

# Where each club hosts a FINAL. Victorian clubs don't get to host finals at
# their home ground -- Geelong's home finals are played at the MCG, not
# Kardinia Park -- so this is deliberately not the same as a home-ground map.
FINALS_HOME_VENUE = {
    "Adelaide": "Adelaide Oval", "Brisbane Lions": "Gabba",
    "Carlton": "M.C.G.", "Collingwood": "M.C.G.", "Essendon": "M.C.G.",
    "Fremantle": "Perth Stadium", "Geelong": "M.C.G.",
    "Gold Coast": "Carrara", "Greater Western Sydney": "Sydney Showground",
    "Hawthorn": "M.C.G.", "Melbourne": "M.C.G.", "North Melbourne": "M.C.G.",
    "Port Adelaide": "Adelaide Oval", "Richmond": "M.C.G.",
    "St Kilda": "M.C.G.", "Sydney": "S.C.G.", "West Coast": "Perth Stadium",
    "Western Bulldogs": "M.C.G.",
}

GRAND_FINAL_VENUE = "M.C.G."

# Squiggle reports whatever a ground was called at the time, so the same venue
# turns up under several names across a 15-year archive. Collapse the
# sponsor-name changes; genuinely different grounds stay separate.
VENUE_ALIASES = {
    "GMHBA Stadium": "Kardinia Park",
    "Marvel Stadium": "Docklands",
    "Etihad Stadium": "Docklands",
    "Optus Stadium": "Perth Stadium",
    "Domain Stadium": "Subiaco",
    "UNSW Canberra Oval": "Manuka Oval",
    "Metricon Stadium": "Carrara",
    "People First Stadium": "Carrara",
    "Adelaide Arena": "Football Park",
    "AAMI Stadium": "Football Park",
    "Blundstone Arena": "Bellerive Oval",
    "UTAS Stadium": "York Park",
    "Engie Stadium": "Sydney Showground",
    "GIANTS Stadium": "Sydney Showground",
    "Spotless Stadium": "Sydney Showground",
}


def canonical_venue(venue):
    """Fold sponsor-era ground names onto one canonical name."""
    return VENUE_ALIASES.get(venue, venue)

# Only fit on recent rounds. Squiggle publishes power ratings for the current
# round only, so pairing today's ratings with April's tips would measure how
# much teams have changed, not how ratings map to margins.
CALIBRATION_FROM_ROUND = 17


# --- Small linear algebra -------------------------------------------------

def solve_ols(rows, targets):
    """Ordinary least squares via the normal equations.

    Hand-rolled because the fetch script runs on a bare container with no pip
    install step. Gaussian elimination with partial pivoting on a matrix that
    is at most 3x3 -- numerical robustness is not the binding constraint here.
    """
    if not rows:
        raise ValueError("no rows to fit")
    width = len(rows[0])

    # XtX (augmented with Xty) so we can eliminate in one pass.
    matrix = []
    for i in range(width):
        row = [sum(r[i] * r[j] for r in rows) for j in range(width)]
        row.append(sum(r[i] * t for r, t in zip(rows, targets)))
        matrix.append(row)

    for col in range(width):
        pivot = max(range(col, width), key=lambda r: abs(matrix[r][col]))
        if abs(matrix[pivot][col]) < 1e-12:
            raise ValueError("singular design matrix -- inputs are collinear")
        matrix[col], matrix[pivot] = matrix[pivot], matrix[col]
        for r in range(width):
            if r == col:
                continue
            factor = matrix[r][col] / matrix[col][col]
            for c in range(col, width + 1):
                matrix[r][c] -= factor * matrix[col][c]

    return [matrix[i][width] / matrix[i][i] for i in range(width)]


def logistic(x):
    if x < -700:
        return 0.0
    if x > 700:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


def logit(p):
    p = min(max(p, 0.001), 0.999)
    return math.log(p / (1.0 - p))


# --- Calibration ----------------------------------------------------------

def venue_context(home, away, venue):
    """(is_home_ground, away_team_is_interstate) for a fixture.

    Reads the venue rather than trusting the home/away label, so Gather Round
    and Tasmania/Darwin games are priced as the neutral-ish fixtures they are.
    """
    venue = canonical_venue(venue)
    venue_state = VENUE_STATE.get(venue)
    if venue_state is None:
        return 1.0, 1.0 if TEAM_STATE.get(home) != TEAM_STATE.get(away) else 0.0
    at_home = 1.0 if VENUE_STATE.get(venue) == TEAM_STATE.get(home) else 0.0
    travelling = 1.0 if venue_state != TEAM_STATE.get(away) else 0.0
    return at_home, travelling


class Calibration:
    """Two fits, both against Squiggle's own published numbers.

    margin_model:      hmargin ~ a*(power difference) + b*(home ground) + c*(away travelling)
    probability_model: logit(confidence) ~ k * hmargin

    The second is the tight, stable one -- Squiggle's own margin-to-confidence
    relationship, which barely moves across a season. The first is the loose
    one, and its residual error is reported so the page can show how much to
    trust it.
    """

    def __init__(self, margin_coefficients, points_per_logit,
                 diagnostics):
        self.margin_coefficients = margin_coefficients
        self.points_per_logit = points_per_logit
        self.diagnostics = diagnostics

    def expected_margin(self, home, away, venue, powers, neutral=False):
        a, b, c = self.margin_coefficients
        delta = powers.get(home, 0.0) - powers.get(away, 0.0)
        if neutral:
            return a * delta
        at_home, travelling = venue_context(home, away, venue)
        return a * delta + b * at_home + c * travelling

    def win_probability(self, home, away, venue, powers, neutral=False):
        margin = self.expected_margin(home, away, venue, powers, neutral)
        return logistic(self.points_per_logit * margin)

    def as_dict(self):
        a, b, c = self.margin_coefficients
        return {
            "points_per_power_point": round(a, 4),
            "home_ground_points": round(b, 4),
            "interstate_travel_points": round(c, 4),
            "logit_per_point": round(self.points_per_logit, 5),
            "diagnostics": self.diagnostics,
        }


def fit_calibration(games, tips, powers):
    """Fit the fallback model on this season's published Squiggle output.

    games   -- Squiggle games for the season, keyed however; only completed or
               fixtured games with two known teams are usable.
    tips    -- Squiggle Aggregate tips for the season.
    powers  -- {team: current Aggregate power rating}
    """
    games_by_id = {g["id"]: g for g in games}

    design, margins, prob_rows, prob_targets = [], [], [], []
    finals_rows, finals_margins = [], []

    for tip in tips:
        game = games_by_id.get(tip.get("gameid"))
        if game is None:
            continue
        home, away = game.get("hteam"), game.get("ateam")
        if not home or not away:
            continue
        try:
            hmargin = float(tip["hmargin"])
            confidence = float(tip["hconfidence"]) / 100.0
        except (TypeError, ValueError, KeyError):
            continue

        # The margin-to-probability fit is stable all season, so use every row.
        prob_rows.append([hmargin])
        prob_targets.append(logit(confidence))

        if game.get("round", 0) < CALIBRATION_FROM_ROUND:
            continue
        if home not in powers or away not in powers:
            continue

        at_home, travelling = venue_context(home, away, game.get("venue"))
        row = [powers[home] - powers[away], at_home, travelling]
        design.append(row)
        margins.append(hmargin)
        if game.get("is_final"):
            finals_rows.append(row)
            finals_margins.append(hmargin)

    if len(design) < 10 or len(prob_rows) < 10:
        raise ValueError(
            f"not enough Squiggle rows to calibrate "
            f"(margin={len(design)}, probability={len(prob_rows)})"
        )

    coefficients = solve_ols(design, margins)
    (points_per_logit,) = solve_ols(prob_rows, prob_targets)

    def rmse(rows, targets):
        if not rows:
            return None
        total = sum(
            (sum(c * v for c, v in zip(coefficients, row)) - target) ** 2
            for row, target in zip(rows, targets)
        )
        return round(math.sqrt(total / len(rows)), 2)

    mean_margin = sum(margins) / len(margins)
    ss_total = sum((m - mean_margin) ** 2 for m in margins)
    ss_residual = sum(
        (sum(c * v for c, v in zip(coefficients, row)) - m) ** 2
        for row, m in zip(design, margins)
    )

    diagnostics = {
        "margin_fit_games": len(design),
        "margin_fit_from_round": CALIBRATION_FROM_ROUND,
        "margin_fit_r_squared": round(1 - ss_residual / ss_total, 3) if ss_total else None,
        "margin_fit_rmse_points": rmse(design, margins),
        "finals_holdout_games": len(finals_rows),
        "finals_holdout_rmse_points": rmse(finals_rows, finals_margins),
        "probability_fit_games": len(prob_rows),
    }

    return Calibration(coefficients, points_per_logit, diagnostics)


# --- The bracket ----------------------------------------------------------
# 2026 is the first top-ten finals series. Five weeks, wildcard round first.
# The forward links below are the AFL's own progression rules, cross-checked at
# runtime against the fixture Squiggle publishes as it fills in.

NODE_ORDER = ["WC1", "WC2", "QF1", "QF2", "EF1", "EF2",
              "SF1", "SF2", "PF1", "PF2", "GF"]

NODE_STAGE = {
    "WC1": "Wildcard", "WC2": "Wildcard",
    "QF1": "Qualifying final", "QF2": "Qualifying final",
    "EF1": "Elimination final", "EF2": "Elimination final",
    "SF1": "Semi-final", "SF2": "Semi-final",
    "PF1": "Preliminary final", "PF2": "Preliminary final",
    "GF": "Grand Final",
}


class Bracket:
    """The 2026 finals tree, seeded from the final home-and-away ladder."""

    def __init__(self, seeds, finals_games, tips_by_game):
        self.seeds = seeds                      # {rank: team name}
        self.rank = {t: r for r, t in seeds.items()}
        self.finals_games = finals_games
        self.tips_by_game = tips_by_game

    # -- structure --------------------------------------------------------

    def participants(self, node, state):
        """Who plays in `node`, given the winners decided so far.

        Returns (home, away) or None if an upstream result is still missing.
        """
        s = self.seeds

        def winner(key):
            return state.get(key)

        def loser(key):
            pair = self.participants(key, state)
            won = state.get(key)
            if pair is None or won is None:
                return None
            return pair[1] if pair[0] == won else pair[0]

        try:
            if node == "WC1":
                return (s[7], s[10])
            if node == "WC2":
                return (s[8], s[9])
            if node == "QF1":
                return (s[1], s[4])
            if node == "QF2":
                return (s[2], s[3])
            if node in ("EF1", "EF2"):
                first, second = winner("WC1"), winner("WC2")
                if not first or not second:
                    return None
                # 5th hosts the LOWER-ranked wildcard winner, 6th the higher.
                higher, lower = sorted([first, second], key=lambda t: self.rank[t])
                return (s[5], lower) if node == "EF1" else (s[6], higher)
            if node == "SF1":
                a, b = loser("QF1"), winner("EF1")
                return (a, b) if a and b else None
            if node == "SF2":
                a, b = loser("QF2"), winner("EF2")
                return (a, b) if a and b else None
            # Prelims cross over: each qualifying-final winner hosts the winner
            # of the OTHER semi-final.
            if node == "PF1":
                a, b = winner("QF1"), winner("SF2")
                return (a, b) if a and b else None
            if node == "PF2":
                a, b = winner("QF2"), winner("SF1")
                return (a, b) if a and b else None
            if node == "GF":
                a, b = winner("PF1"), winner("PF2")
                if not a or not b:
                    return None
                # Neutral ground, so "home" is cosmetic -- show the higher seed
                # first, the way a broadcast graphic would.
                return tuple(sorted([a, b], key=lambda t: self.rank[t]))
        except KeyError:
            return None
        return None

    def venue_for(self, node, home):
        if node == "GF":
            return GRAND_FINAL_VENUE
        return FINALS_HOME_VENUE.get(home)

    # -- matching against Squiggle's fixture --------------------------------

    def game_for(self, home, away):
        """The Squiggle fixture for this matchup, if it has one yet."""
        for game in self.finals_games:
            teams = {game.get("hteam"), game.get("ateam")}
            if teams == {home, away}:
                return game
        return None

    def published_probability(self, home, away):
        """Squiggle's own consensus for this fixture, oriented to `home`.

        Returns (probability, game) or (None, game). Squiggle only tips games
        whose participants it already knows, so this covers the next round and
        nothing beyond it.
        """
        game = self.game_for(home, away)
        if game is None:
            return None, None
        tip = self.tips_by_game.get(game["id"])
        if not tip:
            return None, game
        try:
            home_confidence = float(tip["hconfidence"]) / 100.0
        except (TypeError, ValueError, KeyError):
            return None, game
        if game.get("hteam") == home:
            return home_confidence, game
        return 1.0 - home_confidence, game

    def known_results(self):
        """Winners of the finals already played, keyed by bracket node.

        Iterated to a fixed point rather than walked once. Finals weeks overlap
        -- Geelong's elimination final was decided on the Friday while the
        Saturday qualifying final was still to come -- so a single pass that
        stopped at the first unplayed game would throw away results that are
        already on the board.
        """
        state = {}
        changed = True
        while changed:
            changed = False
            for node in NODE_ORDER:
                if node in state:
                    continue
                pair = self.participants(node, state)
                if pair is None:
                    continue
                game = self.game_for(*pair)
                if game and game.get("complete") == 100 and game.get("winner"):
                    state[node] = game["winner"]
                    changed = True
        return state


def enumerate_bracket(bracket, calibration, powers, forced=None):
    """Walk every remaining outcome and total up who wins the flag.

    Around 128 leaves at this stage of the series, so exhaustive enumeration is
    both fast and exact -- no sampling error to explain away.

    `forced` pins the result of games that have not been played, which is how
    the "what does tonight's other final do to us?" numbers are produced: run
    it once per outcome and compare. Only pin a game whose two participants are
    already decided -- pinning one whose teams still depend on earlier results
    would be pinning a different match on different branches.
    """
    known = dict(bracket.known_results())
    if forced:
        known.update(forced)

    win = {node: {} for node in NODE_ORDER}     # P(team plays in node AND wins it)
    appear = {node: {} for node in NODE_ORDER}  # P(team plays in node at all)
    # P(team plays node AND opponent is X). Has to be the joint, not the product
    # of two marginals -- a team's presence and its opponent's are correlated
    # through the same upstream results.
    versus = {node: {} for node in NODE_ORDER}
    legs = {}                                    # per-node pricing, for the working

    def price(node, home, away):
        """Squiggle's published number if there is one, otherwise the fit.

        The kind is returned as its own field rather than left to be sniffed
        out of the description -- both descriptions mention Squiggle, so any
        substring test would mark every leg as published.
        """
        published, game = bracket.published_probability(home, away)
        if published is not None:
            return published, "published", "Squiggle Aggregate consensus", game
        neutral = node == "GF"
        venue = bracket.venue_for(node, home)
        modelled = calibration.win_probability(home, away, venue, powers, neutral)
        return modelled, "fitted", "fitted from Squiggle power ratings", game

    def walk(index, state, weight):
        if index == len(NODE_ORDER) or weight < 1e-12:
            return
        node = NODE_ORDER[index]
        pair = bracket.participants(node, state)
        if pair is None:
            return
        home, away = pair

        appear[node][home] = appear[node].get(home, 0.0) + weight
        appear[node][away] = appear[node].get(away, 0.0) + weight
        versus[node].setdefault(home, {})[away] = versus[node].setdefault(home, {}).get(away, 0.0) + weight
        versus[node].setdefault(away, {})[home] = versus[node].setdefault(away, {}).get(home, 0.0) + weight

        if node in known:
            winner = known[node]
            win[node][winner] = win[node].get(winner, 0.0) + weight
            walk(index + 1, {**state, node: winner}, weight)
            return

        home_probability, source_kind, source, game = price(node, home, away)
        legs.setdefault(node, []).append({
            "home": home, "away": away, "teams": {home, away},
            "home_probability": round(home_probability, 6),
            "source": source,
            "source_kind": source_kind,
            "venue": (game or {}).get("venue") or bracket.venue_for(node, home),
            "path_weight": round(weight, 6),
        })

        for winner, probability in ((home, home_probability),
                                    (away, 1.0 - home_probability)):
            win[node][winner] = win[node].get(winner, 0.0) + weight * probability
            walk(index + 1, {**state, node: winner}, weight * probability)

    walk(0, {}, 1.0)
    return {"win": win, "appear": appear, "versus": versus,
            "legs": legs, "known": known,
            "decided": bracket.known_results()}


def club_scenarios(outcomes, node, team):
    """Every way this game could line up for `team`: who, where, and our odds.

    Answers the question a supporter actually asks -- "if we win this week, who
    do we get and where?" -- by pairing each possible opponent with the ground
    it would be played on, rather than listing opponents and venues separately
    and leaving you to guess which goes with which.

    Probabilities are conditional on the club being in the game at all, so they
    sum to 1.
    """
    combinations = {}
    for leg in outcomes["legs"].get(node, []):
        if team not in leg["teams"]:
            continue
        at_home = leg["home"] == team
        opponent = leg["away"] if at_home else leg["home"]
        ours = leg["home_probability"] if at_home else 1.0 - leg["home_probability"]

        # A Grand Final is played on neutral ground, so which side the bracket
        # nominates as "home" is a formality. Saying "away" there would be
        # inventing a disadvantage that doesn't exist.
        key = (opponent, leg["venue"], at_home)
        entry = combinations.setdefault(key, {"weight": 0.0, "weighted_win": 0.0})
        entry["weight"] += leg["path_weight"]
        entry["weighted_win"] += leg["path_weight"] * ours

    total = sum(entry["weight"] for entry in combinations.values())
    if total <= 0:
        return []

    return sorted(
        (
            {
                "opponent": opponent,
                "venue": venue,
                "club_is_home": at_home,
                "neutral": node == "GF",
                "probability": round(entry["weight"] / total, 6),
                "club_win_probability": round(entry["weighted_win"] / entry["weight"], 6),
            }
            for (opponent, venue, at_home), entry in combinations.items()
        ),
        key=lambda row: -row["probability"],
    )


def fixture_impact(bracket, calibration, powers, team="Geelong"):
    """What every scheduled final still to be played does to our chances.

    For each game whose two teams are already known, re-run the whole bracket
    with that result pinned each way. The gap between the two answers is what
    that game is worth to us -- which is the honest way to say whether a final
    we are not playing in matters.
    """
    decided = bracket.known_results()
    baseline = enumerate_bracket(bracket, calibration, powers)

    rows = []
    state = {}
    for node in NODE_ORDER:
        pair = bracket.participants(node, state)
        if node in decided:
            state[node] = decided[node]
        if pair is None or node in decided:
            continue

        home, away = pair
        game = bracket.game_for(home, away)
        # Only games the fixture already names. Anything further out has
        # different participants on different branches, so pinning a winner
        # would be pinning a different match each time.
        if game is None:
            continue

        published, _ = bracket.published_probability(home, away)
        leg = (baseline["legs"].get(node) or [{}])[0]

        outcomes = {}
        for winner in (home, away):
            pinned = enumerate_bracket(bracket, calibration, powers, forced={node: winner})
            outcomes[winner] = pinned["win"]["GF"].get(team, 0.0)

        # Squiggle reports a completion percentage, so a game in progress can be
        # told apart from one yet to start. It matters: every probability here
        # is the pre-match consensus, and presenting that beside a live score
        # without saying so would be presenting a stale number as a current one.
        completeness = game.get("complete") or 0
        in_progress = 0 < completeness < 100

        rows.append({
            "node": node,
            "stage": NODE_STAGE[node],
            "home": home,
            "away": away,
            "in_progress": in_progress,
            "complete_percent": completeness,
            "home_score": game.get("hscore") if in_progress else None,
            "away_score": game.get("ascore") if in_progress else None,
            "time_string": game.get("timestr") if in_progress else None,
            "venue": (game or {}).get("venue") or bracket.venue_for(node, home),
            "date": (game or {}).get("date"),
            "unixtime": (game or {}).get("unixtime"),
            "game_id": (game or {}).get("id"),
            "home_probability": round(leg.get("home_probability", published or 0.5), 6),
            "source_kind": leg.get("source_kind"),
            "involves_club": team in (home, away),
            "club_if_home_wins": round(outcomes[home], 6),
            "club_if_away_wins": round(outcomes[away], 6),
            "club_swing": round(abs(outcomes[home] - outcomes[away]), 6),
        })

    rows.sort(key=lambda row: row["unixtime"] or 0)
    return rows


def premiership_report(outcomes, team="Geelong"):
    """Break the headline number into the wins it's actually made of.

    Each leg is P(win this final | playing in it). In a knockout bracket a
    team only reaches a game by winning the previous one, so those conditionals
    telescope: multiply them together and you get the headline back exactly.
    """
    win, appear, versus = outcomes["win"], outcomes["appear"], outcomes["versus"]
    flag = win["GF"].get(team, 0.0)

    decided = outcomes.get("decided", outcomes["known"])
    remaining = [n for n in NODE_ORDER
                 if n not in decided and appear[n].get(team, 0.0) > 1e-12]

    steps = []
    for node in remaining:
        present = appear[node].get(team, 0.0)
        marginal = win[node].get(team, 0.0)

        opponents = sorted(
            ({"team": other, "probability": round(joint / present, 6)}
             for other, joint in versus[node].get(team, {}).items()),
            key=lambda row: -row["probability"],
        )

        # A leg can be played at different grounds depending on who gets there,
        # so weight the venues rather than quietly showing the first one.
        venues = {}
        source = source_kind = None
        for leg in outcomes["legs"].get(node, []):
            if team not in leg["teams"]:
                continue
            venues[leg["venue"]] = venues.get(leg["venue"], 0.0) + leg["path_weight"]
            source = source or leg["source"]
            source_kind = source_kind or leg["source_kind"]
        ranked_venues = sorted(venues, key=lambda v: -venues[v])

        steps.append({
            "node": node,
            "stage": NODE_STAGE[node],
            "scenarios": club_scenarios(outcomes, node, team),
            "conditional_probability": round(marginal / present, 6) if present else 0.0,
            "cumulative_probability": round(marginal, 6),
            "source": source,
            "source_kind": source_kind,
            "venue": ranked_venues[0] if ranked_venues else None,
            "possible_venues": ranked_venues,
            "opponents": opponents,
        })

    return {
        "team": team,
        "probability": round(flag, 6),
        "reaches_grand_final": round(appear["GF"].get(team, 0.0), 6),
        "steps": steps,
    }


def field_probabilities(outcomes):
    """Premiership probability for every side still alive, best first."""
    return sorted(
        (
            {"team": team, "probability": round(probability, 6)}
            for team, probability in outcomes["win"]["GF"].items()
            if probability > 0
        ),
        key=lambda row: -row["probability"],
    )
