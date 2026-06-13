"""Steam feed: combined Atom from Steam's native news RSS endpoints.

Steam's News Hub exposes per-app and per-group RSS at
``store.steampowered.com/feeds/news/...`` (with ``?cc=PL&l=polish`` for the
Polish localization). This feed bundles the global Steam news feed plus a
hand-picked set of games and groups into one Atom stream with per-source
``<category>`` labels and cross-source dedup. The RSS channel titles are just
numeric IDs, so the human-readable labels below are resolved once (app names
via the store ``appdetails`` API, group names via the community
``memberslistxml``) and baked in.

The collection/browse pages the request also listed —
``/news/collection/featured/``, ``/news/collection/steam/``,
``/explore/new/``, and ``/soundtracks`` — are not separate RSS endpoints:
``collection/steam`` is the official-announcements view already covered by the
global news feed and the Steam News app (593110), while ``explore/new`` and
``soundtracks`` are store-browse pages with no news feed.
"""

import argparse
import sys

from multi_rss import run

FEED_NAME = "steam"

_BASE = "https://store.steampowered.com/feeds/news"
_Q = "?cc=PL&l=polish"


def _app(app_id):
    return f"{_BASE}/app/{app_id}/{_Q}"


def _group(group_id):
    return f"{_BASE}/group/{group_id}/{_Q}"


SOURCES = [
    ("Steam News", f"{_BASE}/{_Q}", 20),
    # Apps
    ("Aktualności Steam", _app("593110"), 20),
    ("Half-Life: Alyx", _app("546560"), 20),
    ("Baldur's Gate 3", _app("1086940"), 20),
    ("Half-Life 2", _app("220"), 20),
    ("Left 4 Dead 2", _app("550"), 20),
    ("eFootball", _app("1665460"), 20),
    ("S.T.A.L.K.E.R. 2: Heart of Chornobyl", _app("1643320"), 20),
    ("EA SPORTS FC 26", _app("3405690"), 20),
    ("Grand Theft Auto V Enhanced", _app("3240220"), 20),
    ("Gothic 1 Remake", _app("1297900"), 20),
    ("Football Manager 26", _app("3551340"), 20),
    ("Forza Horizon 5", _app("1551360"), 20),
    ("Euro Truck Simulator 2", _app("227300"), 20),
    ("Cyberpunk 2077", _app("1091500"), 20),
    # Groups
    ("Steam Promotions", _group("39049601"), 20),
    ("PC Gamer", _group("1850"), 20),
    ("Steamworks Development", _group("4145017"), 20),
    ("GRYOnline.pl", _group("6911258"), 20),
    ("Square Enix", _group("1012195"), 20),
]


def main(full=False):
    return run(
        feed_name=FEED_NAME,
        title="Steam",
        subtitle="Combined Steam news feed: the global Steam news feed plus "
                 "selected games and groups, from Steam's native news RSS.",
        blog_url="https://store.steampowered.com/news/",
        author="Steam",
        sources=SOURCES,
        language="pl",
        full=full,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the Steam Atom feed")
    parser.add_argument("--full", action="store_true", help="Ignore cache and rebuild from scratch")
    sys.exit(0 if main(full=parser.parse_args().full) else 1)
