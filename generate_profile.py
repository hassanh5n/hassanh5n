"""
GitHub Profile README Generator
Generates dark_mode.svg and light_mode.svg for hassanh5n's GitHub profile.

Required GitHub Actions secrets:
  ACCESS_TOKEN  - Fine-grained PAT with read:followers, repos, commits
  USER_NAME     - your GitHub username (hassanh5n)

Optional env vars:
  BIRTHDAY              - e.g. "2004-02-19" (YYYY-MM-DD)
  PROFILE_COMMIT_EMAIL  - used by the workflow when publishing generated SVGs
"""

import base64
import datetime
import hashlib
import io
import os
from pathlib import Path
from urllib.parse import quote

import requests
from dateutil import relativedelta
from PIL import Image, ImageOps


TOKEN = (os.environ.get("ACCESS_TOKEN") or "").strip()
HEADERS = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
USER_NAME = os.environ.get("USER_NAME") or "hassanh5n"
BIRTHDAY = os.environ.get("BIRTHDAY") or "2004-02-19"
ASSET_DIR = Path(__file__).resolve().parent / "assets"
ASCII_ART_IMAGE = ASSET_DIR / "ascii-art.png"

DEFAULT_STATS = {
    "repos": "25",
    "stars": "2",
    "commits": "202",
    "followers": "9",
}

PROJECTS = [
    (
        "FAST-Transport",
        "https://github.com/hassanh5n/FAST-Transport",
        "Transport management system for FAST NUCES",
    ),
    (
        "E-Stocks",
        "https://github.com/hassanh5n/E-Stocks",
        "Stock market simulation for investors",
    ),
    (
        "MultiThreaded-FD",
        "https://github.com/hassanh5n/MultiThreaded-File-Downloader",
        "Efficient multithreaded file downloader",
    ),
]

ASCII_ART = [
    "                ::::-:::=::-++--::::.::           ",
    "              :.::::::::+-=-:+--::.:-::.:         ",
    "              :.:..:::::=+::::-::::.:::::         ",
    "             :.:.::.:::::--*=:=:.::=:::::         ",
    "             ::.::::::::::::::::.:.::::::         ",
    "             :..:::::::=:::::::::::::*-:::        ",
    "             .:::-:===:=-:::##****=::-:..         ",
    "             :.:.:::-==+*%%%%%%%##*+--:.:         ",
    "           +*-:::-:-+#%#%%@@@%%%%#**+=::          ",
    "           #*%::+**#%#*%%@@@@@%%%##**+:           ",
    "           *%@=-:##=##%%#+#%%@%%%##**+ :          ",
    "           ##%=+##::*+**=::#%#***##*=:  :         ",
    "            *@=+*#%%%%%##%*-%%-#***-+=--:         ",
    "       :::::::=+*#%%@@@%%#@%%#+#####*             ",
    ":::::::::::::-=+*#%@*%%##*%@@%*%%%%#+             ",
    "::::::::::::-=:=*##%%%%%%%%*#**#%*=*-:            ",
    "::::::::::::=+*-+*#%##*%%%*%*+#*##*::::::.        ",
    ":::::::::::::+**-+*###%%#@%**+*##*:::::::::::     ",
    ":::.:::::::::*****-**#####*##***=:::::::::::::    ",
    ":::::::::::::=*****-=*##%%%#**+::::::::::::::::   ",
    "::::::::::::::******++:=+****:::::::::::::::::::  ",
    "::::::::::::::-*++****+++=+:::::::::::::::::::::: ",
]


def fmt_plural(n):
    return "s" if n != 1 else ""


def calc_uptime():
    bday = datetime.datetime.strptime(BIRTHDAY, "%Y-%m-%d")
    d = relativedelta.relativedelta(datetime.datetime.today(), bday)
    suffix = " birthday" if d.months == 0 and d.days == 0 else ""
    return (
        f"{d.years} year{fmt_plural(d.years)}, "
        f"{d.months} month{fmt_plural(d.months)}, "
        f"{d.days} day{fmt_plural(d.days)}{suffix}"
    )


def gql(query, variables=None):
    if not TOKEN:
        return None

    try:
        r = requests.post(
            "https://api.github.com/graphql",
            json={"query": query, "variables": variables or {}},
            headers=HEADERS,
            timeout=30,
        )
    except requests.RequestException:
        return None

    if r.status_code == 200:
        return r.json()
    return None


