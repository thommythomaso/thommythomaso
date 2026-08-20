#!/usr/bin/env python3
"""Render the contribution graphics in assets/ from the GitHub API.

Writes two colour-neutral SVGs that read on GitHub's light and dark canvas:

  assets/contributions.svg  all-time commits, pull requests, reviews, issues
  assets/activity.svg       contributions per week over the last year

contributionsCollection only covers twelve months per query, so the all-time
totals are summed year by year from the account creation date.
"""

import json
import math
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

USER = os.environ.get("GH_USER", "thommythomaso")
ASSETS = Path(__file__).resolve().parent.parent / "assets"

METRICS = [
    ("Commits", "totalCommitContributions"),
    ("Pull requests", "totalPullRequestContributions"),
    ("Reviews", "totalPullRequestReviewContributions"),
    ("Issues", "totalIssueContributions"),
]

# Colours that hold up on #ffffff and on #0d1117, so one file serves both themes.
ACCENT = "#3b82f6"
MUTED = "#8b949e"
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"

QUERY = """
query($login:String!, $from:DateTime!, $to:DateTime!) {
  user(login:$login) {
    createdAt
    contributionsCollection(from:$from, to:$to) {
      totalCommitContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      totalIssueContributions
      contributionCalendar {
        weeks {
          firstDay
          contributionDays { contributionCount }
        }
      }
    }
  }
}
"""


def graphql(variables):
    cmd = ["gh", "api", "graphql", "-f", f"query={QUERY}"]
    for key, value in variables.items():
        cmd += ["-f", f"{key}={value}"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"gh api failed: {result.stderr.strip()}")
    payload = json.loads(result.stdout)
    if "errors" in payload:
        sys.exit(f"GraphQL error: {payload['errors']}")
    return payload["data"]["user"]


def collect():
    now = datetime.now(timezone.utc)
    last_year = graphql({"login": USER, "from": (now - timedelta(days=364)).isoformat(),
                         "to": now.isoformat()})
    created = datetime.fromisoformat(last_year["createdAt"].replace("Z", "+00:00"))

    totals = {key: 0 for _, key in METRICS}
    start = created
    while start < now:
        end = min(start.replace(year=start.year + 1), now)
        window = graphql({"login": USER, "from": start.isoformat(), "to": end.isoformat()})
        for _, key in METRICS:
            totals[key] += window["contributionsCollection"][key]
        start = end

    weeks = [
        (week["firstDay"], sum(d["contributionCount"] for d in week["contributionDays"]))
        for week in last_year["contributionsCollection"]["contributionCalendar"]["weeks"]
    ]
    return totals, weeks


# --- layout helpers --------------------------------------------------------
# There is no text metrics engine here, so widths are estimated and every
# placed label is checked against the canvas and its neighbours. Overlaps in
# generated SVGs are invisible until someone opens the file, hence check().


def text_width(s, size):
    return 0.58 * size * len(s)


def check(boxes, width, height):
    """boxes: (name, x0, x1) on the same visual row, plus canvas bounds."""
    for name, x0, x1 in boxes:
        if x0 < 0 or x1 > width:
            sys.exit(f"layout: {name} runs from {x0:.0f} to {x1:.0f}, canvas is 0..{width}")
    ordered = sorted(boxes, key=lambda b: b[1])
    for (a, _, a1), (b, b0, _) in zip(ordered, ordered[1:]):
        if b0 < a1:
            sys.exit(f"layout: {a} overlaps {b} ({a1:.0f} > {b0:.0f})")


def svg_open(width, height):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" font-family="{FONT}">')


# --- radar -----------------------------------------------------------------
RW, RH = 560, 250
CX, CY, RAD = 140, 122, 80
COL = 350  # left edge of the figures column


def spoke(index, radius):
    angle = math.radians(-90 + index * 90)
    return CX + radius * math.cos(angle), CY + radius * math.sin(angle)


