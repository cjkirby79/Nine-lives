# Nine Lives

Geelong's chances of winning the 2026 AFL Grand Final, refreshed every half hour.

**Live site:** https://cjkirby79.github.io/Nine-lives/

This is phase one: a working pipeline showing a small amount of real data, not the
full feature set. What's deliberately left out is listed at the bottom.

---

## How it works

A browser can't call the Squiggle API directly — CORS blocks it, and a page that
depends on a live third-party request breaks the moment that request fails. So:

```
GitHub Actions (every 30 min)
        │
        ▼
  fetch/fetch.py ──► api.squiggle.com.au
        │
        ▼
   data/*.json  ──► committed to the repo
        │
        ▼
  GitHub Pages redeploys ──► index.html reads the local JSON
```

Nothing on the page is hand-entered. Every figure traces back to a Squiggle
response, and every figure carries the timestamp of the fetch that produced it.

### Failure behaviour

A failed fetch never blanks the page. `data/state.json` is only ever rewritten on
success; a failure updates `data/status.json` alone. The page then shows the last
good numbers with a banner stating how old they are — amber past two hours, red
past six.

To see this for yourself:

```bash
NINE_LIVES_FORCE_FAIL=1 python3 fetch/fetch.py   # simulate Squiggle going down
python3 -m http.server 8000                      # the page still renders, marked stale
```

---

## Where the headline number comes from

**Squiggle publishes no premiership probability.** It publishes per-game win
probabilities. So the headline is *derived*, and the page says so and shows its
working. Three parts:

1. **Fixtures Squiggle has already tipped** use its published Aggregate consensus
   verbatim. These legs are tagged `published`.

2. **Legs whose opponent isn't known yet** — the preliminary final and the Grand
   Final — use a conversion fitted to Squiggle's own published output this season:

   ```
   predicted margin  =  a·(power rating difference) + b·(home ground) + c·(away side travelling interstate)
   win probability   =  logistic(k · predicted margin)
   ```

   Both fits are ordinary least squares against Squiggle's own numbers, refitted
   on every run. Nothing is assumed about the scale of Squiggle's power ratings,
   because it isn't published and can't be guessed — as of writing, Geelong rate
   62.0 and Fremantle 61.8, yet Squiggle tips Fremantle by 11.4 points. These legs
   are tagged `fitted` and the fit's own error is shown next to them.

3. **The bracket is enumerated exhaustively** — every remaining combination of
   results, roughly 128 leaves — and the paths ending in a premiership are summed.
   This is exact arithmetic over the fixture tree, not a Monte Carlo simulation,
   so there's no sampling error to explain away. As a check, the probabilities
   across all remaining sides sum to exactly 1.

The Grand Final is priced as a neutral ground, which slightly understates a
Victorian side's advantage at the MCG. That's a deliberate choice: the size of
that advantage isn't something Squiggle publishes, so inventing a number for it
would break the rule this project runs on.

Run `python3 fetch/test_model.py` to check the maths. It asserts, among other
things, that the field sums to 1, that the three legs multiply back to the
headline exactly, and that a side which has already won everything sits at 100%.

---

## Setup — what you need to do, in order

You only do this once. Steps 2 and 3 must happen **before** step 4, or the first
run will fail when it tries to push.

### 1. Get the code onto `main`

The work is on the branch `claude/nine-lives-geelong-tracker-b4278r`. Open a pull
request from it and merge it into `main`. This matters beyond tidiness: **GitHub
only runs scheduled workflows from the repository's default branch**, so the cron
will not fire until this code is on `main`.

### 2. Let the workflow write to the repo

The job commits the JSON it fetches, so it needs write access.

1. Go to your repository on github.com
2. Click **Settings** (top row of tabs, far right)
3. In the left sidebar, click **Actions**, then **General**
4. Scroll to **Workflow permissions**
5. Select **Read and write permissions**
6. Click **Save**

### 3. Turn on GitHub Pages

1. Still in **Settings**, click **Pages** in the left sidebar
2. Under **Build and deployment** → **Source**, choose **Deploy from a branch**
3. Under **Branch**, choose **main** and folder **/ (root)**
4. Click **Save**

Give it a minute or two. The URL appears at the top of that same page.

### 4. Run it once by hand

1. Click the **Actions** tab (top row of tabs)
2. If you see a banner asking you to enable workflows, click the green button to
   confirm
3. In the left sidebar, click **Nine Lives fetch**
4. On the right, click the **Run workflow** dropdown, then the green
   **Run workflow** button
5. Wait about a minute, then refresh. A green tick means it worked

Open the Pages URL. You should see a number.

### 5. Confirm the schedule works on its own

Leave it alone for an hour and check the **Actions** tab again. You should see
runs you didn't trigger.

**The schedule is not punctual.** GitHub queues scheduled jobs at low priority and
under load they run late — sometimes very late. Nothing on the site assumes
otherwise: the page shows the true age of its data, not the schedule it was
supposed to keep.

---

## Forcing a refresh from your phone

Open the repo in a browser → **Actions** → **Nine Lives fetch** → **Run workflow**
→ **Run workflow**. Wait a minute, then reload the site. The page fetches its JSON
with cache-busting, so you'll see the new value straight away rather than a cached
one.

---

## Things that will bite you eventually

- **GitHub disables scheduled workflows after 60 days without repository
  activity.** You'll get an email. Re-enable it from the Actions tab. Any commit
  resets the clock, and this workflow's own commits count.
- **The finals fixture is announced late.** The AFL only sets each week's venues
  and times once the previous week finishes, so Squiggle carries a placeholder
  until then. The page detects this and marks the fixture *provisional* rather
  than presenting a guess as fact. It clears itself when the real fixture lands.
