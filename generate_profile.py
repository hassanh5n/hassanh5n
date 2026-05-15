"""
GitHub Profile README Generator
Generates dark_mode.svg and light_mode.svg for hassanh5n's GitHub profile.

Required GitHub Actions secrets:
  ACCESS_TOKEN  - Fine-grained PAT with read:followers, repos, commits
  USER_NAME     - your GitHub username (hassanh5n)

Optional env vars (for customization):
  BIRTHDAY      - e.g. "2002-01-15"  (YYYY-MM-DD)
"""

import datetime
import os
import requests
from dateutil import relativedelta

# ── Config ────────────────────────────────────────────────────────────────────
HEADERS     = {'authorization': 'token ' + os.environ.get('ACCESS_TOKEN', '')}
USER_NAME   = os.environ.get('USER_NAME', 'hassanh5n')
BIRTHDAY    = os.environ.get('BIRTHDAY', '2004-02-19') 

PROJECTS = [
    ("FAST-Transport",  "https://github.com/hassanh5n/FAST-Transport",          "A Transport Management System for FAST NUCES"),
    ("E-Stocks",  "https://github.com/hassanh5n/E-Stocks",          "Stock Market Simulation for Investors"),
    ("MultiThreaded-FD",     "https://github.com/hassanh5n/MultiThreaded-File-Downloader",             "Download a File from Internet, Efficiently"),
]

# ── ASCII art (pre-rendered from photo) ───────────────────────────────────────
ASCII_ART = [
    '                ::::-:::=::-++--::::.::           ',
    '              :.::::::::+-=-:+--::.:-::.:         ',
    '              :.:..:::::=+::::-::::.:::::         ',
    '             :.:.::.:::::--*=:=:.::=:::::         ',
    '             ::.::::::::::::::::.:.::::::         ',
    '             :..:::::::=:::::::::::::*-:::        ',
    '             .:::-:===:=-:::##****=::-:..         ',
    '             :.:.:::-==+*%%%%%%%##*+--:.:         ',
    '           +*-:::-:-+#%#%%@@@%%%%#**+=::          ',
    '           #*%::+**#%#*%%@@@@@%%%##**+:           ',
    '           *%@=-:##=##%%#+#%%@%%%##**+ :          ',
    '           ##%=+##::*+**=::#%#***##*=:  :         ',
    '            *@=+*#%%%%%##%*-%%-#***-+=--:         ',
    '       :::::::=+*#%%@@@%%#@%%#+#####*             ',
    ':::::::::::::-=+*#%@*%%##*%@@%*%%%%#+             ',
    '::::::::::::-=:=*##%%%%%%%%*#**#%*=*-:            ',
    '::::::::::::=+*-+*#%##*%%%*%*+#*##*::::::.        ',
    ':::::::::::::+**-+*###%%#@%**+*##*:::::::::::     ',
    ':::.:::::::::*****-**#####*##***=:::::::::::::    ',
    ':::::::::::::=*****-=*##%%%#**+::::::::::::::::   ',
    '::::::::::::::******++:=+****:::::::::::::::::::  ',
    '::::::::::::::-*++****+++=+:::::::::::::::::::::: ',
]

# ── Helpers ───────────────────────────────────────────────────────────────────
def fmt_plural(n):
    return 's' if n != 1 else ''

def calc_uptime():
    bday = datetime.datetime.strptime(BIRTHDAY, "%Y-%m-%d")
    d = relativedelta.relativedelta(datetime.datetime.today(), bday)
    suffix = ' 🎂' if d.months == 0 and d.days == 0 else ''
    return (f"{d.years} year{fmt_plural(d.years)}, "
            f"{d.months} month{fmt_plural(d.months)}, "
            f"{d.days} day{fmt_plural(d.days)}{suffix}")

def gql(query, variables=None):
    if not os.environ.get('ACCESS_TOKEN'):
        return None
    r = requests.post(
        'https://api.github.com/graphql',
        json={'query': query, 'variables': variables or {}},
        headers=HEADERS,
        timeout=30,
    )
    if r.status_code == 200:
        return r.json()
    return None

def get_user_stats():
    q = '''
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
    }'''
    data = gql(q, {'login': USER_NAME})
    if not data:
        return {'repos': '??', 'stars': '??', 'commits': '??', 'followers': '??'}
    u = data['data']['user']
    stars = sum(r['stargazers']['totalCount'] for r in u['repositories']['nodes'])
    return {
        'repos':     u['repositories']['totalCount'],
        'stars':     stars,
        'commits':   u['contributionsCollection']['contributionCalendar']['totalContributions'],
        'followers': u['followers']['totalCount'],
    }

