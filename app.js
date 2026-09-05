/* Nine Lives — reads the JSON the fetch script committed and renders it.
   No API calls from the browser: CORS would block them, and a page that
   depends on a live third-party request breaks the moment that request fails.

   Rule followed throughout: if a value isn't in the data, show a visible gap.
   Never substitute a plausible-looking number for a missing one. */

(function () {
  "use strict";

  var REDUCED_MOTION =
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var STALE_WARN_HOURS = 2;
  var STALE_BAD_HOURS = 6;

  // ---- small helpers ----------------------------------------------------

  function $(selector) { return document.querySelector(selector); }
  function field(name) { return document.querySelector('[data-field="' + name + '"]'); }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  /** A visible hole, so a missing figure can never be mistaken for a real one. */
  function gap(reason) {
    return el("span", "gap", reason || "not available");
  }

  function percent(value, places) {
    if (typeof value !== "number" || !isFinite(value)) return null;
    return (value * 100).toFixed(places === undefined ? 1 : places) + "%";
  }

  /** A win rate reads harder than a won-lost line: 83% beats 5–1. */
  function record(row) {
    if (!row || !row.played) return "—";
    return Math.round((row.won / row.played) * 100) + "%";
  }

  function recordDetail(row) {
    if (!row || !row.played) return null;
    return row.won + "–" + row.lost;
  }

  // Just enough English to avoid "8 storys".
  var IRREGULAR_PLURALS = { story: "stories", flag: "flags", win: "wins" };

  function plural(count, word) {
    if (count === 1) return count + " " + word;
    return count + " " + (IRREGULAR_PLURALS[word] || word + "s");
  }

  /** A bare duration for "in the past ___" — no "ago", no leading 1. */
  function durationPhrase(seconds) {
    var minutes = Math.round(seconds / 60);
    if (minutes < 90) return minutes < 2 ? "minute" : minutes + " minutes";
    var hours = Math.round(minutes / 60);
    if (hours < 36) return hours < 2 ? "hour" : hours + " hours";
    var days = Math.round(hours / 24);
    return days < 2 ? "day" : days + " days";
  }

  function describeAge(seconds) {
    if (seconds < 90) return "just now";
    var minutes = Math.round(seconds / 60);
    if (minutes < 60) return plural(minutes, "minute") + " ago";
    var hours = Math.round(minutes / 60);
    if (hours < 36) return plural(hours, "hour") + " ago";
    return plural(Math.round(hours / 24), "day") + " ago";
  }

  function formatLocal(iso) {
    var when = new Date(iso);
    if (isNaN(when.getTime())) return null;
    try {
      return new Intl.DateTimeFormat(undefined, {
        weekday: "short", day: "numeric", month: "short",
        hour: "numeric", minute: "2-digit", timeZoneName: "short"
      }).format(when);
    } catch (err) {
      return when.toString();
    }
  }

  function loadJSON(path) {
    // An offline snapshot bakes the data in rather than fetching it.
    var bundled = window.__NINE_LIVES_DATA;
    if (bundled && bundled[path]) return Promise.resolve(bundled[path]);

    // Pages caches aggressively; the whole point of the manual refresh button
    // is being able to watch the number move, so bypass it.
    return fetch(path + "?t=" + Date.now(), { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) throw new Error(path + " -> HTTP " + response.status);
        return response.json();
      });
  }

  // ---- 1. the headline --------------------------------------------------

  /* The page leads with the strongest case the data currently supports, not
     with the compound probability of winning every remaining game. That is an
     editorial choice about emphasis: the unconditional number is still shown,
     in the method panel, and every figure here is the real one. */
  function renderHeadline(state, history) {
    var headline = state.headline || {};
    var lead = (state.case || [])[0];
    var node = field("probability");

    if (!lead) {
      // No case survived the checks -- fall back to the plain probability
      // rather than showing nothing.
      if (typeof headline.probability !== "number") {
        node.textContent = "";
        node.appendChild(gap("no figure"));
        return;
      }
      countUp(node, headline.probability);
      field("hero-label").textContent = "for the premiership";
    } else if (/^[\d.]+%$/.test(lead.stat)) {
      countUp(node, parseFloat(lead.stat) / 100);
      field("hero-label").textContent = lead.label;
    } else {
      node.textContent = lead.stat;
      field("hero-label").textContent = lead.label;
    }

    // One game at a time. Nothing up here mentions the Grand Final: a
    // premiership probability five weeks out excites nobody, and the number
    // that matters this week is the one on Saturday's game.
    var fixture = state.next_fixture;
    field("hero-title").textContent = fixture
      ? (fixture.stage || "Next match") + " · v " + fixture.opponent
      : "The case for Geelong";

    var supporting = (state.case || []).length - 1;
    field("figure-note").textContent = supporting > 0
      ? supporting + " reasons that number looks light."
      : "";

    renderDelta(state, history);
    renderMethod(state);
    renderCase(state);
  }

  var NUMBER_WORDS = ["no", "one", "two", "three", "four", "five", "six",
                      "seven", "eight", "nine", "ten", "eleven", "twelve"];

  function renderCase(state) {
    var list = field("case");
    list.textContent = "";
    // The lead card is the headline; the rest make up the argument.
    var cards = (state.case || []).slice(1);

    // Count the cards rather than hardcoding a number in the heading -- rules
    // drop out when they stop being true, and a heading promising nine reasons
    // over eight of them is the sort of thing a nephew notices.
    var word = NUMBER_WORDS[cards.length] || String(cards.length);
    field("case-title").textContent =
      word.charAt(0).toUpperCase() + word.slice(1) + " reasons to believe";

    if (!cards.length) {
      var empty = document.createElement("li");
      empty.appendChild(gap("nothing in the data supports a case right now"));
      list.appendChild(empty);
      return;
    }

    cards.forEach(function (card) {
      var item = document.createElement("li");
      item.appendChild(el("div", "case-stat", card.stat));
      item.appendChild(el("div", "case-label", card.label));
      item.appendChild(el("div", "case-detail", card.detail));
      item.appendChild(el("div", "case-source", card.source));
      list.appendChild(item);
    });
  }

  function ordinal(n) {
    // 11th, 12th and 13th break the usual pattern.
    if (n % 100 >= 11 && n % 100 <= 13) return n + "th";
    return n + ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th");
  }

  function countUp(node, target) {
    var text = percent(target);
    if (REDUCED_MOTION) { node.textContent = text; return; }
    var started = null;
    var duration = 900;
    function frame(now) {
      if (started === null) started = now;
      var t = Math.min((now - started) / duration, 1);
      var eased = 1 - Math.pow(1 - t, 3);
      node.textContent = percent(target * eased);
      if (t < 1) requestAnimationFrame(frame);
      else node.textContent = text;
    }
    requestAnimationFrame(frame);
  }

  /** Movement since roughly a day ago, so the number has a direction. */
  function renderDelta(state, history) {
    var node = field("delta");
    var lead = (state.case || [])[0];
    // Track whatever the headline is actually showing, not a different number.
    var tracking = lead && lead.id === "what_the_experts_give_us"
      ? "models_next_game" : "probability";
    var current = tracking === "models_next_game"
      ? parseFloat(lead.stat) / 100 : state.headline.probability;

    if (!Array.isArray(history) || history.length < 2 ||
        typeof current !== "number") {
      node.textContent = "no earlier reading to compare against yet";
      return;
    }

    var now = Date.now();
    var wanted = now - 24 * 3600 * 1000;
    var baseline = null;
    for (var i = 0; i < history.length; i++) {
      var at = new Date(history[i].at).getTime();
      if (isNaN(at) || now - at < 3600 * 1000) continue;      // too recent to be a baseline
      if (typeof history[i][tracking] !== "number") continue;
      if (!baseline || Math.abs(at - wanted) < Math.abs(baseline.time - wanted)) {
        baseline = { time: at, probability: history[i][tracking] };
      }
    }
    if (!baseline || typeof baseline.probability !== "number") {
      node.textContent = "no earlier reading to compare against yet";
      return;
    }

    var move = (current - baseline.probability) * 100;
    var since = durationPhrase((now - baseline.time) / 1000);
    if (Math.abs(move) < 0.05) {
      node.removeAttribute("data-dir");
      node.textContent = "hasn't budged in the past " + since;
      return;
    }
    node.setAttribute("data-dir", move > 0 ? "up" : "down");
    // "points" would read as a score in an AFL context, so be explicit.
    node.textContent = (move > 0 ? "▲ drifting our way — " : "▼ ") +
      Math.abs(move).toFixed(1) + " percentage points in the past " + since;
  }

  function renderMethod(state) {
    var method = state.method || {};
    field("method-description").textContent = method.description || "";

    var list = field("legs");
    list.textContent = "";
    var steps = (state.headline || {}).steps || [];

    if (!steps.length) {
      list.appendChild(el("li", null, "Nothing left to play."));
    }

    var product = [];
    steps.forEach(function (step) {
      var item = document.createElement("li");

      var stage = el("div", "leg-stage");
      stage.appendChild(document.createTextNode(step.stage + " "));
      var published = step.source_kind === "published";
      stage.appendChild(el("span", "tag " + (published ? "tag-published" : "tag-fitted"),
        published ? "published" : "fitted"));
      item.appendChild(stage);

      item.appendChild(el("div", "leg-prob", percent(step.conditional_probability, 1)));

      var opponents = (step.opponents || []).slice(0, 3).map(function (o) {
        return o.probability >= 0.999
          ? o.team
          : o.team + " " + percent(o.probability, 0);
      }).join(", ");
      var venues = (step.possible_venues || []).join(" or ");
      item.appendChild(el("div", "leg-detail",
        (opponents || "opponent unknown") + (venues ? " · " + venues : "")));

      list.appendChild(item);
      product.push((step.conditional_probability * 100).toFixed(1) + "%");
    });

    field("method-product").textContent = steps.length
      ? product.join("  ×  ") + "  =  " + percent(state.headline.probability) +
        " to win every remaining game"
      : "";

    renderFit(method.calibration);
  }

  function renderFit(calibration) {
    var list = field("fit");
    list.textContent = "";
    if (!calibration) { list.appendChild(gap("fit diagnostics missing")); return; }
    var d = calibration.diagnostics || {};

    function points(value) {
      return typeof value === "number" ? value.toFixed(1) + " points" : null;
    }

    var rows = [
      ["Home ground worth", points(calibration.home_ground_points)],
      ["Interstate trip worth", points(calibration.interstate_travel_points)],
      ["Fit quality (R²)", d.margin_fit_r_squared],
      ["Typical error", points(d.margin_fit_rmse_points)],
      ["Fitted on", d.margin_fit_games + " games from round " + d.margin_fit_from_round],
      ["Checked against", d.finals_holdout_games + " finals, " +
        points(d.finals_holdout_rmse_points) + " error"]
    ];

    rows.forEach(function (row) {
      list.appendChild(el("dt", null, row[0]));
      var dd = document.createElement("dd");
      if (row[1] === undefined || row[1] === null || /null|undefined/.test(String(row[1]))) {
        dd.appendChild(gap("—"));
      } else {
        dd.textContent = row[1];
      }
      list.appendChild(dd);
    });
  }

  // ---- 2. the Chris Scott era ------------------------------------------

  function renderScottEra(state) {
    var era = state.scott_era;
    var strip = field("scott-strip");
    strip.textContent = "";

    if (!era) { strip.appendChild(gap("finals history not available")); return; }

    field("scott-range").textContent =
      "Sixteen seasons, " + era.seasons_playing_finals + " finals campaigns, " +
      "two flags. Not many clubs have had it this good for this long.";

    var overall = era.overall || {};
    var semis = (era.by_stage || []).filter(function (s) { return s.stage === "Semi-final"; })[0];

    var flags = (era.by_stage || []).filter(function (s) {
      return s.stage === "Grand Final";
    })[0];

    var stats = [
      { value: flags ? flags.won : null, label: "Premierships", tone: "stat-strong" },
      { value: semis ? record(semis) : null, label: "Semi-finals won", tone: "stat-strong" },
      { value: era.grand_finals_reached, label: "Grand Finals", tone: "" },
      { value: era.seasons_playing_finals, label: "Finals series", tone: "" }
    ];

    stats.forEach(function (stat) {
      var box = el("div", "stat " + (stat.tone || ""));
      var value = el("span", "stat-value");
      if (stat.value === null || stat.value === undefined) value.appendChild(gap("—"));
      else value.textContent = stat.value;
      box.appendChild(value);
      box.appendChild(el("span", "stat-label", stat.label));
      strip.appendChild(box);
    });

    fillRecordList(field("scott-stages"),
      (era.by_stage || []).concat(overall.played
        ? [{ stage: "Every final since 2011", won: overall.won,
             lost: overall.lost, played: overall.played }]
        : []),
      function (row) {
        return { label: row.stage, value: record(row),
                 note: recordDetail(row), row: row };
      });

    renderDefence(state);

    var recent = field("scott-recent");
    recent.textContent = "";
    (era.recent || []).forEach(function (game) {
      var item = document.createElement("li");
      item.setAttribute("data-result", game.result);
      item.appendChild(el("span", "form-result", game.result));
      var margin = (game.margin > 0 ? "+" : "") + game.margin;
      item.appendChild(el("span", "form-meta", game.year + " " + margin));
      item.appendChild(el("span", "form-meta", "v " + game.opponent));
      recent.appendChild(item);
    });
    if (!(era.recent || []).length) recent.appendChild(el("li", null, "—"));
  }

  /* Bare records are unkind. This is the rest of what the scoreboard doesn't
     say about the finals we lost -- all of it from the results themselves. */
  function renderDefence(state) {
    var d = state.in_our_defence;
    var list = field("defence");
    if (!list) return;
    list.textContent = "";

    if (!d || !d.losses) {
      field("defence-note").textContent = "";
      return;
    }

    [
      // Noun phrases, so the row reads left to right: label, then count.
      { label: "Losses to the side that won the flag that year",
        count: d.to_eventual_premier,
        note: "you can only lose to the best team in the competition so often "
              + "before it stops being a flaw" },
      { label: "Losses away from home",
        count: d.away_from_home,
        note: "September on the road is a different sport" },
      { label: "Losses by two goals or less",
        count: d.within_two_goals,
        note: "a kick here or there and this page reads very differently" }
    ].forEach(function (row) {
      if (!row.count) return;
      var item = document.createElement("li");
      var left = el("span", null, row.label);
      left.appendChild(document.createTextNode(" "));
      left.appendChild(el("span", "record-note", row.note));
      item.appendChild(left);
      var value = el("span", "record-value", row.count + " of " + d.losses);
      value.setAttribute("data-tone", "level");
      item.appendChild(value);
      list.appendChild(item);
    });

    field("defence-note").textContent =
      d.premier_bound_or_close + " of our " + d.losses + " finals defeats since " +
      d.from_year + " came against the eventual premier or by less than two " +
      "goals. " + (d.no_team_news || "");
  }

  function fillRecordList(list, rows, shape) {
    list.textContent = "";
    if (!rows || !rows.length) {
      var empty = document.createElement("li");
      empty.appendChild(gap("no records"));
      list.appendChild(empty);
      return;
    }
    rows.forEach(function (row) {
      var mapped = shape(row);
      var item = document.createElement("li");
      var left = el("span", null, mapped.label);
      if (mapped.note) {
        left.appendChild(document.createTextNode(" "));
        left.appendChild(el("span", "record-note", mapped.note));
      }
      item.appendChild(left);
      var value = el("span", "record-value", mapped.value);
      if (mapped.row && mapped.row.played) {
        value.setAttribute("data-tone",
          mapped.row.won > mapped.row.lost ? "good"
            : mapped.row.won === mapped.row.lost ? "level" : "quiet");
      }
      item.appendChild(value);
      list.appendChild(item);
    });
  }

  // ---- word from the club -----------------------------------------------

  /* Headlines here are written by somebody else. They go in as text, never as
     markup, and the link is only rendered if the fetch script kept one -- it
     drops anything that doesn't point at afl.com.au. */
  function renderNews(state) {
    var feed = state.news || {};
    var list = field("news");
    if (!list) return;
    list.textContent = "";

    var items = feed.items || [];
    if (!items.length) {
      var empty = document.createElement("li");
      empty.appendChild(gap(feed.error
        ? "the AFL feed is not answering right now"
        : "nothing about our campaign in the feed yet"));
      list.appendChild(empty);
      field("news-sub").textContent = "";
      field("news-note").textContent = feed.error
        ? "Everything else on this page is unaffected — the news feed is kept "
          + "separate so it cannot take the football down with it."
        : "";
      return;
    }

    var ours = items.filter(function (i) {
      return (i.about || []).indexOf(state.club) !== -1;
    }).length;
    field("news-sub").textContent =
      plural(items.length, "story") + " worth knowing about" +
      (ours ? ", " + ours + " of them about us" : "") + ".";

    items.forEach(function (item) {
      var entry = document.createElement("li");
      entry.setAttribute("data-club",
        String((item.about || []).indexOf(state.club) !== -1));

      var headline;
      if (item.link) {
        headline = document.createElement("a");
        headline.href = item.link;
        headline.rel = "noopener noreferrer";
        headline.target = "_blank";
        headline.textContent = item.title;
      } else {
        headline = el("div", "news-title", item.title);
      }
      entry.appendChild(headline);

      var meta = el("div", "news-meta");
      if (item.is_team_news) meta.appendChild(el("span", "tag tag-warn", "team news"));
      (item.about || []).forEach(function (team) {
        meta.appendChild(el("span", "tag tag-published", team));
      });
      if (item.published_utc) {
        var age = (Date.now() - new Date(item.published_utc).getTime()) / 1000;
        meta.appendChild(el("span", null, describeAge(age)));
      }
      entry.appendChild(meta);
      list.appendChild(entry);
    });

    var note = "Headlines from AFL.com.au, picked out by who they mention. ";
    if (feed.stale) {
      note += "The feed is not answering at the moment, so these are the last " +
        "ones that came through. ";
    }
    field("news-note").textContent = note +
      "Tagging is done by keyword, so the odd stray will slip in.";
  }

  // ---- September, and this lot ------------------------------------------

  /** A supporter's read on a head-to-head record, built from the games. */
  function h2hLine(row, club) {
    if (!row.played) {
      return "Never met them in September. No history, no scar tissue, " +
        "nothing to be frightened of.";
    }
    var best = row.biggest_win;
    var recent = row.most_recent;
    var parts = [];

    if (best) {
      parts.push("We put " + best.margin + " points on them in " + best.year +
        (/grand final/i.test(best.stage || "") ? " — in a Grand Final." :
         /preliminary/i.test(best.stage || "") ? " — in a preliminary final." :
         /semi/i.test(best.stage || "") ? " — in a semi-final, the same game " +
           "we are playing now." : "."));
    }
    // Don't say "and the last time we met..." about the game just quoted.
    var recentIsBest = best && recent &&
      recent.year === best.year && recent.margin === best.margin;

    if (recentIsBest || !best) {
      // Nothing to add: either the biggest win is also the most recent
      // meeting, or there are no wins and the line below covers it.
    } else if (recent && !recent.won) {
      var since = new Date().getFullYear() - recent.year;
      parts.push(since > 6
        ? "The last time they beat us in a final was " + recent.year +
          ", which is " + since + " years and about three lists ago."
        : "They got us in " + recent.year + ", by " +
          Math.abs(recent.margin) + ". We owe them one.");
    } else if (recent && recent.won) {
      parts.push("Last time we met in September, " + recent.year +
        ", we won by " + recent.margin + ".");
    }
    if (!best) {
      parts.push("Beaten by " + Math.abs(recent.margin) + " in " + recent.year +
        ". One game is not a hoodoo, it is one game.");
    }
    return parts.join(" ");
  }

  function renderHeadToHead(state) {
    var data = state.finals_head_to_head;
    var host = field("h2h");
    if (!data || !host) return;
    host.textContent = "";

    field("h2h-sub").textContent =
      "Every final we have played against the sides still standing, back to " +
      data.from_year + ". In the order we could meet them. Tap any of them " +
      "for the games.";

    (data.teams || []).forEach(function (row, index) {
      var box = document.createElement("details");
      box.className = "h2h";

      var summary = document.createElement("summary");
      var name = el("div", "h2h-team", row.team);
      if (index === 0) name.appendChild(el("span", "h2h-when", "Saturday"));
      summary.appendChild(name);

      var rate = el("div", "h2h-rate",
        row.played ? Math.round(row.win_rate * 100) + "%" : "—");
      rate.setAttribute("data-tone",
        !row.played ? "level"
          : row.won > row.lost ? "good"
          : row.won === row.lost ? "level" : "quiet");
      summary.appendChild(rate);

      summary.appendChild(el("div", "h2h-line",
        (row.played ? row.won + "–" + row.lost + " in finals. " : "") +
        h2hLine(row, state.club)));
      box.appendChild(summary);

      var list = document.createElement("ol");
      (row.meetings || []).forEach(function (game) {
        var item = document.createElement("li");
        item.setAttribute("data-won", String(game.won));
        item.appendChild(el("span", "m-year", game.year));
        var where = el("span", null,
          (game.stage || "").replace("Finals Week 1", "Week 1 final")
            .replace("Preliminary Finals", "Preliminary final")
            .replace("Semi-Finals", "Semi-final") +
          " · " + game.venue);
        // Say what the scoreboard leaves out about a defeat.
        if (!game.won) {
          if (game.opponent_won_flag) {
            where.appendChild(document.createTextNode(" "));
            where.appendChild(el("span", "tag tag-warn", "they won the flag"));
          } else if (!game.at_home) {
            where.appendChild(document.createTextNode(" "));
            where.appendChild(el("span", "tag tag-warn", "away"));
          }
        }
        item.appendChild(where);
        item.appendChild(el("span", "m-margin",
          (game.margin > 0 ? "+" : "") + game.margin));
        list.appendChild(item);
      });
      if (!row.meetings.length) {
        var none = document.createElement("li");
        none.appendChild(el("span", null, "No finals meetings on record."));
        list.appendChild(none);
      }
      box.appendChild(list);
      host.appendChild(box);
    });
  }

  // ---- it has been done -------------------------------------------------

  function renderPrecedent(state) {
    var p = state.precedent;
    if (!p) return;

    var position = ordinal(p.ladder_position || 5);
    var flags = p.flags_from_here || [];

    field("precedent-sub").textContent = flags.length
      ? "Sides who finished " + position + " or lower and won the whole thing " +
        "anyway, since " + p.from_year + ". Two of them. One of them was the " +
        "year before last, and they took our exact road."
      : "Nobody has done it from here since " + p.from_year +
        ". Somebody has to be first.";

    var host = field("precedent-paths");
    host.textContent = "";

    flags.forEach(function (run, index) {
      var box = el("div", "roadmap");
      var head = el("div", "roadmap-head");
      head.appendChild(document.createTextNode(run.year + " · "));
      head.appendChild(el("b", null, run.team));
      head.appendChild(document.createTextNode(
        " — finished " + ordinal(run.position)));
      box.appendChild(head);

      var away = (run.path || []).filter(function (g) { return !g.at_home; }).length;
      var beatUs = (run.path || []).filter(function (g) {
        return g.opponent === state.club;
      })[0];

      var line = index === 0
        ? "Same ladder spot as us. Same elimination final. Same road."
        : plural(away, "away final") + " on the bounce, and they won the lot.";
      // No point pretending we don't remember.
      if (beatUs) {
        line += " Yes, that " +
          (beatUs.stage || "").toLowerCase().replace("preliminary finals", "prelim")
            .replace("finals week 1", "final").replace("semi-finals", "semi") +
          " was against us. We have not forgotten.";
      }
      box.appendChild(el("div", "roadmap-sub", line));

      var list = document.createElement("ol");
      (run.path || []).forEach(function (game) {
        var item = document.createElement("li");
        item.appendChild(el("span", "rm-stage",
          (game.stage || "").replace("Finals Week 1", "Elimination")
            .replace("Preliminary Finals", "Prelim")
            .replace("Semi-Finals", "Semi")));
        var line = el("span", null, "v " + game.opponent + " ");
        if (!game.at_home) line.appendChild(el("span", "rm-away", "away"));
        item.appendChild(line);
        item.appendChild(el("span", "rm-margin",
          (game.margin > 0 ? "+" : "") + game.margin));
        list.appendChild(item);
      });
      box.appendChild(list);
      host.appendChild(box);
    });

    // The odds facing a side in our exact seat, and how we compare to them.
    var stats = field("precedent-stats");
    stats.textContent = "";

    var ours = (state.next_fixture || {}).club_win_probability;
    var rows = [];

    if (typeof p.visitor_win_rate === "number") {
      rows.push({
        label: "Visitors have won this many semi-finals since " + p.from_year,
        value: percent(p.visitor_win_rate, 0),
        note: typeof ours === "number" && ours > p.visitor_win_rate
          ? "we are rated " + percent(ours, 0) + " — better than the average side in our seat"
          : "the away side is always up against it, and always has been"
      });
    }
    if (typeof p.flag_rate_after_winning_semi === "number") {
      rows.push({
        label: "Win the semi and this many go on to lift the cup",
        value: percent(p.flag_rate_after_winning_semi, 0),
        note: p.semi_winners_to_flag + " of " + p.semi_finals +
              " since " + p.from_year + " — better than one in seven"
      });
    }
    if (p.semi_winners_to_grand_final) {
      rows.push({
        label: "And this many reach the Grand Final",
        value: percent(p.semi_winners_to_grand_final / p.semi_finals, 0),
        note: "one in four. We have been worse places."
      });
    }

    rows.forEach(function (row) {
      var item = document.createElement("li");
      var left = el("span", null, row.label);
      left.appendChild(document.createTextNode(" "));
      left.appendChild(el("span", "record-note", row.note));
      item.appendChild(left);
      var value = el("span", "record-value", row.value);
      value.setAttribute("data-tone", "good");
      item.appendChild(value);
      stats.appendChild(item);
    });

    field("precedent-note").textContent =
      "Nobody is pretending this is the easy way round. Brisbane were not " +
      "supposed to do it in 2024 either, and they went and won three finals " +
      "away from home to get there. Somebody wins it from fifth. It may as " +
      "well be us.";
  }

  // ---- Geelong, the greatest team of all --------------------------------

  function renderGreatest(state) {
    var d = state.dominance;
    var strip = field("greatest-strip");
    var table = field("greatest-table");
    strip.textContent = "";
    table.textContent = "";

    if (!d || !d.club) {
      strip.appendChild(gap("league records not available"));
      return;
    }

    var us = d.club, ranks = d.ranks || {}, next = d.next_best;

    field("greatest-sub").textContent =
      "Since " + d.from_year + ", across " + d.clubs_compared +
      " clubs and " + us.played + " games, nobody has won more often than us.";

    [
      { value: percent(us.win_rate, 1), label: "Win rate since " + d.from_year,
        rank: ranks.win_rate },
      { value: us.won + "–" + us.lost, label: "Won–lost", rank: null },
      { value: us.finals, label: "Finals played", rank: ranks.finals },
      { value: us.finals_series, label: "Finals series", rank: ranks.finals_series }
    ].forEach(function (stat) {
      var box = el("div", "stat" + (stat.rank === 1 ? " stat-strong" : ""));
      box.appendChild(el("span", "stat-value", stat.value));
      box.appendChild(el("span", "stat-label",
        stat.label + (stat.rank === 1 ? " · No.1" : "")));
      strip.appendChild(box);
    });

    (d.table || []).forEach(function (row, index) {
      var item = document.createElement("li");
      var isUs = row.team === state.club;
      item.setAttribute("data-club", String(isUs));
      item.appendChild(el("span", "league-pos", index + 1));
      item.appendChild(el("span", "league-team", row.team));
      item.appendChild(el("span", "league-value", percent(row.win_rate, 1)));
      item.appendChild(el("span", "league-sub",
        row.won + "–" + row.lost + " · " + row.finals + " finals · " +
        plural(row.flags, "flag")));
      table.appendChild(item);
    });

    if (next) {
      var gap_ = (us.win_rate - next.win_rate) * 100;
      field("greatest-note").textContent =
        next.team + " are next, " + gap_.toFixed(1) +
        " points back over fifteen years. That is not a hot streak. " +
        "That is a dynasty, and it has not finished yet.";
    }

    renderBoards(d, state.club);
  }

  function renderBoards(dominance, club) {
    var host = field("greatest-boards");
    host.textContent = "";

    (dominance.leaderboards || []).forEach(function (board) {
      var box = el("div", "board");
      box.appendChild(el("p", "board-title", board.label));

      // "Number 3 in the league" undersells being level on the count and one
      // off the lead. Say how close it actually is.
      var ourRow = board.rows.filter(function (r) { return r.team === club; })[0];
      var leader = board.rows[0];
      var text;
      if (board.our_rank === 1) {
        text = "No club has more";
      } else if (ourRow && leader) {
        var place = ordinal(board.our_rank);
        var behind = plural(leader.value - ourRow.value,
                            board.unit.replace(/s$/, ""));
        text = (ourRow.shared ? "Equal " + place : place) +
          " — " + behind + " off the lead";
      } else {
        text = "Number " + board.our_rank + " in the league";
      }
      var verdict = el("p", "board-verdict", text);
      verdict.setAttribute("data-top", String(board.our_rank === 1));
      box.appendChild(verdict);

      var list = document.createElement("ol");
      board.rows.forEach(function (row) {
        var item = document.createElement("li");
        item.setAttribute("data-club", String(row.team === club));
        item.appendChild(el("span", "board-pos",
          (row.shared ? "=" : "") + row.position));
        item.appendChild(el("span", null, row.team));
        item.appendChild(el("span", "board-value", row.value));
        list.appendChild(item);
      });
      box.appendChild(list);
      host.appendChild(box);
    });
  }

  // ---- what the tipsters make of it -------------------------------------

  function renderExperts(state) {
    var panel = state.experts || {};
    var list = field("experts");
    list.textContent = "";

    if (!panel.tips || !panel.tips.length) {
      var empty = document.createElement("li");
      empty.appendChild(gap("nobody has priced this game yet"));
      list.appendChild(empty);
      field("experts-sub").textContent =
        "The tipsters publish once the fixture is confirmed. Check back.";
      return;
    }

    var backing = panel.tipping_club;
    field("experts-sub").textContent = backing
      ? backing + " of " + panel.counted + " have us winning it — and the rest " +
        "have not been to Kardinia Park on a Friday night."
      : panel.counted + " have priced it so far, and not one of them is " +
        "tipping us. Good. We have never gone better than when nobody fancies us.";

    panel.tips.forEach(function (tip, index) {
      var item = document.createElement("li");
      item.setAttribute("data-market", String(Boolean(tip.is_market)));
      item.appendChild(el("span", "expert-pos", index + 1));
      var name = el("span", "expert-name", tip.source);
      if (tip.is_market) {
        name.appendChild(document.createTextNode(" "));
        name.appendChild(el("span", "tag tag-warn", "the bookies"));
      } else if (tip.is_consensus) {
        name.appendChild(document.createTextNode(" "));
        name.appendChild(el("span", "tag tag-published", "consensus"));
      }
      item.appendChild(name);
      item.appendChild(el("span", "expert-value", percent(tip.club_probability)));
      item.appendChild(el("span", "expert-sub",
        (tip.club_margin >= 0 ? "has us by " + tip.club_margin
          : "has us down by " + Math.abs(tip.club_margin)) + " points"));
      list.appendChild(item);
    });
  }

  // ---- 3. next fixture --------------------------------------------------

  var clocks = [];

  /** Both clocks tick off one interval. */
  function startClocks() {
    if (window.__nineLivesClock) clearInterval(window.__nineLivesClock);

    function tick() {
      var now = Date.now();
      clocks.forEach(function (clock) {
        var remaining = Math.floor((clock.at - now) / 1000);
        if (remaining <= 0) {
          clock.node.textContent = clock.done;
          return;
        }
        var days = Math.floor(remaining / 86400);
        var hours = Math.floor(remaining / 3600) % 24;
        var mins = Math.floor(remaining / 60) % 60;
        var secs = remaining % 60;

        clock.node.textContent = "";
        [[days, "d"], [hours, "h"], [mins, "m"], [secs, "s"]]
          .forEach(function (part, index) {
            if (index === 0 && !days) return;   // no "0d" on the last day
            var value = index > 0 && part[0] < 10 ? "0" + part[0] : String(part[0]);
            clock.node.appendChild(document.createTextNode(value));
            clock.node.appendChild(el("small", null, part[1]));
          });
      });
    }
    tick();
    window.__nineLivesClock = setInterval(tick, 1000);
  }

  function addClock(nodeName, at, done) {
    var node = field(nodeName);
    var when = new Date(at).getTime();
    if (!node || isNaN(when)) return false;
    clocks.push({ node: node, at: when, done: done });
    return true;
  }

  function renderCountdowns(state) {
    clocks = [];

    var fixture = state.next_fixture;
    if (fixture && addClock("cd-next-clock", fixture.start_utc, "Under way!")) {
      field("cd-next-sub").textContent =
        state.club + " v " + fixture.opponent + " · " +
        (fixture.venue || "venue still to be locked in");
    } else {
      field("cd-next").hidden = true;
    }

    var decider = state.grand_final;
    if (decider && !decider.complete &&
        addClock("cd-glory-clock", decider.start_utc, "It is happening.")) {
      // Venue names like "M.C.G." already end in a full stop, so don't add
      // another one straight after it.
      field("cd-glory-sub").textContent =
        "The last Saturday in September, at the " +
        (decider.venue || "M.C.G.") + " — that is what we are playing for.";
    } else if (decider && decider.winner === state.club) {
      field("cd-glory-clock").textContent = "PREMIERS";
      field("cd-glory-sub").textContent = "Get the ute down Moorabool Street.";
    } else {
      field("cd-glory").hidden = true;
    }

    startClocks();
  }

  function renderNextFixture(state) {
    var host = field("next-fixture");
    host.textContent = "";
    var fixture = state.next_fixture;

    if (!fixture) {
      host.appendChild(el("p", "fixture-teams", "No fixture ahead."));
      host.appendChild(el("p", "fixture-where",
        "Either the season is done or the next game hasn't been scheduled."));
      return;
    }

    host.appendChild(el("div", "fixture-stage", fixture.stage || "Next match"));
    host.appendChild(el("div", "fixture-teams",
      fixture.club_is_home
        ? state.club + " v " + fixture.opponent
        : fixture.opponent + " v " + state.club));

    var where = el("p", "fixture-where");
    where.appendChild(document.createTextNode(
      (fixture.venue || "venue unknown") + " · " +
      (formatLocal(fixture.start_utc) || "time unknown") + " your time"));
    if (fixture.local_time) {
      where.appendChild(document.createElement("br"));
      where.appendChild(document.createTextNode(
        fixture.local_time.slice(11, 16) + " at the ground" +
        (fixture.timezone ? " (UTC" + fixture.timezone + ")" : "")));
    }
    if (typeof fixture.club_win_probability === "number") {
      where.appendChild(document.createElement("br"));
      where.appendChild(document.createTextNode(
        state.club + " " + percent(fixture.club_win_probability) +
        " to win, on the Squiggle consensus"));
    }
    host.appendChild(where);

    if (fixture.provisional_reasons && fixture.provisional_reasons.length) {
      var warning = el("div", "provisional");
      warning.appendChild(el("strong", null, "Not locked in yet. "));
      warning.appendChild(document.createTextNode(
        "The AFL only sets each finals week once the previous one is done, so " +
        "this is still a placeholder:"));
      var reasons = document.createElement("ul");
      fixture.provisional_reasons.forEach(function (reason) {
        reasons.appendChild(el("li", null, reason));
      });
      warning.appendChild(reasons);
      host.appendChild(warning);
    }

  }

  // ---- 5. path to glory -------------------------------------------------

  function renderPathToGlory(state) {
    var path = state.path_to_glory || {};
    var club = state.club;

    var note = $('[data-field="live-note"]');
    if (path.live_disclaimer) {
      note.textContent = "Football is on right now. These prices were set "
        + "before the bounce, so they don't know what's happening out there yet.";
      note.hidden = false;
    } else {
      note.hidden = true;
    }

    var playing = path.playing_now;
    var remaining = (state.headline.steps || []).length;
    field("path-sub").textContent = remaining
      ? plural(remaining, "win") + ". That is all that stands between us and " +
        "the last Saturday in September. It starts with " +
        (playing && playing.scenarios && playing.scenarios[0]
          ? playing.scenarios[0].opponent : "the next one") + "."
      : "Nothing left to play. What a ride.";

    renderFixtures(path.fixtures || [], club);

    // "If we win, who do we get?" -- the step after the one being played.
    var next = path.if_we_win;
    field("if-win-title").textContent = playing && playing.scenarios &&
      playing.scenarios[0]
        ? "If we beat " + playing.scenarios[0].opponent
        : "If we win";
    renderScenarios(field("if-win"), next, club,
      "Nothing after this — it's the last game.");
    if (next) {
      field("if-win-note").textContent =
        "Both are on the road, and we would take either of them.";
    }

    var last = path.final_step;
    renderScenarios(field("final-scenarios"),
      last && last.node === "GF" ? last : null, club,
      "Not applicable — this is the Grand Final.");
  }

  function renderFixtures(fixtures, club) {
    var list = field("fixtures");
    list.textContent = "";

    if (!fixtures.length) {
      var empty = document.createElement("li");
      empty.appendChild(gap("no fixtures left to play"));
      list.appendChild(empty);
      return;
    }

    fixtures.forEach(function (fixture) {
      var item = document.createElement("li");
      item.setAttribute("data-club", String(Boolean(fixture.involves_club)));

      var head = el("div", "fx-head");
      head.appendChild(el("span", null, fixture.stage));
      if (fixture.in_progress) {
        head.appendChild(el("span", "fx-live",
          fixture.time_string || "live"));
      } else if (fixture.start_utc) {
        head.appendChild(el("span", null, formatLocal(fixture.start_utc) || ""));
      }
      item.appendChild(head);

      var teams = el("div", "fx-teams");
      if (fixture.in_progress) {
        teams.appendChild(document.createTextNode(fixture.home + " "));
        teams.appendChild(el("b", "fx-score", fixture.home_score));
        teams.appendChild(document.createTextNode("  v  " + fixture.away + " "));
        teams.appendChild(el("b", "fx-score", fixture.away_score));
      } else {
        teams.textContent = fixture.home + " v " + fixture.away;
      }
      item.appendChild(teams);

      var venue = el("div", "fx-venue", fixture.venue || "venue to be confirmed");
      if (fixture.provisional_reasons && fixture.provisional_reasons.length) {
        venue.appendChild(document.createTextNode(" "));
        venue.appendChild(el("span", "tag tag-warn", "provisional"));
      }
      item.appendChild(venue);

      var bar = el("div", "split-bar");
      var home = el("i");
      home.style.width = (fixture.home_probability * 100).toFixed(1) + "%";
      var away = el("i");
      away.style.width = (fixture.away_probability * 100).toFixed(1) + "%";
      bar.appendChild(home);
      bar.appendChild(away);
      item.appendChild(bar);

      var odds = el("div", "fx-odds");
      odds.appendChild(document.createTextNode(
        fixture.home + " " + percent(fixture.home_probability) + " · " +
        fixture.away + " " + percent(fixture.away_probability)));
      if (typeof fixture.market_home_probability === "number") {
        odds.appendChild(document.createTextNode(
          "  ·  market " + percent(fixture.market_home_probability) +
          " " + fixture.home));
      }
      if (fixture.in_progress) {
        odds.appendChild(document.createTextNode(" "));
        odds.appendChild(el("span", "tag tag-warn", "pre-match"));
      }
      item.appendChild(odds);

      // What this game is worth to us. For our own game that's the whole
      // season; for one we're not in, it's the honest way to say whether it
      // matters at all.
      if (typeof fixture.club_if_home_wins === "number") {
        var impact = el("div", "fx-impact");
        if (fixture.involves_club) {
          impact.appendChild(document.createTextNode("This is the one. Win it "));
          impact.appendChild(el("b", null, "and we are into a preliminary final"));
          impact.appendChild(document.createTextNode(
            ", with everything still in front of us."));
        } else if (fixture.we_want) {
          // What a supporter actually wants to know: who are we barracking for?
          impact.appendChild(document.createTextNode("Get on "));
          impact.appendChild(el("b", null, fixture.we_want));
          impact.appendChild(document.createTextNode(
            ". Their win is the one that helps us — worth " +
            (fixture.club_swing * 100).toFixed(1) +
            " points to our chances."));
        } else {
          impact.appendChild(document.createTextNode(
            "Doesn't matter a jot to us. Put your feet up and enjoy it."));
        }
        item.appendChild(impact);
      }

      list.appendChild(item);
    });
  }

  function renderScenarios(list, step, club, emptyMessage) {
    list.textContent = "";
    if (!step || !step.scenarios || !step.scenarios.length) {
      var empty = document.createElement("li");
      empty.appendChild(gap(emptyMessage));
      list.appendChild(empty);
      return;
    }

    step.scenarios.forEach(function (scenario) {
      var item = document.createElement("li");
      item.appendChild(el("div", "sc-opp", scenario.opponent));
      item.appendChild(el("div", "sc-chance", percent(scenario.probability, 0)));

      var meta = el("div", "sc-meta");
      meta.appendChild(document.createTextNode(
        (scenario.venue || "venue unknown") + " · " +
        (scenario.neutral ? "neutral deck"
          : scenario.club_is_home ? "at home" : "on the road") + " · "));
      // Say it the way a supporter would: what we make of our chances.
      var ours = scenario.club_win_probability;
      meta.appendChild(document.createTextNode(
        ours >= 0.55 ? "and we'd start favourite, "
          : ours >= 0.45 ? "and it's a coin toss, "
          : "and we'd go in as underdogs at "));
      meta.appendChild(el("b", null, percent(ours)));
      if (ours < 0.45) {
        meta.appendChild(document.createTextNode(" — which suits us fine"));
      }
      item.appendChild(meta);

      list.appendChild(item);
    });
  }

  // ---- the bracket ------------------------------------------------------

  function renderBracket(state) {
    var list = field("bracket");
    list.textContent = "";
    var rows = state.bracket || [];
    if (!rows.length) { list.appendChild(gap("bracket not available")); return; }

    rows.forEach(function (row) {
      var item = document.createElement("li");
      item.setAttribute("data-club", String(Boolean(row.involves_club)));
      item.setAttribute("data-state", row.complete ? "done" : "pending");

      item.appendChild(el("div", "bracket-stage", row.stage));

      var teams = el("div", "bracket-teams");
      if (row.home && row.away) {
        teams.textContent = row.home + " v " + row.away;
      } else {
        teams.appendChild(el("span", "bracket-tbc", "To be decided"));
      }
      item.appendChild(teams);

      var meta = el("div", "bracket-meta");
      if (row.complete) {
        meta.appendChild(el("span", "bracket-score",
          row.home_score + "–" + row.away_score));
        meta.appendChild(document.createTextNode("  " + row.winner + " won · " + row.venue));
      } else if (row.home && row.away) {
        meta.appendChild(document.createTextNode(row.venue || "venue TBC"));
        if (row.provisional_reasons && row.provisional_reasons.length) {
          meta.appendChild(document.createTextNode(" "));
          meta.appendChild(el("span", "tag tag-warn", "provisional"));
        }
      } else if (typeof row.club_wins_away === "number") {
        meta.appendChild(document.createTextNode(
          row.club_wins_away === 0
            ? "This is ours to win"
            : plural(row.club_wins_away, "win") + " away"));
      } else if (typeof row.club_appearance_probability === "number") {
        meta.appendChild(document.createTextNode(
          "not on " + state.club + "'s side of the draw"));
      }
      item.appendChild(meta);
      list.appendChild(item);
    });
  }

  // ---- photographs ------------------------------------------------------

  /* Driven entirely by images/manifest.json so adding a photo is a file drop
     plus one entry, with no code change. Anything that fails -- a missing
     manifest, an unknown role, a filename typo -- degrades to no image rather
     than a broken layout or a broken-image icon. */

  function mountImage(container, spec, decorative, onFail) {
    if (!container || !spec || !spec.file) return null;

    var image = new Image();
    var src = "images/" + spec.file;
    var inlined = window.__NINE_LIVES_IMAGES;
    image.src = (inlined && inlined[src]) || src;
    image.alt = decorative ? "" : (spec.alt || "");
    if (decorative) image.setAttribute("aria-hidden", "true");
    image.loading = "lazy";
    image.decoding = "async";
    if (spec.focus) image.style.objectPosition = spec.focus;

    // A photo that 404s should leave no trace. The caller decides what "no
    // trace" means -- hiding a backdrop is enough, but a gallery item has a
    // caption and a box of its own that have to go with it.
    image.addEventListener("error", function () {
      if (image.parentNode) image.parentNode.removeChild(image);
      if (onFail) onFail();
      else container.hidden = true;
    });

    container.appendChild(image);
    return image;
  }

  function renderMedia(manifest) {
    var images = (manifest && Array.isArray(manifest.images)) ? manifest.images : [];
    if (!images.length) return;

    function byRole(role) {
      return images.filter(function (item) { return item.role === role; });
    }

    // The masthead backdrop. First hero wins; the rest are ignored.
    var hero = byRole("hero")[0];
    if (hero) mountImage(field("hero"), hero, false);

    // Photographs behind panels. Any section carrying data-panel="<name>" can
    // be targeted from the manifest, so a new backdrop needs no markup change.
    byRole("panel").forEach(function (spec) {
      var panel = document.querySelector('[data-panel="' + spec.target + '"]');
      if (!panel || panel.querySelector(".media-layer")) return;

      var layer = el("div", "media-layer");
      panel.insertBefore(layer, panel.firstChild);
      if (mountImage(layer, spec, true)) {
        panel.classList.add("has-media");
        // A wide, short photograph forced into a tall layer zooms into the
        // middle of it. Let the manifest say how deep the layer should be.
        if (spec.height) {
          panel.style.setProperty("--media-height", spec.height + "px");
        }
      } else {
        panel.removeChild(layer);
      }
    });

    // The crest. Artwork rather than a photograph, so it is never decorative
    // and never graded.
    var crest = byRole("crest")[0];
    if (crest) {
      var badge = field("crest");
      if (mountImage(badge, crest, false)) badge.hidden = false;
    }

    // A full-width band for photographs too wide to crop into a panel.
    var band = byRole("band")[0];
    if (band) {
      var figure = field("band");
      if (mountImage(figure, band, false)) {
        figure.hidden = false;
        if (band.caption || band.credit) {
          var bandCaption = document.createElement("figcaption");
          if (band.caption) bandCaption.appendChild(document.createTextNode(band.caption));
          if (band.credit) bandCaption.appendChild(el("span", "credit", band.credit));
          figure.appendChild(bandCaption);
        }
      }
    }

    // Inline headshots. A face is worth showing properly rather than washing
    // out behind a table of numbers.
    byRole("portrait").forEach(function (spec) {
      var panel = document.querySelector('[data-panel="' + spec.target + '"]');
      if (!panel || panel.querySelector(".panel-portrait")) return;
      var holder = el("div", "portrait-holder");
      if (!mountImage(holder, spec, false)) return;
      var image = holder.querySelector("img");
      image.className = "panel-portrait";
      var title = panel.querySelector(".panel-title");
      panel.insertBefore(image, title ? title.nextSibling : panel.firstChild);
    });

    renderRail(byRole("gallery"), "gallery", "gallery-panel");
    renderRail(byRole("history"), "history", "history-panel");
  }

  /** One scrolling rail of photographs, plus the section that wraps it. */
  function renderRail(specs, railName, panelName) {
    if (!specs.length) return;

    var rail = field(railName);
    var panel = field(panelName);
    if (!rail || !panel) return;
    rail.textContent = "";

    specs.forEach(function (spec) {
      var item = document.createElement("li");
      var figure = document.createElement("figure");

      // Take the whole item away if the photo never arrives, caption and all,
      // and fold the section away if that empties the rail.
      if (!mountImage(figure, spec, false, function () {
        if (item.parentNode) item.parentNode.removeChild(item);
        if (!rail.children.length) panel.hidden = true;
      })) return;

      if (spec.caption || spec.credit) {
        var caption = document.createElement("figcaption");
        if (spec.caption) caption.appendChild(document.createTextNode(spec.caption));
        if (spec.credit) caption.appendChild(el("span", "credit", spec.credit));
        figure.appendChild(caption);
      }
      item.appendChild(figure);
      rail.appendChild(item);
    });

    if (rail.children.length) panel.hidden = false;
  }

  // ---- 6. provenance and staleness -------------------------------------

  function renderFooter(state, status) {
    var generated = new Date(state.generated_at);
    var ageSeconds = (Date.now() - generated.getTime()) / 1000;

    field("updated").textContent =
      (formatLocal(state.generated_at) || "unknown") + " · " + describeAge(ageSeconds);

    field("season").textContent = state.season;
    field("model-count").textContent = (state.source && state.source.models_aggregated)
      ? state.source.models_aggregated : "a number of";

    var note = field("fetch-status");
    note.textContent = "";
    if (status) {
      var bits = [];
      if (status.last_attempt) {
        bits.push("Last fetch attempted " +
          describeAge((Date.now() - new Date(status.last_attempt).getTime()) / 1000) + ".");
      }
      if (status.consecutive_failures) {
        bits.push(plural(status.consecutive_failures, "consecutive fetch") +
          " failed. Last error: " + status.last_error);
      } else {
        bits.push("Source reachable.");
      }
      note.textContent = bits.join(" ");
    }

    renderStaleness(ageSeconds, status);
  }

  function renderStaleness(ageSeconds, status) {
    var banner = $("#staleness");
    var hours = ageSeconds / 3600;

    if (hours < STALE_WARN_HOURS && !(status && status.consecutive_failures)) {
      banner.hidden = true;
      return;
    }

    banner.hidden = false;
    banner.setAttribute("data-level", hours >= STALE_BAD_HOURS ? "bad" : "warn");
    var message = "Hang on — these numbers are " + describeAge(ageSeconds) +
      " old and haven't refreshed.";
    if (status && status.consecutive_failures) {
      message += " " + plural(status.consecutive_failures, "fetch") +
        " have failed since; the last good values are shown.";
    }
    banner.textContent = message;
  }

  // ---- boot -------------------------------------------------------------

  function fatal(message) {
    var banner = $("#staleness");
    banner.hidden = false;
    banner.setAttribute("data-level", "bad");
    banner.textContent = message;
  }

  // Photos are independent of the data, so a manifest problem must never stop
  // the numbers rendering, and vice versa.
  loadJSON("images/manifest.json")
    .then(renderMedia)
    .catch(function () { /* no photos configured; the page works without them */ });

  Promise.all([
    loadJSON("data/state.json"),
    loadJSON("data/history.json").catch(function () { return []; }),
    loadJSON("data/status.json").catch(function () { return null; })
  ]).then(function (results) {
    var state = results[0], history = results[1], status = results[2];
    renderCountdowns(state);
    renderHeadline(state, history);
    renderScottEra(state);
    renderNextFixture(state);
    renderNews(state);
    renderHeadToHead(state);
    renderPrecedent(state);
    renderGreatest(state);
    renderExperts(state);
    renderPathToGlory(state);
    renderBracket(state);
    renderFooter(state, status);
  }).catch(function (error) {
    fatal("Couldn't load the data files (" + error.message +
      "). The site is static, so this usually means the first fetch hasn't run yet.");
  });
})();