def get_user_stats():
    # Step 1: account metadata — creation year, repos, stars, followers
    meta_q = """
    query($login: String!) {
      user(login: $login) {
        createdAt
        followers { totalCount }
        repositories(ownerAffiliations: [OWNER], isFork: false, first: 100) {
          totalCount
          nodes { stargazers { totalCount } }
        }
      }
    }"""
    meta = gql(meta_q, {"login": USER_NAME})
    if not meta or "errors" in meta:
        return DEFAULT_STATS.copy()

    u            = meta["data"]["user"]
    stars        = sum(r["stargazers"]["totalCount"] for r in u["repositories"]["nodes"])
    created_year = int(u["createdAt"][:4])
    current_year = datetime.datetime.utcnow().year

    # Step 2: sum totalCommitContributions year-by-year since account creation.
    # contributionsCollection without a date range only covers the past 12 months,
    # so we must query each calendar year individually to get an all-time total.
    commits_q = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          totalCommitContributions
        }
      }
    }"""
    total_commits = 0
    for year in range(created_year, current_year + 1):
        data = gql(commits_q, {
            "login": USER_NAME,
            "from":  f"{year}-01-01T00:00:00Z",
            "to":    f"{year}-12-31T23:59:59Z",
        })
        if data and "errors" not in data:
            total_commits += (
                data["data"]["user"]["contributionsCollection"]["totalCommitContributions"]
            )

    return {
        "repos":     u["repositories"]["totalCount"],
        "stars":     stars,
        "commits":   total_commits,
        "followers": u["followers"]["totalCount"],
    }


# ── LOC via GraphQL commit pagination (Andrew6rant approach) ──────────────────
#
# The REST contributor stats endpoint (/repos/{r}/stats/contributors) returns
# 202 indefinitely from GitHub Actions because the cache is always cold on a
# fresh runner. Instead we use GraphQL to paginate every commit on the default
# branch and filter by the user's node ID — accurate, reliable, no polling.
#
# Results are cached in cache/loc_data.txt so only repos whose commit count
# changed since the last run are re-fetched, making daily runs fast.

LOC_CACHE_DIR  = Path(__file__).resolve().parent / "cache"
LOC_CACHE_FILE = LOC_CACHE_DIR / "loc_data.txt"


def _get_owner_id():
    """Return the GitHub node ID for USER_NAME, e.g. {'id': 'MDQ6VXNlcjU3...'}.
    Used to identify commits authored by the user across all repos."""
    q = "query($login:String!){user(login:$login){id}}"
    data = gql(q, {"login": USER_NAME})
    if data and "errors" not in data:
        return {"id": data["data"]["user"]["id"]}
    return None


def _loc_query(owner_id, cursor=None, edges=None):
    """
    Fetch all owned non-fork repos with their default-branch commit counts.
    Returns a list of edge dicts: {nameWithOwner, totalCommits}.
    Paginates automatically (60 repos per request to avoid 502s).
    """
    if edges is None:
        edges = []
    q = """
    query($login: String!, $cursor: String) {
      user(login: $login) {
        repositories(first: 60, after: $cursor,
                     ownerAffiliations: [OWNER], isFork: false) {
          edges {
            node {
              nameWithOwner
              defaultBranchRef {
                target {
                  ... on Commit { history { totalCount } }
                }
              }
            }
          }
          pageInfo { endCursor hasNextPage }
        }
      }
    }"""
    data = gql(q, {"login": USER_NAME, "cursor": cursor})
    if not data or "errors" in data:
        return edges

    page = data["data"]["user"]["repositories"]
    edges += page["edges"]
    if page["pageInfo"]["hasNextPage"]:
        return _loc_query(owner_id, page["pageInfo"]["endCursor"], edges)
    return edges


def _recursive_loc(owner, repo_name, owner_id,
                   add=0, delete=0, my_commits=0, cursor=None):
    """
    Paginate through commits on the default branch (100 at a time) and
    accumulate additions/deletions only for commits authored by owner_id.
    """
    q = """
    query($owner: String!, $repo: String!, $cursor: String) {
      repository(owner: $owner, name: $repo) {
        defaultBranchRef {
          target {
            ... on Commit {
              history(first: 100, after: $cursor) {
                edges {
                  node {
                    author { user { id } }
                    additions
                    deletions
                  }
                }
                pageInfo { endCursor hasNextPage }
              }
            }
          }
        }
      }
    }"""
    data = gql(q, {"owner": owner, "repo": repo_name, "cursor": cursor})
    if not data or "errors" in data:
        return add, delete, my_commits

    ref = (data["data"]["repository"] or {}).get("defaultBranchRef")
    if not ref:
        return add, delete, my_commits

    history = ref["target"]["history"]
    for edge in history["edges"]:
        node = edge["node"]
        author_user = (node.get("author") or {}).get("user")
        if author_user and author_user.get("id") == owner_id.get("id"):
            my_commits += 1
            add    += node["additions"]
            delete += node["deletions"]

    if history["pageInfo"]["hasNextPage"]:
        return _recursive_loc(owner, repo_name, owner_id,
                              add, delete, my_commits,
                              history["pageInfo"]["endCursor"])
    return add, delete, my_commits


def _load_cache():
    """
    Load loc_data.txt. Returns a dict keyed by repo_hash:
      {repo_hash: [total_commits, my_commits, additions, deletions]}
    """
    result = {}
    try:
        with open(LOC_CACHE_FILE, encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) == 5:
                    h, tc, mc, a, d = parts
                    result[h] = [int(tc), int(mc), int(a), int(d)]
    except FileNotFoundError:
        pass
    return result


def _save_cache(cache):
    LOC_CACHE_DIR.mkdir(exist_ok=True)
    with open(LOC_CACHE_FILE, "w", encoding="utf-8") as f:
        for h, (tc, mc, a, d) in cache.items():
            f.write(f"{h} {tc} {mc} {a} {d}\n")


def get_loc():
    """
    Returns (total_str, added_str, deleted_str) for all lines the user has
    committed across owned repos, using GraphQL commit pagination.

    On each run:
    - Repos whose default-branch commit count hasn't changed → served from cache.
    - Repos with new commits → re-fetched via _recursive_loc and cache updated.
    First run is slow (fetches every commit in every repo); subsequent daily
    runs only re-fetch repos that had new activity.
    """
    if not TOKEN:
        return "refreshing", "pending", "pending"

    owner_id = _get_owner_id()
    if not owner_id:
        return "refreshing", "pending", "pending"

    edges = _loc_query(owner_id)
    if not edges:
        return "refreshing", "pending", "pending"

    cache = _load_cache()
    updated = False

    for edge in edges:
        node        = edge["node"]
        name        = node["nameWithOwner"]
        repo_hash   = hashlib.sha256(name.encode()).hexdigest()
        ref         = node.get("defaultBranchRef")
        total_commits = (
            ref["target"]["history"]["totalCount"]
            if ref and ref.get("target") else 0
        )

        cached = cache.get(repo_hash)
        if cached and cached[0] == total_commits:
            # commit count unchanged — use cached values
            continue

        # new or updated repo — fetch fresh LOC
        owner, repo_name = name.split("/", 1)
        print(f"  LOC: fetching {name}…", flush=True)
        a, d, mc = _recursive_loc(owner, repo_name, owner_id)
        cache[repo_hash] = [total_commits, mc, a, d]
        updated = True

    if updated:
        _save_cache(cache)

    total_add = sum(v[2] for v in cache.values())
    total_del = sum(v[3] for v in cache.values())

    if total_add == 0 and total_del == 0:
        return "refreshing", "pending", "pending"

    total = total_add + total_del
    return f"{total:,}", f"+{total_add:,}", f"-{total_del:,}"


def escape(value):
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def trim(value, limit):
    value = str(value)
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


def ascii_image_data_uri(color):
    if not ASCII_ART_IMAGE.exists():
        return None

    with Image.open(ASCII_ART_IMAGE) as source:
        source = source.convert("RGBA")
        gray = ImageOps.grayscale(source)

        ink_mask = gray.point(lambda p: 255 if p < 245 else 0)
        bbox = ink_mask.getbbox()
        if bbox:
            gray = gray.crop(bbox)

        rgb = hex_to_rgb(color)
        alpha = gray.point(lambda p: max(0, min(255, int((255 - p) * 1.55))))
        rendered = Image.new("RGBA", gray.size, rgb + (0,))
        rendered.putalpha(alpha)

        out = io.BytesIO()
        rendered.save(out, format="PNG", optimize=True)

    encoded = base64.b64encode(out.getvalue()).decode("ascii")
    return {
        "href": f"data:image/png;base64,{encoded}",
        "width": rendered.width,
        "height": rendered.height,
    }


def build_svg(dark, stats, loc_total, loc_add, loc_del, uptime):
    if dark:
        theme = {
            "card":   "#161b22",
            "border": "#21262d",
            "fg":     "#e6edf3",
            "muted":  "#60758a",
            "label":  "#ff8f40",
            "value":  "#8cc8ff",
            "ascii":  "#f0f6fc",
            "green":  "#3fb950",
            "red":    "#ff6b6b",
        }
    else:
        theme = {
            "card":   "#ffffff",
            "border": "#d0d7de",
            "fg":     "#24292f",
            "muted":  "#57606a",
            "label":  "#953800",
            "value":  "#0550ae",
            "ascii":  "#24292f",
            "green":  "#1a7f37",
            "red":    "#cf222e",
        }

    width = 1500
    height = 760
    right_x = 720
    right_edge = 1458

    font = 'font-family="Cascadia Mono, Fira Code, JetBrains Mono, Consolas, monospace"'
    ascii_fs = 18.0
    ascii_lh = 24.0
    ascii_cw = 9.8
    info_fs = 20.0
    info_lh = 25.5
    info_cw = 10.8

    lines = [
        (
            f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" '
            f'rx="18" fill="{theme["card"]}" stroke="{theme["border"]}" stroke-width="1"/>'
        )
    ]

    def text_node(x, y, text, color, size=info_fs, weight=None, spacing=0):
        weight_attr = f' font-weight="{weight}"' if weight else ""
        lines.append(
            f'<text x="{x:.1f}" y="{y:.1f}" {font} font-size="{size}" '
            f'fill="{color}" xml:space="preserve" letter-spacing="{spacing}"{weight_attr}>'
            f'{escape(text)}</text>'
        )

    art_box_x = 40
    art_box_y = 36
    art_box_w = right_x - 76
    art_box_h = height - 72
    art_image = ascii_image_data_uri(theme["ascii"])

    if art_image:
        scale = min(art_box_w / art_image["width"], art_box_h / art_image["height"])
        art_w = art_image["width"] * scale
        art_h = art_image["height"] * scale
        art_x = art_box_x + (art_box_w - art_w) / 2
        art_y = art_box_y + (art_box_h - art_h) / 2
        lines.append(
            f'<image x="{art_x:.1f}" y="{art_y:.1f}" width="{art_w:.1f}" '
            f'height="{art_h:.1f}" href="{art_image["href"]}" '
            f'preserveAspectRatio="xMidYMid meet"/>'
        )
    else:
        art_width = max(len(row) for row in ASCII_ART) * ascii_cw
        art_height = (len(ASCII_ART) - 1) * ascii_lh
        art_x = max(38, right_x - 34 - art_width)
        art_y = (height - art_height) / 2 + ascii_fs / 2
        for i, row in enumerate(ASCII_ART):
            text_node(art_x, art_y + i * ascii_lh, row, theme["ascii"], ascii_fs)

    def trim_to(value, max_chars):
        return trim(value, max_chars)

    def row(label, value, y, value_color=None):
        value_color = value_color or theme["value"]
        label_text = f"{label}:"
        value = trim_to(value, 48)
        label_x = right_x + 24
        dot_x = right_x
        value_width = len(value) * info_cw
        value_x = right_edge - value_width
        min_value_x = label_x + len(label_text) * info_cw + 56

        if value_x < min_value_x:
            value = trim_to(value, max(14, int((right_edge - min_value_x) / info_cw)))
            value_width = len(value) * info_cw
            value_x = right_edge - value_width

        dots_start = label_x + len(label_text) * info_cw + 18
        dots_count = max(3, int((value_x - dots_start) / info_cw))

        text_node(dot_x, y, ".", theme["muted"])
        text_node(label_x, y, label_text, theme["label"], weight="700")
        text_node(dots_start, y, "." * dots_count, theme["muted"], spacing=2)
        text_node(value_x, y, value, value_color, weight="600")

    def section(title, y):
        x = right_x
        text = f"- {title} "
        dash_count = max(8, int((right_edge - x) / info_cw) - len(text) - 3)
        text_node(x, y, text + "-" * dash_count, theme["fg"], weight="700")

    def stat_pair(label_a, value_a, label_b, value_b, y):
        x = right_x
        mid = right_x + 320
        text_node(x, y, ".", theme["muted"])
        text_node(x + 24, y, f"{label_a}:", theme["label"], weight="700")
        text_node(x + 24 + (len(label_a) + 1) * info_cw + 12, y, str(value_a), theme["value"], weight="600")
        text_node(mid - 14, y, "|", theme["fg"], weight="700")
        text_node(mid + 8, y, f"{label_b}:", theme["label"], weight="700")
        text_node(mid + 8 + (len(label_b) + 1) * info_cw + 12, y, str(value_b), theme["value"], weight="600")

    def loc_row(y):
        label = "Lines of Code on GitHub:"
        text_node(right_x, y, ".", theme["muted"])
        text_node(right_x + 24, y, label, theme["label"], weight="700")

        if loc_total == "refreshing":
            value = "refreshing (pending, pending)"
            text_node(right_edge - len(value) * info_cw, y, value, theme["value"], weight="600")
            return

        value = f"{loc_total} ( {loc_add} , {loc_del} )"
        value_x = right_edge - len(value) * info_cw
        text_node(value_x, y, loc_total, theme["value"], weight="600")
        x = value_x + len(loc_total) * info_cw
        text_node(x, y, " ( ", theme["fg"])
        x += 3 * info_cw
        text_node(x, y, loc_add, theme["green"], weight="700")
        x += len(loc_add) * info_cw
        text_node(x, y, ", ", theme["fg"])
        x += 2 * info_cw
        text_node(x, y, loc_del, theme["red"], weight="700")
        x += len(loc_del) * info_cw
        text_node(x, y, " )", theme["fg"])

    y = 39
    header = "hassan@h5n"
    text_node(right_x, y, header, theme["fg"], weight="700")
    text_node(right_x + len(header) * info_cw + 20, y, "-" * 49, theme["fg"], weight="700")

    y += info_lh * 1.05
    row("OS", "Windows, Linux", y); y += info_lh
    row("Uptime", uptime, y); y += info_lh
    row("Host", "FAST NUCES Student", y); y += info_lh
    row("Kernel", "DevOps, Cloud, AI/ML, Systems", y); y += info_lh
    row("IDE", "VSCode, AntiGravity, Jupyter", y); y += info_lh * 1.35

    row("Languages.Programming", "Python, C/C++, C#, JavaScript", y); y += info_lh
    row("Languages.Systems", "Linux, Bash, Docker, CI/CD, AWS", y); y += info_lh
    row("Data.Bases", "MySQL, PostgreSQL, MongoDB", y); y += info_lh
    row("Frameworks", "Django, React, ASP.NET, Scikit-learn", y); y += info_lh
    row("Projects", ", ".join(p[0] for p in PROJECTS), y); y += info_lh
    row("Hobbies", "Building things, Breaking things", y); y += info_lh * 1.35

    section("Contact", y); y += info_lh
    row("GitHub", "github.com/hassanh5n", y); y += info_lh
    row("LinkedIn", "linkedin.com/in/shaikh-hassan-nafees-640998227", y); y += info_lh
    row("Email", "hassannafees.hn@email.com", y); y += info_lh * 1.35

    section("GitHub Stats", y); y += info_lh
    stat_pair("Repos", stats["repos"], "Stars", stats["stars"], y); y += info_lh
    stat_pair("Commits", stats["commits"], "Followers", stats["followers"], y); y += info_lh
    loc_row(y)

    inner = "\n  ".join(lines)
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        'xmlns="http://www.w3.org/2000/svg">\n'
        f'  {inner}\n'
        '</svg>\n'
    )


def main():
    print("Fetching stats...", flush=True)
    stats = get_user_stats()
    loc_t, loc_a, loc_d = get_loc()
    uptime = calc_uptime()

    print(f"Stats: {stats}", flush=True)
    print(f"LOC: {loc_t} ({loc_a}, {loc_d})", flush=True)
    print(f"Uptime: {uptime}", flush=True)

    dark_svg  = build_svg(True,  stats, loc_t, loc_a, loc_d, uptime)
    light_svg = build_svg(False, stats, loc_t, loc_a, loc_d, uptime)

    with open("dark_mode.svg",  "w", encoding="utf-8") as f:
        f.write(dark_svg)
    with open("light_mode.svg", "w", encoding="utf-8") as f:
        f.write(light_svg)

    print("dark_mode.svg and light_mode.svg written.", flush=True)


if __name__ == "__main__":
    main()