def get_loc():
    """Returns (added, deleted) lines of code across all repos."""
    q = '''
    query($login: String!, $cursor: String) {
      user(login: $login) {
        repositories(ownerAffiliations: [OWNER], isFork: false, first: 100, after: $cursor) {
          edges { node { nameWithOwner } }
          pageInfo { endCursor hasNextPage }
        }
      }
    }'''
    if not os.environ.get('ACCESS_TOKEN'):
        return '??', '??', '??'

    repos, cursor = [], None
    while True:
        data = gql(q, {'login': USER_NAME, 'cursor': cursor})
        if not data:
            break
        info = data['data']['user']['repositories']
        repos.extend(e['node']['nameWithOwner'] for e in info['edges'])
        if not info['pageInfo']['hasNextPage']:
            break
        cursor = info['pageInfo']['endCursor']

    added = deleted = 0
    for repo in repos:
        owner, name = repo.split('/')
        try:
            r = requests.get(
                f'https://api.github.com/repos/{owner}/{name}/stats/contributors',
                headers=HEADERS, timeout=15,
            )
            if r.status_code == 200:
                for contrib in r.json():
                    if isinstance(contrib, dict) and contrib.get('author', {}).get('login') == USER_NAME:
                        for week in contrib.get('weeks', []):
                            added   += week.get('a', 0)
                            deleted += week.get('d', 0)
        except Exception:
            pass

    total = added + deleted
    return (f"{total:,}", f"{added:,}++", f"{deleted:,}--")