def render_radar(totals):
    values = [totals[key] for _, key in METRICS]
    # Commits outnumber issues by roughly twenty to one; on a linear radius the
    # three smaller axes collapse into the centre and the shape says nothing.
    radii = [math.sqrt(v) for v in values]
    peak = max(radii) or 1

    out = [svg_open(RW, RH)]

    for ring in (0.25, 0.5, 0.75, 1.0):
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (spoke(i, RAD * ring) for i in range(4)))
        out.append(f'<polygon points="{pts}" fill="none" stroke="{MUTED}" '
                   f'stroke-opacity="0.3" stroke-width="1"/>')
    for i in range(4):
        x, y = spoke(i, RAD)
        out.append(f'<line x1="{CX}" y1="{CY}" x2="{x:.1f}" y2="{y:.1f}" stroke="{MUTED}" '
                   f'stroke-opacity="0.3" stroke-width="1"/>')

    pts = " ".join(f"{x:.1f},{y:.1f}"
                   for x, y in (spoke(i, RAD * r / peak) for i, r in enumerate(radii)))
    out.append(f'<polygon points="{pts}" fill="{ACCENT}" fill-opacity="0.16" stroke="{ACCENT}" '
               f'stroke-width="2" stroke-linejoin="round"/>')
    for i, r in enumerate(radii):
        x, y = spoke(i, RAD * r / peak)
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{ACCENT}"/>')

    label_size = 11
    gap = 12
    placements = [
        ("middle", CX, CY - RAD - gap),
        ("start", CX + RAD + gap, CY + 4),
        ("middle", CX, CY + RAD + gap + 8),
        ("end", CX - RAD - gap, CY + 4),
    ]
    row = []
    for i, (label, _) in enumerate(METRICS):
        anchor, x, y = placements[i]
        width = text_width(label, label_size)
        x0 = {"middle": x - width / 2, "start": x, "end": x - width}[anchor]
        if i in (1, 3):  # the two labels that share a row with the figures column
            row.append((label, x0, x0 + width))
        out.append(f'<text x="{x:.0f}" y="{y:.0f}" fill="{MUTED}" font-size="{label_size}" '
                   f'text-anchor="{anchor}">{label}</text>')

    value_size, name_size, note_size = 24, 11.5, 10
    note = "all-time totals · radius ∝ √count"
    widest = max(text_width(name, name_size) for name, _ in METRICS)
    row.append(("figures column", COL, COL + max(widest, text_width(note, note_size))))
    check(row, RW, RH)

    for i, (label, key) in enumerate(METRICS):
        y = 38 + i * 46
        out.append(f'<text x="{COL}" y="{y}" fill="{ACCENT}" font-size="{value_size}" '
                   f'font-weight="600" font-variant-numeric="tabular-nums">{totals[key]}</text>')
        out.append(f'<text x="{COL}" y="{y + 17}" fill="{MUTED}" font-size="{name_size}">'
                   f'{label}</text>')
    out.append(f'<text x="{COL}" y="{38 + 4 * 46 - 6}" fill="{MUTED}" font-size="{note_size}" '
               f'fill-opacity="0.85">{note}</text>')

    out.append("</svg>")
    return "\n".join(out)


# --- activity --------------------------------------------------------------
AW, AH = 560, 150
PLOT_L, PLOT_R, PLOT_T, PLOT_B = 34, 546, 26, 108


def render_activity(weeks):
    counts = [count for _, count in weeks]
    peak = max(counts) or 1
    span = PLOT_R - PLOT_L
    step = span / max(len(counts) - 1, 1)

    def x_of(i):
        return PLOT_L + i * step

    def y_of(count):
        return PLOT_B - (PLOT_B - PLOT_T) * count / peak

    out = [svg_open(AW, AH)]

    for frac in (0.5, 1.0):
        y = PLOT_B - (PLOT_B - PLOT_T) * frac
        out.append(f'<line x1="{PLOT_L}" y1="{y:.1f}" x2="{PLOT_R}" y2="{y:.1f}" '
                   f'stroke="{MUTED}" stroke-opacity="0.22" stroke-width="1"/>')
    out.append(f'<line x1="{PLOT_L}" y1="{PLOT_B}" x2="{PLOT_R}" y2="{PLOT_B}" stroke="{MUTED}" '
               f'stroke-opacity="0.4" stroke-width="1"/>')

    line = " ".join(f"{x_of(i):.1f},{y_of(c):.1f}" for i, c in enumerate(counts))
    out.append(f'<polygon points="{PLOT_L},{PLOT_B} {line} {PLOT_R},{PLOT_B}" fill="{ACCENT}" '
               f'fill-opacity="0.14"/>')
    out.append(f'<polyline points="{line}" fill="none" stroke="{ACCENT}" stroke-width="1.8" '
               f'stroke-linejoin="round" stroke-linecap="round"/>')

    out.append(f'<text x="{PLOT_L - 6}" y="{PLOT_T + 4}" fill="{MUTED}" font-size="10" '
               f'text-anchor="end">{peak}</text>')
    out.append(f'<text x="{PLOT_L - 6}" y="{PLOT_B + 4}" fill="{MUTED}" font-size="10" '
               f'text-anchor="end">0</text>')

    seen, ticks = set(), []
    for i, (first_day, _) in enumerate(weeks):
        month = datetime.fromisoformat(first_day).strftime("%b")
        key = first_day[:7]
        if key in seen or i % 2:
            continue
        seen.add(key)
        ticks.append((x_of(i), month))
    ticks = ticks[::2]  # every other month keeps the axis from crowding

    row = []
    for x, month in ticks:
        width = text_width(month, 10)
        row.append((month + f"@{x:.0f}", x - width / 2, x + width / 2))
        out.append(f'<text x="{x:.0f}" y="{PLOT_B + 18}" fill="{MUTED}" font-size="10" '
                   f'text-anchor="middle">{month}</text>')
    check(row, AW, AH)

    caption = "contributions per week, last 12 months"
    out.append(f'<text x="{PLOT_L}" y="{AH - 8}" fill="{MUTED}" font-size="10" '
               f'fill-opacity="0.85">{caption}</text>')

    out.append("</svg>")
    return "\n".join(out)


if __name__ == "__main__":
    totals, weeks = collect()
    print(json.dumps(totals, indent=2))
    print(f"{len(weeks)} weeks, peak {max(c for _, c in weeks)}")
    ASSETS.mkdir(parents=True, exist_ok=True)
    (ASSETS / "contributions.svg").write_text(render_radar(totals) + "\n")
    (ASSETS / "activity.svg").write_text(render_activity(weeks) + "\n")
    print(f"wrote {ASSETS}/contributions.svg and {ASSETS}/activity.svg")