- **Squiggle blocks badly-behaved bots.** Every request identifies itself and
  carries a contact address, requests are spaced out, and completed past seasons
  are cached in `data/cache/` and never refetched. Don't shorten the schedule
  much below 30 minutes.

---

## Adding photos

Photos are driven by `images/manifest.json`. To add one: drop the file into
`images/`, then add an entry.

```json
{
  "file": "your-photo.jpg",
  "role": "gallery",
  "alt": "What is happening in the picture",
  "caption": "Shown under the photo",
  "credit": "Photographer or agency",
  "focus": "50% 30%"
}
```

**`role`** decides where it goes:

| role | where it lands |
|---|---|
| `crest` | the club badge in the masthead |
| `hero` | behind the masthead. First one wins, the rest are ignored |
| `band` | full width, keeping its own proportions |
| `panel` | behind a panel — set `target` to one of the names below |
| `gallery` | the "The campaign" rail at the foot — this season |
| `history` | the "Silverware" rail under the Chris Scott panel — past flags |

Use `band` for anything too panoramic to crop into a panel — a team photo
cropped to a phone-height masthead is four torsos. The band keeps the image's
own aspect ratio and shows all of it.

`crest` is for flat artwork and is deliberately exempt from the grading every
photograph gets, so it stays crisp. The supplied crest PNG has no transparency
and its own white is load-bearing — the cat and the lettering are white — so
it can't be keyed out onto navy. It sits on a white badge instead, which is how
a crest appears on a broadcast graphic anyway. A transparent PNG or an SVG
would drop straight in over it.

Any section on the page can take a photograph behind it. The `target` names are
`headline`, `scott`, `next`, `market` and `bracket`. The same file can appear
more than once — a photo can be a panel backdrop and sit in the gallery too.

A word on which panels to use: the fade behind a panel is measured in pixels,
not percentages, so a photo reads across roughly the first 300px and everything
below sits on solid navy however tall the panel grows. That works well for
`scott` and `next`. Panels that are mostly small numbers — `bracket` especially
— read better left clean, and the headline number is best on a plain ground.

**`focus`** is a CSS `object-position`. Use it when a crop cuts someone's head
off: `"50% 20%"` pulls the crop upwards, `"20% 50%"` shifts the subject right.
Nothing in the CSS needs touching.

Every photo gets the same grade — pulled towards navy, slightly desaturated —
so a press shot, a phone snap and a screenshot all still look like one site.
You don't need to edit anything before dropping it in.

Nothing here can break the page. An unknown role is ignored, a filename typo is
dropped silently, and if the manifest is missing entirely the site renders
exactly as it did before there were any photos.

There are two rails, kept apart on purpose: `gallery` is this year's campaign,
`history` is the premierships. Order matters in both — they render left to
right, so put the best one first. The same file can appear more than once under
different roles.

One sizing note, learned the hard way. A photograph behind a panel is bounded
to the depth of the fade rather than stretched to the panel, because
`object-fit: cover` scales to whichever side is larger: a 738×414 photo behind
the Chris Scott panel, which runs about 1700px tall, was being magnified four
times over and turned into a smear. Bounded, it crops sideways instead and the
subject survives. You don't have to do anything about this — it's just why tall
panels don't ruin wide photos.

Two practical notes. Keep files under a few hundred KB — they're committed to
the repo and served on phones, and there's no image pipeline. And the photos
currently in there look like agency press images; on a public site that's worth
a thought, and the `credit` field is there if you want to attribute them.

---

## Running it locally

```bash
python3 fetch/test_model.py     # check the maths (no dependencies)
python3 fetch/fetch.py          # pull from Squiggle, write data/
python3 -m http.server 8000     # then open http://localhost:8000
```

Python 3.9+, standard library only. There is no build step and no package
install, for the site or the fetch script.

| Path | What it does |
|---|---|
| `fetch/squiggle.py` | Squiggle client: UserAgent, throttling, retries, disk cache |
| `fetch/model.py` | Calibration fits and the bracket enumeration |
| `fetch/fetch.py` | Pulls everything, writes `data/` |
| `fetch/test_model.py` | Tests for the maths |
| `data/state.json` | Everything the page renders. Only written on success |
| `data/history.json` | The headline number over time, so the page can show movement |
| `data/status.json` | Fetch health. Always written, success or failure |
| `index.html` `styles.css` `app.js` | The site |
| `images/manifest.json` | Which photos appear and where. See above |

Useful environment variables: `NINE_LIVES_FORCE_FAIL=1` simulates an outage,
`NINE_LIVES_SEASON` overrides the season (otherwise it's the current year — not
hardcoded), `NINE_LIVES_CLUB` overrides the club.

---

## Not in phase one

Deferred on purpose. All of these are cheap off the same Squiggle data:
bogey teams, ten-week form for every club, head-to-head against each side still
alive, and the full twenty-year record (Squiggle's archive reaches back to 2000).

Two are genuinely harder and need a decision first:

- **Player selection and injury news.** There is no free structured feed for this.
  It needs AFL.com.au's RSS or scraping a club site, and neither gives clean data.
  This is the hardest thing in the original brief.
- **The 1989 Grand Final.** It predates Squiggle's archive, so it can't be fetched
  — it would have to be written by hand and clearly marked as editorial rather
  than sourced.

---

Data from the [Squiggle API](https://api.squiggle.com.au/), which is free, needs
no key, and deserves the courtesy it asks for. Not affiliated with the Geelong
Football Club or the AFL. Market pricing is shown for context only.
