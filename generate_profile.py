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
    if dark:
        theme = {
            "bg": "#050505",
            "border": "#202020",
            "fg": "#f2f2f2",
            "muted": "#777777",
            "line": "#565656",
            "keyword": "#ffb86c",
            "name": "#8ab4f8",
            "key": "#c792ea",
            "string": "#f1dca7",
            "number": "#f78c6c",
            "punct": "#bbbbbb",
            "ascii": "#f6f6f6",
        }
    else:
        theme = {
            "bg": "#ffffff",
            "border": "#d9d9d9",
            "fg": "#151515",
            "muted": "#777777",
            "line": "#a0a0a0",
            "keyword": "#8a4b08",
            "name": "#005f87",
            "key": "#6f3fa0",
            "string": "#744f00",
            "number": "#9a3412",
            "punct": "#404040",
            "ascii": "#111111",
        }

    width = 960
    height = 540
    pad = 28
    gutter = 24
    half = (width - (pad * 2) - gutter) / 2
    left_x = pad
    right_x = pad + half + gutter
    right_w = width - right_x - pad

    font = 'font-family="Cascadia Mono, Fira Code, JetBrains Mono, Consolas, monospace"'
    ascii_fs = 12.5
    ascii_lh = 15.2
    ascii_cw = 7.15
    code_fs = 12.5
    code_lh = 15.8
    code_cw = 7.25
    max_code_chars = int((right_w - 34) / code_cw)

    lines = [
        f'<rect width="{width}" height="{height}" fill="{theme["bg"]}" rx="8"/>',
        (
            f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" '
            f'fill="none" stroke="{theme["border"]}" stroke-width="1" rx="8"/>'
        ),
    ]

    art_width = max(len(row) for row in ASCII_ART) * ascii_cw
    art_height = len(ASCII_ART) * ascii_lh
    art_x = left_x + max(0, (half - art_width) / 2)
    art_y = (height - art_height) / 2 + ascii_fs

    for i, row in enumerate(ASCII_ART):
        y = art_y + i * ascii_lh
        lines.append(
            f'<text x="{art_x:.1f}" y="{y:.1f}" {font} font-size="{ascii_fs}" '
            f'fill="{theme["ascii"]}" xml:space="preserve" letter-spacing="0">'
            f'{escape(row)}</text>'
        )

    line_no_x = right_x
    code_x = right_x + 34
    y = 42
    line_no = 1

    def add_code(parts):
        nonlocal y, line_no
        lines.append(
            f'<text x="{line_no_x:.1f}" y="{y:.1f}" {font} font-size="{code_fs}" '
            f'fill="{theme["line"]}">{line_no:02}</text>'
        )
        x = code_x
        for text, color, weight in parts:
            weight_attr = f' font-weight="{weight}"' if weight else ""
            lines.append(
                f'<text x="{x:.1f}" y="{y:.1f}" {font} font-size="{code_fs}" '
                f'fill="{color}"{weight_attr} xml:space="preserve">{escape(text)}</text>'
            )
            x += len(text) * code_cw
        y += code_lh
        line_no += 1

    def add_gap(size=0.45):
        nonlocal y
        y += code_lh * size

    def add_kv(key, value, comma=True):
        value_limit = max(14, max_code_chars - len(key) - 8)
        value = trim(value, value_limit)
        add_code(
            [
                ("  ", theme["fg"], None),
                (f"{key}", theme["key"], "600"),
                (": ", theme["punct"], None),
                ('"', theme["punct"], None),
                (value, theme["string"], None),
                ('"', theme["punct"], None),
                ("," if comma else "", theme["punct"], None),
            ]
        )

    def add_project(name, desc, comma=True):
        max_desc = max(16, max_code_chars - 30)
        add_code(
            [
                ("    // ", theme["muted"], None),
                (trim(name, 18), theme["name"], "600"),
                (" - ", theme["muted"], None),
                (trim(desc, max_desc), theme["muted"], None),
                ("," if comma else "", theme["punct"], None),
            ]
        )

    add_code(
        [
            ("const ", theme["keyword"], "600"),
            ("hassan", theme["name"], "700"),
            (" = {", theme["punct"], None),
        ]
    )
    add_gap()
    add_kv("os", "Linux | Windows")
    add_kv("uptime", uptime)
    add_kv("focus", "DevOps | Cloud | AI/ML | Systems")
    add_kv("ide", "VSCode | AntiGravity | Jupyter")
    add_gap()
    add_kv("code", "Python | C/C++ | C#")
    add_kv("cloud", "Docker | CI/CD | AWS | Linux")
    add_kv("data", "MySQL | PostgreSQL | MongoDB")
    add_kv("frameworks", "Django | React | ASP.NET | Scikit-learn")
    add_kv("hobbies", "Building things | Breaking things")
    add_gap()
    add_code([("  projects: [", theme["punct"], None)])
    for idx, (name, _url, desc) in enumerate(PROJECTS):
        add_project(name, desc, comma=idx < len(PROJECTS) - 1)
    add_code([("  ],", theme["punct"], None)])
    add_gap()
    add_kv("github", "github.com/hassanh5n")
    add_kv("linkedin", "linkedin.com/in/shaikh-hassan-nafees-640998227")
    add_kv("email", "hassannafees.hn@email.com")
    add_gap()
    add_code(
        [
            ("  stats: { ", theme["punct"], None),
            ("repos", theme["key"], "600"),
            (": ", theme["punct"], None),
            (str(stats["repos"]), theme["number"], "600"),
            (", ", theme["punct"], None),
            ("stars", theme["key"], "600"),
            (": ", theme["punct"], None),
            (str(stats["stars"]), theme["number"], "600"),
            (", ", theme["punct"], None),
            ("commits", theme["key"], "600"),
            (": ", theme["punct"], None),
            (str(stats["commits"]), theme["number"], "600"),
            (" },", theme["punct"], None),
        ]
    )
    add_code(
        [
            ("  followers: ", theme["punct"], None),
            (str(stats["followers"]), theme["number"], "600"),
            (",", theme["punct"], None),
        ]
    )
    add_code(
        [
            ("  loc: ", theme["punct"], None),
            ('"', theme["punct"], None),
            (trim(f"{loc_total} ({loc_add}, {loc_del})", max_code_chars - 10), theme["string"], None),
            ('"', theme["punct"], None),
        ]
    )
    add_code([("};", theme["punct"], None)])

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