# ── SVG builder ───────────────────────────────────────────────────────────────
def escape(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

def build_svg(dark: bool, stats: dict, loc_total: str, loc_add: str, loc_del: str, uptime: str) -> str:
    # Theme colours
    if dark:
        bg        = '#0d1117'
        fg        = '#c9d1d9'
        dim       = '#8b949e'
        accent1   = '#f78166'   # red-orange  (labels)
        accent2   = '#79c0ff'   # blue        (values)
        ascii_col = '#3fb950'   # green        (ASCII)
        border    = '#30363d'
        head_col  = '#ffa657'   # orange      (section headers)
    else:
        bg        = '#ffffff'
        fg        = '#24292f'
        dim       = '#57606a'
        accent1   = '#cf222e'
        accent2   = '#0969da'
        ascii_col = '#1a7f37'
        border    = '#d0d7de'
        head_col  = '#953800'

    font     = "font-family=\"'Courier New', Courier, monospace\""
    fs       = 11.5        # info panel font-size px
    lh       = 15.5        # info panel line height px
    char_w   = 6.92        # info panel char width

    # ASCII art uses its own smaller font — all characters kept, just rendered smaller
    fs_ascii = 5.0         # ASCII font-size px  (143 chars * 3.01 = ~430px wide)
    lh_ascii = 6.1         # ASCII line height px (68 lines * 6.1  = ~415px tall)
    cw_ascii = 3.01        # char width at fs_ascii in Courier New

    ascii_panel_w = int(max(len(l) for l in ASCII_ART) * cw_ascii) + 8
    ascii_panel_h = int(len(ASCII_ART) * lh_ascii) + 8

    W   = ascii_panel_w + 480
    H   = max(ascii_panel_h + 36, 460)
    pad = 18

    info_x = ascii_panel_w + pad
    info_w = W - info_x - pad

    lines_svg = []

    # ── background + border ──────────────────────────────────────────────────
    lines_svg.append(f'<rect width="{W}" height="{H}" fill="{bg}" rx="8"/>')
    lines_svg.append(f'<rect width="{W}" height="{H}" fill="none" stroke="{border}" stroke-width="1" rx="8"/>')

    # ── ASCII art (full character resolution, smaller font) ───────────────────
    for i, row in enumerate(ASCII_ART):
        y = pad + lh_ascii + i * lh_ascii
        lines_svg.append(
            f'<text x="{pad}" y="{y}" {font} font-size="{fs_ascii}" '
            f'fill="{ascii_col}" xml:space="preserve" letter-spacing="0">{escape(row)}</text>'
        )

    # ── info panel ───────────────────────────────────────────────────────────
    def row(label, value, y, lcolor=accent1, vcolor=accent2, bold_val=False):
        dots = '.' * max(1, int((info_w / char_w - len(label) - len(str(value)) - 2) * 0.9))
        bw = 'font-weight="600"' if bold_val else ''
        lines_svg.append(
            f'<text x="{info_x}" y="{y}" {font} font-size="{fs}" fill="{lcolor}">{escape(label)}</text>'
        )
        lines_svg.append(
            f'<text x="{info_x + len(label) * char_w}" y="{y}" {font} font-size="{fs}" fill="{dim}">{dots}</text>'
        )
        lines_svg.append(
            f'<text x="{W - pad - len(str(value)) * char_w}" y="{y}" {font} font-size="{fs}" fill="{vcolor}" {bw}>{escape(str(value))}</text>'
        )

    def section_header(title, y):
        bar = '─' * int((info_w / char_w - len(title) - 3))
        lines_svg.append(
            f'<text x="{info_x}" y="{y}" {font} font-size="{fs}" fill="{head_col}" font-weight="600">'
            f'- {escape(title)} {escape(bar)}</text>'
        )

    def plain(text, y, color=None):
        c = color or fg
        lines_svg.append(
            f'<text x="{info_x}" y="{y}" {font} font-size="{fs}" fill="{c}" xml:space="preserve">{escape(text)}</text>'
        )

    y = pad + lh

    # prompt line
    lines_svg.append(
        f'<text x="{info_x}" y="{y}" {font} font-size="{fs + 1}" fill="{accent2}" font-weight="700">'
        f'hassan@h5n</text>'
    )
    lines_svg.append(
        f'<text x="{info_x + 10 * (fs + 1) * 0.6}" y="{y}" {font} font-size="{fs + 1}" fill="{dim}">'
        f' {"─" * 42}</text>'
    )

    y += lh * 1.4
    row('  OS',       'Linux · Windows',       y);   y += lh
    row('  Uptime',   uptime,                            y);   y += lh
    row('  Kernel',   'DevOps · Cloud · AI/ML · Systems', y);  y += lh
    row('  IDE',      'VSCode · AntiGravity · Jupyter',      y);   y += lh

    y += lh * 0.6
    row('  Lang.Code',  'Python · C/C++ · C#',  y); y += lh
    row('  DevOps.Cloud', 'Docker · CI/CD · AWS · Linux',   y); y += lh
    row('  Data.Bases',      'MySQL · PostgreSQL · MongoDB',                  y); y += lh
    row('  Frameworks', 'Django · React · ASP .NET · Scikit-learn', y); y += lh
    row('  Hobbies',    'Building things · Breaking things',  y); y += lh

    y += lh * 0.6
    section_header('Projects', y); y += lh

    # dynamic project list
    MAX_PROJ = 5
    for (pname, purl, pdesc) in PROJECTS[:MAX_PROJ]:
        label = f'  › {pname}'
        desc_short = pdesc[:38]
        dots = '.' * max(1, int((info_w / char_w - len(label) - len(desc_short) - 2) * 0.85))
        lines_svg.append(
            f'<text x="{info_x}" y="{y}" {font} font-size="{fs}" fill="{fg}">{escape(label)}</text>'
        )
        lines_svg.append(
            f'<text x="{info_x + len(label) * char_w}" y="{y}" {font} font-size="{fs}" fill="{dim}">{dots}</text>'
        )
        lines_svg.append(
            f'<text x="{W - pad - len(desc_short) * char_w}" y="{y}" {font} font-size="{fs}" fill="{dim}">{escape(desc_short)}</text>'
        )
        y += lh

    y += lh * 0.6
    section_header('Contact', y); y += lh
    row('  GitHub',   'github.com/hassanh5n',      y, vcolor=accent2); y += lh
    row('  LinkedIn', 'linkedin.com/in/shaikh-hassan-nafees-640998227', y, vcolor=accent2); y += lh
    row('  Email', 'hassannafees.hn@email.com',             y, vcolor=accent2); y += lh

    y += lh * 0.6
    section_header('GitHub Stats', y); y += lh
    row('  Repos',    f"{stats['repos']} (contributed: {stats['repos']})",  y); y += lh
    row('  Stars',    stats['stars'],     y); y += lh
    row('  Commits',  stats['commits'],   y); y += lh
    row('  Followers',stats['followers'], y); y += lh

    if loc_total != '??':
        lines_svg.append(
            f'<text x="{info_x}" y="{y}" {font} font-size="{fs}" fill="{fg}">  Lines of Code: {escape(loc_total)}'
            f' (</text>'
        )
        # green additions
        off = info_x + (18 + len(loc_total) + 2) * char_w
        lines_svg.append(
            f'<text x="{off}" y="{y}" {font} font-size="{fs}" fill="#3fb950">{escape(loc_add)}, </text>'
        )
        off2 = off + (len(loc_add) + 2) * char_w
        lines_svg.append(
            f'<text x="{off2}" y="{y}" {font} font-size="{fs}" fill="{accent1}">{escape(loc_del)}</text>'
        )
        off3 = off2 + len(loc_del) * char_w
        lines_svg.append(
            f'<text x="{off3}" y="{y}" {font} font-size="{fs}" fill="{fg}">)</text>'
        )

    inner = '\n  '.join(lines_svg)
    return (
        f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">\n'
        f'  {inner}\n'
        f'</svg>\n'
    )

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("Fetching stats…")
    stats     = get_user_stats()
    loc_t, loc_a, loc_d = get_loc()
    uptime    = calc_uptime()

    print(f"Stats: {stats}")
    print(f"Uptime: {uptime}")

    dark_svg  = build_svg(True,  stats, loc_t, loc_a, loc_d, uptime)
    light_svg = build_svg(False, stats, loc_t, loc_a, loc_d, uptime)

    with open('dark_mode.svg',  'w', encoding='utf-8') as f:
        f.write(dark_svg)
    with open('light_mode.svg', 'w', encoding='utf-8') as f:
        f.write(light_svg)

    print("✅  dark_mode.svg  and  light_mode.svg  written.")

if __name__ == '__main__':
    main()