"""Team news from the AFL's public RSS feed.

The one thing the original brief asked for that Squiggle cannot give us:
selection, injuries, and whatever else is being said about our campaign.

Two things govern the design.

First, this feed is far less reliable than Squiggle -- it is a public RSS
endpoint on a marketing site, it can change shape without notice, and it is the
most likely thing on this page to break. So it is isolated: a failure here must
degrade to "no news right now" and must never stop the football numbers
updating. The caller is expected to keep the last good items.

Second, everything in it is text written by somebody else. Headlines are
rendered as text, never as markup, and a link is only kept if it actually
points at afl.com.au -- a feed is not a place to accept arbitrary URLs from.
"""

import html
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

FEED_URL = "https://www.afl.com.au/rss"
ALLOWED_HOSTS = ("afl.com.au", "www.afl.com.au")
TIMEOUT_SECONDS = 20

# Words that mean somebody's availability is in question. Matching one of these
# tags an item as team news -- it does not claim the news is good or bad, which
# is not something a headline can be trusted to tell us.
SELECTION_WORDS = (
    "team news", "ins and outs", "selection", "selected", "omitted", "axed",
    "injury", "injured", "hamstring", "concussion", "corked", "soreness",
    "ruled out", "in doubt", "test", "scan", "surgery", "fitness",
    "return", "returns", "recalled", "available", "cleared", "comeback",
    "suspended", "suspension", "tribunal", "match review", "ban", "banned",
    "late change", "squad", "line-up", "lineup",
)

FINALS_WORDS = ("final", "finals", "semi", "prelim", "september", "flag",
                "premiership")

# Competitions this page is not about. An AFLW or VFL story mentioning
# Adelaide is not team news for our campaign.
OTHER_COMPETITIONS = ("aflw", "vflw", "vfl", "wafl", "sanfl", "under-18",
                      "draft combine")

_TAG = re.compile(r"<[^>]+>")


def _mentions(haystack, words):
    """Whole-word matching.

    Substring matching looks fine until "underdogs" counts as a Bulldogs story
    and "the Cats' rivals" is indistinguishable from anything containing the
    letters c-a-t-s. Nicknames are short and collide easily, so match on word
    boundaries or not at all.
    """
    return any(re.search(r"\b" + re.escape(word) + r"\b", haystack)
               for word in words)


def _clean(text):
    return html.unescape(_TAG.sub("", text or "")).strip()


def _safe_link(url):
    """Only links that genuinely point at afl.com.au."""
    try:
        parsed = urllib.parse.urlparse(url or "")
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        return None
    return urllib.parse.urlunparse(parsed._replace(scheme="https"))


def _published(item):
    raw = item.findtext("pubDate")
    if not raw:
        return None
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc)


def _nicknames(team):
    """Club nicknames, so "Cats" and "Dockers" match as well as the club name."""
    return {
        "Adelaide": ("adelaide", "crows"),
        "Brisbane Lions": ("brisbane", "lions"),
        "Carlton": ("carlton", "blues"),
        "Collingwood": ("collingwood", "magpies", "pies"),
        "Essendon": ("essendon", "bombers"),
        "Fremantle": ("fremantle", "dockers", "freo"),
        "Geelong": ("geelong", "cats"),
        "Gold Coast": ("gold coast", "suns"),
        "Greater Western Sydney": ("greater western sydney", "gws", "giants"),
        "Hawthorn": ("hawthorn", "hawks"),
        "Melbourne": ("melbourne", "demons", "dees"),
        "North Melbourne": ("north melbourne", "kangaroos", "roos"),
        "Port Adelaide": ("port adelaide", "power"),
        "Richmond": ("richmond", "tigers"),
        "St Kilda": ("st kilda", "saints"),
        "Sydney": ("sydney", "swans"),
        "West Coast": ("west coast", "eagles"),
        "Western Bulldogs": ("western bulldogs", "bulldogs", "dogs"),
    }.get(team, (team.lower(),))


class NewsUnavailable(RuntimeError):
    """The feed could not be read. Never fatal to the rest of the site."""


def fetch(user_agent, club, next_opponent, live_teams, limit=10):
    """Return items about our club, most relevant first.

    Geelong only. There is no club-specific feed to use -- the club site
    refuses us and afl.com.au ignores a ?club= parameter -- so this is the
    league-wide feed of the twenty latest stories, filtered down. That means
    the number of items varies with how much has been written about us lately,
    and some days it will be thin. Better thin and about us than padded out
    with other people's news.

    Raises on any network or parsing failure. The caller decides what to do
    about that -- which here means keeping the last good list and carrying on.
    """
    if os.environ.get("NINE_LIVES_NEWS_FAIL"):
        raise NewsUnavailable("NINE_LIVES_NEWS_FAIL is set (simulated outage)")

    request = urllib.request.Request(FEED_URL, headers={
        "User-Agent": user_agent,
        "Accept": "application/rss+xml, application/xml, text/xml",
    })
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        body = response.read()

    channel = ElementTree.fromstring(body).find("channel")
    if channel is None:
        raise ValueError("no <channel> in the AFL feed")

    now = datetime.now(timezone.utc)
    club_words = _nicknames(club)
    opponent_words = _nicknames(next_opponent) if next_opponent else ()
    others = {t: _nicknames(t) for t in live_teams if t not in (club, next_opponent)}

    items = []
    for entry in channel.findall("item"):
        title = _clean(entry.findtext("title"))
        if not title:
            continue
        summary = _clean(entry.findtext("description"))
        link = _safe_link(entry.findtext("link"))

        # The URL slug names the club even when the headline doesn't: the
        # story "Scott confident Holmes will benefit from the run" mentions
        # Geelong nowhere in its title or summary, but its link reads
        # /news/.../geelong-cats-coach-chris-scott-... Hyphens become spaces so
        # whole-word matching still works.
        slug = ""
        if link:
            slug = urllib.parse.urlparse(link).path.replace("-", " ").replace("/", " ")

        haystack = f"{title} {summary} {slug}".lower()

        # Another competition entirely.
        if any(word in haystack for word in OTHER_COMPETITIONS):
            continue

        # If it isn't about us, we aren't interested.
        if not _mentions(haystack, club_words):
            continue

        score, tags, about = 10, [], [club]

        # A story that also names who we are playing is worth more than one
        # that doesn't.
        if opponent_words and _mentions(haystack, opponent_words):
            score += 8
            about.append(next_opponent)
        for team, words in others.items():
            if _mentions(haystack, words):
                score += 2
                about.append(team)

        if _mentions(haystack, SELECTION_WORDS):
            score += 6
            tags.append("team news")
        if _mentions(haystack, FINALS_WORDS):
            score += 2
            tags.append("finals")

        published = _published(entry)
        if published:
            age_hours = (now - published).total_seconds() / 3600
            if age_hours < 24:
                score += 4
            elif age_hours < 72:
                score += 2

        items.append({
            "title": title,
            "link": link,
            "published_utc": published.isoformat().replace("+00:00", "Z")
                             if published else None,
            "about": sorted(set(about)),
            "tags": tags,
            "is_team_news": "team news" in tags,
            "score": score,
        })

    items.sort(key=lambda row: (-row["score"], row["published_utc"] or ""))
    return items[:limit]
