#!/usr/bin/env python3
"""Tests for the maths behind the headline number.

Plain asserts, no pytest -- this runs in the same bare container as the fetch
script. Run with: python3 fetch/test_model.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import case
import model

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SEEDS = {
    1: "Fremantle", 2: "Sydney", 3: "Brisbane Lions", 4: "Hawthorn",
    5: "Geelong", 6: "Adelaide", 7: "Melbourne", 8: "Western Bulldogs",
    9: "Collingwood", 10: "Carlton",
}

# Mirrors the real state of the 2026 series after week two: the Friday
# elimination final is decided while the Saturday qualifying final is not.
FINALS = [
    {"id": 1, "hteam": "Melbourne", "ateam": "Carlton", "complete": 100,
     "winner": "Carlton", "venue": "M.C.G.", "round": 25},
    {"id": 2, "hteam": "Western Bulldogs", "ateam": "Collingwood", "complete": 100,
     "winner": "Western Bulldogs", "venue": "M.C.G.", "round": 25},
    {"id": 3, "hteam": "Fremantle", "ateam": "Hawthorn", "complete": 100,
     "winner": "Hawthorn", "venue": "Perth Stadium", "round": 26},
    {"id": 4, "hteam": "Sydney", "ateam": "Brisbane Lions", "complete": 0,
     "winner": None, "venue": "S.C.G.", "round": 26},
    {"id": 5, "hteam": "Geelong", "ateam": "Carlton", "complete": 100,
     "winner": "Geelong", "venue": "M.C.G.", "round": 26},
    {"id": 6, "hteam": "Adelaide", "ateam": "Western Bulldogs", "complete": 0,
     "winner": None, "venue": "Adelaide Oval", "round": 26},
    {"id": 7, "hteam": "Fremantle", "ateam": "Geelong", "complete": 0,
     "winner": None, "venue": "M.C.G.", "round": 27},
]

TIPS = {7: {"hconfidence": "61.96", "hmargin": "10.26"}}

POWERS = {name: 100.0 for name in SEEDS.values()}

CALIBRATION = model.Calibration([1.5, 3.5, 4.5], 0.047, {})

checks = 0


def check(condition, description):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(description)


def close(a, b, tolerance=1e-9):
    return abs(a - b) <= tolerance


def bracket():
    return model.Bracket(SEEDS, FINALS, TIPS)


# --- linear algebra -------------------------------------------------------

def test_ols_recovers_known_coefficients():
    rows = [[1.0, 0.0, 2.0], [2.0, 1.0, 0.0], [3.0, 1.0, 1.0],
            [0.0, 2.0, 1.0], [4.0, 0.0, 3.0], [1.0, 3.0, 1.0]]
    truth = [2.0, -1.0, 0.5]
    targets = [sum(c * v for c, v in zip(truth, row)) for row in rows]
    fitted = model.solve_ols(rows, targets)
    check(all(close(f, t, 1e-8) for f, t in zip(fitted, truth)),
          f"OLS should recover exact coefficients, got {fitted}")


def test_ols_rejects_collinear_input():
    rows = [[1.0, 2.0], [2.0, 4.0], [3.0, 6.0]]
    try:
        model.solve_ols(rows, [1.0, 2.0, 3.0])
    except ValueError:
        return
    raise AssertionError("collinear design matrix should raise, not return garbage")


def test_logit_roundtrip():
    for p in (0.05, 0.25, 0.5, 0.75, 0.95):
        check(close(model.logistic(model.logit(p)), p, 1e-9), f"logit roundtrip at {p}")


# --- bracket structure ----------------------------------------------------

def test_wildcard_winners_feed_the_right_elimination_finals():
    state = {"WC1": "Carlton", "WC2": "Western Bulldogs"}
    # 5th hosts the LOWER-ranked wildcard winner, 6th the higher-ranked one.
    check(bracket().participants("EF1", state) == ("Geelong", "Carlton"),
          "5th should host the lower-ranked wildcard winner")
    check(bracket().participants("EF2", state) == ("Adelaide", "Western Bulldogs"),
          "6th should host the higher-ranked wildcard winner")


def test_semi_final_pairs_qualifying_loser_with_elimination_winner():
    state = {"WC1": "Carlton", "WC2": "Western Bulldogs",
             "QF1": "Hawthorn", "EF1": "Geelong"}
    check(bracket().participants("SF1", state) == ("Fremantle", "Geelong"),
          "the beaten minor premier should host the elimination winner")


def test_preliminary_finals_cross_over():
    state = {"WC1": "Carlton", "WC2": "Western Bulldogs", "QF1": "Hawthorn",
             "QF2": "Sydney", "EF1": "Geelong", "EF2": "Adelaide",
             "SF1": "Geelong", "SF2": "Adelaide"}
    check(bracket().participants("PF1", state) == ("Hawthorn", "Adelaide"),
          "PF1 should pair the QF1 winner with the OTHER semi-final winner")
    check(bracket().participants("PF2", state) == ("Sydney", "Geelong"),
          "PF2 should pair the QF2 winner with the SF1 winner")


def test_unresolved_upstream_leaves_participants_unknown():
    check(bracket().participants("SF2", {"QF1": "Hawthorn"}) is None,
          "a game whose feeders haven't been played should not resolve")


def test_known_results_survives_an_unplayed_earlier_game():
    """The regression this suite exists for.

    Geelong's elimination final finished on the Friday; the qualifying final it
    sits after in bracket order was still to be played on the Saturday. A
    single ordered pass drops the Friday result on the floor.
    """
    known = bracket().known_results()
    check(known.get("EF1") == "Geelong",
          "a completed elimination final must be recorded even though a "
          "lower-numbered node is still pending")
    check("QF2" not in known, "an unplayed game must not be given a winner")
    check(known.get("QF1") == "Hawthorn" and known.get("WC1") == "Carlton",
          "completed games should all be picked up")


# --- pricing --------------------------------------------------------------

def test_published_tip_is_used_verbatim_and_oriented():
    probability, _ = bracket().published_probability("Fremantle", "Geelong")
    check(close(probability, 0.6196, 1e-9), "home side should get the tip as published")
    flipped, _ = bracket().published_probability("Geelong", "Fremantle")
    check(close(flipped, 1 - 0.6196, 1e-9), "reversing the fixture must flip the tip")


def test_evenly_matched_sides_on_a_neutral_ground_are_a_coin_toss():
    p = CALIBRATION.win_probability("Geelong", "Hawthorn", "M.C.G.", POWERS, neutral=True)
    check(close(p, 0.5, 1e-9), f"neutral ground, equal ratings should be 0.5, got {p}")


def test_home_ground_and_travel_both_help_the_home_side():
    home_only = CALIBRATION.win_probability(
        "Geelong", "Hawthorn", "M.C.G.", POWERS)          # both Victorian
    plus_travel = CALIBRATION.win_probability(
        "Fremantle", "Geelong", "Perth Stadium", POWERS)  # Geelong flying west
    check(home_only > 0.5, "home ground alone should favour the host")
    check(plus_travel > home_only,
          "an interstate trip should cost the visitor more than a local one")


# --- enumeration ----------------------------------------------------------

def outcomes():
    return model.enumerate_bracket(bracket(), CALIBRATION, POWERS)


def test_exactly_one_team_wins_the_flag():
    total = sum(row["probability"] for row in model.field_probabilities(outcomes()))
    check(close(total, 1.0, 1e-9), f"premiership probabilities must sum to 1, got {total}")


def test_every_game_has_exactly_one_winner():
    result = outcomes()
    for node in model.NODE_ORDER:
        total = sum(result["win"][node].values())
        check(close(total, 1.0, 1e-9),
              f"win probabilities at {node} should sum to 1, got {total}")
        appearing = sum(result["appear"][node].values())
        check(close(appearing, 2.0, 1e-9),
              f"exactly two teams contest {node}, got {appearing}")


def test_eliminated_teams_cannot_win():
    field = {row["team"]: row["probability"] for row in model.field_probabilities(outcomes())}
    for team in ("Melbourne", "Collingwood", "Carlton"):
        check(field.get(team, 0.0) == 0.0, f"{team} is out and must sit at zero")


def test_leg_source_is_machine_readable():
    """Guards a real bug: both source descriptions contain the word "Squiggle",
    so sniffing the description marked the fitted legs as published."""
    report = model.premiership_report(outcomes(), "Geelong")
    kinds = {step["node"]: step["source_kind"] for step in report["steps"]}
    check(kinds["SF1"] == "published",
          "the semi-final has a Squiggle tip and must be marked published")
    check(kinds["PF2"] == "fitted" and kinds["GF"] == "fitted",
          "games with unknown opponents cannot be published, only fitted")
    for step in report["steps"]:
        check(step["source_kind"] in ("published", "fitted"),
              "every leg needs a source kind the page can branch on")


def test_conditionals_multiply_back_to_the_headline():
    report = model.premiership_report(outcomes(), "Geelong")
    product = 1.0
    for step in report["steps"]:
        product *= step["conditional_probability"]
    check(close(product, report["probability"], 1e-6),
          f"legs {product} should multiply to the headline {report['probability']}")
    check([s["node"] for s in report["steps"]] == ["SF1", "PF2", "GF"],
          "Geelong's remaining path is semi, prelim, grand final")


def test_opponent_probabilities_are_conditional_not_marginal():
    report = model.premiership_report(outcomes(), "Geelong")
    for step in report["steps"]:
        total = sum(o["probability"] for o in step["opponents"])
        # The full list, not a truncated top-N -- a published breakdown that
        # doesn't add up is worse than no breakdown.
        check(close(total, 1.0, 1e-5),   # tolerance covers 6dp rounding only
              f"{step['node']} opponents should sum to 1, got {total}")
        for opponent in step["opponents"]:
            check(0.0 <= opponent["probability"] <= 1.0,
                  f"{opponent} is not a probability")


# --- path to glory --------------------------------------------------------

def test_forcing_a_result_pins_it():
    pinned = model.enumerate_bracket(bracket(), CALIBRATION, POWERS,
                                     forced={"QF2": "Sydney"})
    check(close(pinned["win"]["QF2"].get("Sydney", 0.0), 1.0, 1e-9),
          "a pinned winner should win that game in every branch")
    check(pinned["win"]["QF2"].get("Brisbane Lions", 0.0) == 0.0,
          "the pinned loser should not win it anywhere")
    check("QF2" not in pinned["decided"],
          "pinning must not be mistaken for a game actually having been played")


def test_conditional_probabilities_obey_total_probability():
    """The strongest check available on the swing numbers.

    P(flag) must equal P(home win) x P(flag | home win)
                     + P(away win) x P(flag | away win).
    If the conditional runs and the baseline disagree, one of them is wrong.
    """
    baseline = model.enumerate_bracket(bracket(), CALIBRATION, POWERS)
    flag = baseline["win"]["GF"].get("Geelong", 0.0)

    rows = model.fixture_impact(bracket(), CALIBRATION, POWERS, "Geelong")
    check(len(rows) > 0, "there should be scheduled games left to weigh up")

    for row in rows:
        recombined = (row["home_probability"] * row["club_if_home_wins"]
                      + (1 - row["home_probability"]) * row["club_if_away_wins"])
        check(close(recombined, flag, 1e-6),
              f"{row['node']}: conditionals recombine to {recombined}, "
              f"not the baseline {flag}")
        check(row["club_swing"] >= 0, "a swing is a magnitude, never negative")


def test_our_own_game_is_worth_the_whole_season():
    rows = {r["node"]: r for r in
            model.fixture_impact(bracket(), CALIBRATION, POWERS, "Geelong")}
    semi = rows["SF1"]
    check(semi["involves_club"], "SF1 is Geelong's game")
    # Fremantle host, so Geelong winning is the away result.
    check(close(semi["club_if_home_wins"], 0.0, 1e-12),
          "losing the semi-final must end the season at zero")
    check(semi["club_if_away_wins"] > 0.2,
          "winning it should be worth a good deal more than the baseline")


def test_only_scheduled_games_get_weighed_up():
    nodes = {r["node"] for r in
             model.fixture_impact(bracket(), CALIBRATION, POWERS, "Geelong")}
    check(nodes == {"QF2", "EF2", "SF1"},
          f"only games the fixture already names can be pinned, got {nodes}")
    check("PF1" not in nodes and "GF" not in nodes,
          "a game whose teams vary by branch must not be pinned -- that would "
          "be pinning a different match on each branch")


def test_scenarios_pair_each_opponent_with_its_ground():
    report = model.premiership_report(outcomes(), "Geelong")
    steps = {step["node"]: step for step in report["steps"]}

    prelim = steps["PF2"]["scenarios"]
    check(sum(s["probability"] for s in prelim) - 1.0 < 1e-6,
          "opponent chances should sum to 1")
    grounds = {s["opponent"]: s["venue"] for s in prelim}
    check(grounds.get("Sydney") == "S.C.G.",
          "a preliminary final against Sydney is played at the S.C.G.")
    check(grounds.get("Brisbane Lions") == "Gabba",
          "against Brisbane it is played at the Gabba")
    for scenario in prelim:
        check(not scenario["club_is_home"],
              "Geelong travel to a preliminary final either way")
        check(not scenario["neutral"], "a preliminary final is not neutral")


def test_grand_final_scenarios_are_neutral():
    report = model.premiership_report(outcomes(), "Geelong")
    final = [s for s in report["steps"] if s["node"] == "GF"][0]
    for scenario in final["scenarios"]:
        check(scenario["neutral"],
              "the Grand Final is neutral ground -- calling it home or away "
              "invents an advantage that isn't there")
        check(scenario["venue"] == model.GRAND_FINAL_VENUE,
              "the Grand Final is at the M.C.G.")


def test_a_finished_bracket_is_a_certainty():
    finished = [dict(g) for g in FINALS]
    for game, winner in zip(finished[3:], ("Sydney", None, "Adelaide", "Geelong")):
        if winner:
            game.update(complete=100, winner=winner)
    finished += [
        {"id": 8, "hteam": "Brisbane Lions", "ateam": "Adelaide", "complete": 100,
         "winner": "Adelaide", "venue": "Gabba", "round": 27},
        {"id": 9, "hteam": "Hawthorn", "ateam": "Adelaide", "complete": 100,
         "winner": "Hawthorn", "venue": "M.C.G.", "round": 28},
        {"id": 10, "hteam": "Sydney", "ateam": "Geelong", "complete": 100,
         "winner": "Geelong", "venue": "S.C.G.", "round": 28},
        {"id": 11, "hteam": "Hawthorn", "ateam": "Geelong", "complete": 100,
         "winner": "Geelong", "venue": "M.C.G.", "round": 29},
    ]
    result = model.enumerate_bracket(
        model.Bracket(SEEDS, finished, {}), CALIBRATION, POWERS)
    report = model.premiership_report(result, "Geelong")
    check(close(report["probability"], 1.0, 1e-9),
          "a side that has already won every final must sit at 100%")
    check(report["steps"] == [], "nothing is left to play")


# --- the case engine ------------------------------------------------------
# This site argues a case, so the one thing that must never break is that it
# only argues things the data supports.

def case_context(**overrides):
    base = {
        "season": 2026,
        "next_stage": "Semi-Finals",
        "next_opponent": "Fremantle",
        "by_stage": {
            "Semi-final": {"stage": "Semi-final", "played": 6, "won": 5, "lost": 1},
            "Grand Final": {"stage": "Grand Final", "played": 4, "won": 2, "lost": 2},
        },
        "by_venue": {"M.C.G.": {"venue": "M.C.G.", "played": 24, "won": 13, "lost": 11}},
        "against_live_teams": [
            {"team": "Hawthorn", "played": 5, "won": 3, "lost": 2},
            {"team": "Sydney", "played": 3, "won": 2, "lost": 1},
        ],
        "grand_finals_reached": 4,
        "seasons_playing_finals": 14,
        "seasons_coached": 16,
        "next_venue": "Perth Stadium",
        "next_venue_provisional": False,
        "season_series": [
            {"round": 15, "venue": "Perth Stadium", "club_is_home": False,
             "our_score": 90, "their_score": 99, "margin": -9},
            {"round": 1, "venue": "Kardinia Park", "club_is_home": True,
             "our_score": 110, "their_score": 100, "margin": 10},
        ],
        "flag_if_we_win": 0.219,
        "grand_final_scenarios": [
            {"opponent": "Hawthorn", "probability": 0.66, "club_win_probability": 0.481},
            {"opponent": "Sydney", "probability": 0.09, "club_win_probability": 0.576},
        ],
        "ladder_rank": 5,
        "percentage_rank": 3,
        "percentage": 122.3,
        "win_streak": 7,
        "last_loss_note": "round 18 against Greater Western Sydney",
        "rival_streaks": {"Hawthorn": 3, "Sydney": 2},
        "opponent_last_loss": {"team": "Fremantle", "opponent": "Hawthorn",
                               "margin": 32, "venue": "Perth Stadium"},
        "market_probability": 0.391,
        "model_probability": 0.380,
    }
    base.update(overrides)
    return base


def ids_for(**overrides):
    return {card["id"] for card in case.build_case(case_context(**overrides))}


def test_the_case_is_built_from_the_current_data():
    cards = case.build_case(case_context())
    check(len(cards) >= 8, f"expected a full case, got {len(cards)} cards")
    check(cards[0]["id"] == "what_the_market_gives_us",
          "this week's price leads -- one game at a time")
    for card in cards:
        for key in ("id", "stat", "label", "detail", "source", "priority"):
            check(key in card, f"{card.get('id')} is missing {key}")
        check(card["source"], "every claim must carry where it came from")


def test_a_losing_semi_final_record_is_not_advertised():
    losing = {"stage": "Semi-final", "played": 6, "won": 1, "lost": 5}
    check("semi_final_pedigree" not in
          ids_for(by_stage={"Semi-final": losing}),
          "a losing record must not be dressed up as a selling point")


def test_the_semi_final_card_only_fires_for_a_semi_final():
    check("semi_final_pedigree" not in ids_for(next_stage="Preliminary Finals"),
          "the semi-final record is only the argument when a semi is next")


def test_nothing_quotes_a_premiership_probability():
    """One game at a time: a flag probability five weeks out excites nobody."""
    cards = case.build_case(case_context())
    check("one_win_away" not in {c["id"] for c in cards},
          "the 'for the flag if we win' card is retired")
    check("favoured_in_the_decider" not in {c["id"] for c in cards},
          "the Grand Final matchup card is retired")
    for card in cards:
        text = (card["label"] + " " + card["detail"]).lower()
        check("for the flag" not in text and "premiership probability" not in text,
              f"{card['id']} still talks about winning the flag: {card['label']}")


def test_the_price_leads_and_names_the_opponent():
    lead = case.build_case(case_context())[0]
    check(lead["stat"] == "39.1%", f"the market price should lead, got {lead['stat']}")
    check("Fremantle" in lead["label"], "the lead card names who we are playing")
    check("38.0%" in lead["detail"],
          "and notes the models rate us lower still")


def test_the_price_falls_back_to_the_models_without_a_market():
    lead = case.build_case(case_context(market_probability=None))[0]
    check(lead["stat"] == "38.0%",
          "with no bookmaker price, quote the model consensus rather than nothing")


def test_a_tight_season_series_is_the_argument():
    cards = {c["id"]: c for c in case.build_case(case_context())}
    check("one_point_in_it" in cards, "200-199 across two games is the story")
    check(cards["one_point_in_it"]["stat"] == "1", "one point in it")
    # A blowout series is not an argument for us.
    blown = ids_for(season_series=[
        {"round": 15, "venue": "Perth Stadium", "club_is_home": False,
         "our_score": 40, "their_score": 120, "margin": -80},
        {"round": 1, "venue": "Kardinia Park", "club_is_home": True,
         "our_score": 60, "their_score": 110, "margin": -50},
    ])
    check("one_point_in_it" not in blown,
          "when they have thrashed us twice, that is not a selling point")
    check("we_have_beaten_them" not in blown,
          "and we cannot claim a win we did not have")


def test_the_ground_card_waits_for_a_confirmed_venue():
    winning_ground = {"M.C.G.": {"venue": "M.C.G.", "played": 24,
                                 "won": 13, "lost": 11}}
    check("finals_at_this_ground" in
          ids_for(next_venue="M.C.G.", by_venue=winning_ground),
          "a winning record at a confirmed ground is worth saying")
    check("finals_at_this_ground" not in
          ids_for(next_venue="M.C.G.", by_venue=winning_ground,
                  next_venue_provisional=True),
          "but not while the AFL has not actually confirmed the ground")


def test_percentage_card_only_fires_when_it_flatters_us():
    check("better_than_our_ladder_position" in ids_for(),
          "3rd on percentage having finished 5th is a fair point to make")
    check("better_than_our_ladder_position" not in
          ids_for(ladder_rank=3, percentage_rank=5),
          "if percentage is WORSE than where we finished, stay quiet")


def test_streak_claim_is_checked_against_rivals():
    strong = case.build_case(case_context())
    streak = [c for c in strong if c["id"] == "winning_streak"][0]
    check("longest active run" in streak["detail"],
          "7 beats every rival here, so the claim is allowed")

    outgunned = case.build_case(case_context(rival_streaks={"Hawthorn": 11}))
    beaten = [c for c in outgunned if c["id"] == "winning_streak"][0]
    check("longest active run" not in beaten["detail"],
          "a side on a longer run means we must not claim the best form")


def test_a_short_streak_is_not_spun_as_form():
    check("winning_streak" not in ids_for(win_streak=1),
          "one win is not a run of form")


def test_an_unbeaten_opponent_gets_no_wounded_card():
    check("opponent_is_wounded" not in ids_for(opponent_last_loss=None),
          "if the opponent won last week, we don't get to say they're wounded")


def test_a_coach_without_a_flag_is_not_credited_with_one():
    check("a_coach_who_has_done_it" not in ids_for(by_stage={
        "Grand Final": {"stage": "Grand Final", "played": 2, "won": 0, "lost": 2}}),
          "no premierships means no premierships card")


# --- the live data --------------------------------------------------------

def test_committed_state_is_internally_consistent():
    path = os.path.join(ROOT, "data", "state.json")
    if not os.path.exists(path):
        print("  (skipped live-data checks: data/state.json not built yet)")
        return
    with open(path, encoding="utf-8") as handle:
        state = json.load(handle)

    total = sum(row["probability"] for row in state["field"])
    check(close(total, 1.0, 1e-3), f"published field must sum to 1, got {total}")

    headline = state["headline"]
    product = 1.0
    for step in headline["steps"]:
        product *= step["conditional_probability"]
    check(close(product, headline["probability"], 1e-4),
          "published legs must multiply back to the published headline")
    check(0.0 <= headline["probability"] <= 1.0, "headline is a probability")
    check(headline["probability"] <= headline["reaches_grand_final"] + 1e-9,
          "you cannot win the flag more often than you reach the grand final")

    fit = state["method"]["calibration"]
    check(fit["diagnostics"]["margin_fit_r_squared"] > 0.5,
          "a fit this weak should not be driving the headline")
    check(0 < fit["home_ground_points"] < 30 and 0 < fit["interstate_travel_points"] < 30,
          "home-ground and travel effects should land in a plausible points range")
    check(fit["logit_per_point"] > 0, "a bigger predicted margin must mean a better chance")


def main():
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failures = []
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failures.append((test.__name__, exc))
            print(f"FAIL {test.__name__}\n     {exc}")
        else:
            print(f"ok   {test.__name__}")
    print(f"\n{len(tests) - len(failures)}/{len(tests)} tests passed, {checks} assertions")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
