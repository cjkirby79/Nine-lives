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

  function record(row) {
    if (!row || !row.played) return "0–0";
    return row.won + "–" + row.lost;
  }

  function plural(count, word) {
    return count + " " + word + (count === 1 ? "" : "s");
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
    // Pages caches aggressively; the whole point of the manual refresh button
    // is being able to watch the number move, so bypass it.
    return fetch(path + "?t=" + Date.now(), { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) throw new Error(path + " -> HTTP " + response.status);
        return response.json();
      });
  }

  // ---- 1. the headline --------------------------------------------------

  function renderHeadline(state, history) {
    var headline = state.headline || {};
    var target = headline.probability;
    var node = field("probability");

    if (typeof target !== "number") {
      node.textContent = "";
      node.appendChild(gap("no figure"));
      return;
    }

    countUp(node, target);

    var parts = [];
    var reach = percent(headline.reaches_grand_final);
    if (reach) parts.push(reach + " to reach the Grand Final");

    var contenders = state.field || [];
    for (var i = 0; i < contenders.length; i++) {
      if (contenders[i].team === state.club) {
        parts.push("ranked " + ordinal(i + 1) + " of " +
          contenders.length + " sides left");
        break;
      }
    }
    field("figure-note").textContent = parts.join(" · ");

    renderDelta(target, history);
    renderMethod(state);
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
  function renderDelta(current, history) {
    var node = field("delta");
    if (!Array.isArray(history) || history.length < 2) {
      node.textContent = "no earlier reading to compare against yet";
      return;
    }

    var now = Date.now();
    var wanted = now - 24 * 3600 * 1000;
    var baseline = null;
    for (var i = 0; i < history.length; i++) {
      var at = new Date(history[i].at).getTime();
      if (isNaN(at) || now - at < 3600 * 1000) continue;      // too recent to be a baseline
      if (!baseline || Math.abs(at - wanted) < Math.abs(baseline.time - wanted)) {
        baseline = { time: at, probability: history[i].probability };
      }
    }
    if (!baseline || typeof baseline.probability !== "number") {
      node.textContent = "no earlier reading to compare against yet";
      return;
    }

    var move = (current - baseline.probability) * 100;
    var since = describeAge((now - baseline.time) / 1000);
    if (Math.abs(move) < 0.05) {
      node.removeAttribute("data-dir");
      node.textContent = "unchanged since " + since.replace(" ago", "");
      return;
    }
    node.setAttribute("data-dir", move > 0 ? "up" : "down");
    // "points" would read as a score in an AFL context, so be explicit.
    node.textContent = (move > 0 ? "▲ " : "▼ ") + Math.abs(move).toFixed(1) +
      " percentage points since " + since.replace(" ago", "");
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
      ? product.join("  ×  ") + "  =  " + percent(state.headline.probability)
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
      era.from_year + "–" + era.to_year + " · every final Geelong have played under him, " +
      "counted from match records";

    var overall = era.overall || {};
    var semis = (era.by_stage || []).filter(function (s) { return s.stage === "Semi-final"; })[0];

    var stats = [
      { value: record(overall), label: "Finals record", tone: "" },
      { value: semis ? record(semis) : null, label: "In semi-finals", tone: "stat-strong" },
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

    fillRecordList(field("scott-stages"), era.by_stage, function (row) {
      return { label: row.stage, value: record(row), note: null };
    });

    fillRecordList(field("scott-opponents"), era.against_live_teams, function (row) {
      return {
        label: row.team,
        value: row.played ? record(row) : "—",
        note: row.played ? null : "never met in finals"
      };
    });

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
      item.appendChild(el("span", "record-value", mapped.value));
      list.appendChild(item);
    });
  }

  // ---- 3. next fixture --------------------------------------------------

  var countdownTimer = null;

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

    var countdown = el("div", "countdown");
    ["days", "hours", "mins", "secs"].forEach(function (unit) {
      var cell = document.createElement("div");
      cell.appendChild(el("b", null, "—")).setAttribute("data-unit", unit);
      cell.appendChild(el("span", null, unit));
      countdown.appendChild(cell);
    });
    host.appendChild(countdown);

    if (fixture.provisional_reasons && fixture.provisional_reasons.length) {
      var warning = el("div", "provisional");
      warning.appendChild(el("strong", null, "Fixture not confirmed. "));
      warning.appendChild(document.createTextNode(
        "The AFL sets each finals week only after the previous one finishes, so " +
        "Squiggle is still carrying a placeholder:"));
      var reasons = document.createElement("ul");
      fixture.provisional_reasons.forEach(function (reason) {
        reasons.appendChild(el("li", null, reason));
      });
      warning.appendChild(reasons);
      host.appendChild(warning);
    }

    startCountdown(countdown, fixture.start_utc);
  }

  function startCountdown(root, startUtc) {
    var kickoff = new Date(startUtc).getTime();
    if (countdownTimer) clearInterval(countdownTimer);
    if (isNaN(kickoff)) return;

    function tick() {
      var remaining = Math.floor((kickoff - Date.now()) / 1000);
      if (remaining <= 0) {
        clearInterval(countdownTimer);
        root.textContent = "";
        root.appendChild(el("div", null, "Under way — or done.")).style.flex = "1";
        return;
      }
      var units = {
        days: Math.floor(remaining / 86400),
        hours: Math.floor(remaining / 3600) % 24,
        mins: Math.floor(remaining / 60) % 60,
        secs: remaining % 60
      };
      Object.keys(units).forEach(function (unit) {
        var cell = root.querySelector('[data-unit="' + unit + '"]');
        if (cell) cell.textContent = units[unit] < 10 ? "0" + units[unit] : units[unit];
      });
    }
    tick();
    countdownTimer = setInterval(tick, 1000);
  }

  // ---- 4. market against models ----------------------------------------

  function renderMarket(state) {
    var host = field("market");
    host.textContent = "";

    var fixture = state.next_fixture;
    var market = state.market;
    var models = fixture && fixture.club_win_probability;

    if (!fixture || typeof models !== "number") {
      host.appendChild(gap("no priced fixture to compare"));
      return;
    }

    var wrap = el("div", "versus");
    wrap.appendChild(bar("The models", models, "bar-models",
      "Squiggle consensus of its public models"));

    if (market && typeof market.club_win_probability === "number") {
      wrap.appendChild(bar("The market", market.club_win_probability, "bar-market",
        "Squiggle's Punters source, derived from bookmaker pricing"));
    } else {
      var missing = el("div", "versus-row");
      missing.appendChild(gap("market pricing not published for this fixture"));
      wrap.appendChild(missing);
    }
    host.appendChild(wrap);

    if (market && typeof market.club_win_probability === "number") {
      var difference = (market.club_win_probability - models) * 100;
      var line = el("p", "versus-gap");
      if (Math.abs(difference) < 0.5) {
        line.textContent = "The public and the models agree on " + state.club +
          " v " + fixture.opponent + ".";
      } else {
        line.textContent = "The public rate " + state.club + " " +
          Math.abs(difference).toFixed(1) + " percentage points " +
          (difference > 0 ? "higher" : "lower") + " than the models do.";
      }
      host.appendChild(line);
    }
  }

  function bar(label, value, className, note) {
    var row = el("div", "versus-row");
    var head = el("div", "versus-head");
    head.appendChild(el("span", null, label));
    head.appendChild(el("span", "versus-value", percent(value)));
    row.appendChild(head);
    var track = el("div", "bar " + className);
    var fill = document.createElement("i");
    fill.style.width = Math.max(0, Math.min(100, value * 100)) + "%";
    track.appendChild(fill);
    row.appendChild(track);
    row.appendChild(el("div", "record-note", note));
    return row;
  }

  // ---- 5. path to glory -------------------------------------------------

  function renderPathToGlory(state) {
    var path = state.path_to_glory || {};
    var club = state.club;

    var note = $('[data-field="live-note"]');
    if (path.live_disclaimer) {
      note.textContent = path.live_disclaimer;
      note.hidden = false;
    } else {
      note.hidden = true;
    }

    var playing = path.playing_now;
    var remaining = (state.headline.steps || []).length;
    field("path-sub").textContent = remaining
      ? plural(remaining, "win") + " from the premiership, starting with " +
        (playing && playing.scenarios && playing.scenarios[0]
          ? playing.scenarios[0].opponent : "the next one") + "."
      : "Nothing left to play.";

    renderFixtures(path.fixtures || [], club);

    // "If we win, who do we get?" -- the step after the one being played.
    var next = path.if_we_win;
    field("if-win-title").textContent = playing && playing.scenarios &&
      playing.scenarios[0]
        ? "If we beat " + playing.scenarios[0].opponent
        : "If we win";
    renderScenarios(field("if-win"), next, club,
      "Nothing after this — it's the last game.");

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
          var ifWeWin = fixture.home === club
            ? fixture.club_if_home_wins : fixture.club_if_away_wins;
          impact.appendChild(document.createTextNode("Win and we're "));
          impact.appendChild(el("b", null, percent(ifWeWin)));
          impact.appendChild(document.createTextNode(
            " for the flag. Lose and the season is over."));
        } else {
          impact.appendChild(document.createTextNode(
            fixture.home + " win → " + club + " " +
            percent(fixture.club_if_home_wins) + "  ·  " +
            fixture.away + " win → " + percent(fixture.club_if_away_wins) + "  "));
          var swing = fixture.club_swing * 100;
          // "0.0pp swing" reads like a broken number rather than a small one.
          impact.appendChild(el("b", null,
            swing < 0.1 ? "barely moves us" : swing.toFixed(1) + "pp swing"));
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
        (scenario.neutral ? "neutral"
          : scenario.club_is_home ? "home" : "away") + " · we'd be "));
      meta.appendChild(el("b", null, percent(scenario.club_win_probability)));
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
      } else if (typeof row.club_appearance_probability === "number") {
        meta.appendChild(document.createTextNode(
          row.club_appearance_probability < 1e-9
            ? "not on " + state.club + "'s side of the draw"
            : state.club + " reach this " +
              percent(row.club_appearance_probability) + " of the time"));
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
    image.src = "images/" + spec.file;
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
    var message = "Stale data — these numbers were last refreshed " +
      describeAge(ageSeconds) + ".";
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
    renderHeadline(state, history);
    renderScottEra(state);
    renderNextFixture(state);
    renderMarket(state);
    renderPathToGlory(state);
    renderBracket(state);
    renderFooter(state, status);
  }).catch(function (error) {
    fatal("Couldn't load the data files (" + error.message +
      "). The site is static, so this usually means the first fetch hasn't run yet.");
  });
})();
