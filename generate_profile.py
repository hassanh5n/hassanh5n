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

import datetime
import os
import time

import requests
from dateutil import relativedelta


HEADERS = {"authorization": "token " + os.environ.get("ACCESS_TOKEN", "")}
USER_NAME = os.environ.get("USER_NAME") or "hassanh5n"
BIRTHDAY = os.environ.get("BIRTHDAY") or "2004-02-19"
LOC_TIMEOUT_SECONDS = float(os.environ.get("LOC_TIMEOUT_SECONDS") or "15")
LOC_REPO_LIMIT = int(os.environ.get("LOC_REPO_LIMIT") or "8")

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
    if not os.environ.get("ACCESS_TOKEN"):
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
    q = """
    query($login: String!) {
      user(login: $login) {
        followers { totalCount }
        repositories(ownerAffiliations: [OWNER], isFork: false, first: 100) {
          totalCount
          nodes { stargazers { totalCount } }
        }
        contributionsCollection {
          contributionCalendar { totalContributions }
        }
      }
    }"""
    data = gql(q, {"login": USER_NAME})
    if not data or "errors" in data:
        return DEFAULT_STATS.copy()

    u = data["data"]["user"]
    stars = sum(r["stargazers"]["totalCount"] for r in u["repositories"]["nodes"])
    return {
        "repos": u["repositories"]["totalCount"],
        "stars": stars,
        "commits": u["contributionsCollection"]["contributionCalendar"][
            "totalContributions"
        ],
        "followers": u["followers"]["totalCount"],
    }


def get_repositories():
    q = """
    query($login: String!, $cursor: String) {
      user(login: $login) {
        repositories(ownerAffiliations: [OWNER], isFork: false, first: 100, after: $cursor) {
          edges { node { nameWithOwner } }
          pageInfo { endCursor hasNextPage }
        }
      }
    }"""

    repos, cursor = [], None
    while True:
        data = gql(q, {"login": USER_NAME, "cursor": cursor})
        if not data or "errors" in data:
            break
        info = data["data"]["user"]["repositories"]
        repos.extend(e["node"]["nameWithOwner"] for e in info["edges"])
        if not info["pageInfo"]["hasNextPage"]:
            break
        cursor = info["pageInfo"]["endCursor"]
    return repos


def get_contributor_stats(owner, name):
    """Return cached contributor stats without waiting for GitHub to compute them."""
    url = f"https://api.github.com/repos/{owner}/{name}/stats/contributors"

    try:
        r = requests.get(url, headers=HEADERS, timeout=6)
    except requests.RequestException:
        return None

    if r.status_code == 200:
        return r.json()
    return None


def get_loc():
    """Returns total, added, and deleted lines across owned repositories.

    GitHub's contributor-stats endpoint is eventually computed and can return 202
    for a long time. Keep this opportunistic so the profile build never hangs.
    """
    if not os.environ.get("ACCESS_TOKEN"):
        return "refreshing", "pending", "pending"

    repos = get_repositories()
    if not repos:
        return "refreshing", "pending", "pending"

    deadline = time.monotonic() + LOC_TIMEOUT_SECONDS
    added = deleted = 0
    processed = 0

    for repo in repos[:LOC_REPO_LIMIT]:
        if time.monotonic() >= deadline:
            print("LOC budget reached; finishing SVG without full LOC refresh.", flush=True)
            break

        owner, name = repo.split("/")
        print(f"LOC: checking {repo}", flush=True)
        contributors = get_contributor_stats(owner, name)
        if not contributors:
            continue

        processed += 1
        for contrib in contributors:
            author = contrib.get("author") or {}
            if author.get("login") != USER_NAME:
                continue
            for week in contrib.get("weeks", []):
                added += week.get("a", 0)
                deleted += week.get("d", 0)

    if processed == 0 or (added == 0 and deleted == 0):
        return "refreshing", "pending", "pending"

    total = added + deleted
    return (f"{total:,}", f"+{added:,}", f"-{deleted:,}")


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


def build_svg(dark, stats, loc_total, loc_add, loc_del, uptime):
    theme = {
        "card": "#161b22",
        "border": "#21262d",
        "fg": "#e6edf3",
        "muted": "#60758a",
        "label": "#ff8f40",
        "value": "#8cc8ff",
        "ascii": "#f0f6fc",
        "green": "#3fb950",
        "red": "#ff6b6b",
    }

    width = 1240
    height = 665
    right_x = 575
    right_edge = 1202

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

        value = f"{loc_total} ( {loc_add}, {loc_del} )"
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
    row("OS", "Windows 10, Android 14, Linux", y); y += info_lh
    row("Uptime", uptime, y); y += info_lh
    row("Host", "FAST NUCES Student", y); y += info_lh
    row("Kernel", "DevOps, Cloud, AI/ML, Systems", y); y += info_lh
    row("IDE", "VSCode, AntiGravity, Jupyter", y); y += info_lh * 1.35

    row("Languages.Programming", "Python, C/C++, C#, JavaScript", y); y += info_lh
    row("Languages.Systems", "Linux, Bash, Docker, CI/CD", y); y += info_lh
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

    dark_svg = build_svg(True, stats, loc_t, loc_a, loc_d, uptime)
    light_svg = build_svg(False, stats, loc_t, loc_a, loc_d, uptime)

    with open("dark_mode.svg", "w", encoding="utf-8") as f:
        f.write(dark_svg)
    with open("light_mode.svg", "w", encoding="utf-8") as f:
        f.write(light_svg)

    print("dark_mode.svg and light_mode.svg written.", flush=True)


if __name__ == "__main__":
    main()