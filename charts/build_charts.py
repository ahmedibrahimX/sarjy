"""Builds the slide/Slack-ready charts from measured Phase 2 data.

Values are the measured p50s recorded in LATENCY.md (human turns on the
deployed instance) — hardcoded with citations rather than fetched live, so
the chart is pinned to the dataset it claims to show.

Run: uv run --with matplotlib python charts/build_charts.py
"""

import matplotlib
import matplotlib.pyplot as plt

matplotlib.rcParams["font.family"] = "monospace"

BG = "#0e0f12"
SURFACE = "#1c1f26"
INK = "#eae7de"
MUTED = "#8d93a0"
GREEN = "#6ee7a0"
BLUE = "#7aa2f7"
BLUE_DIM = "#46587a"
AMBER = "#ffb454"

# Before: tap weather, warm, all flags off — LATENCY.md human baseline (n=4)
BEFORE = [
    ("endpointing (Chrome)", 1470, GREEN),
    ("send to first byte", 1158, BLUE),
    ("wait for full reply (tool + stream)", 2378, BLUE_DIM),
    ("tts", 6, AMBER),
]
# After: tap weather, warm, shipped config — final 8-rep validation
AFTER_SOLID = [
    ("endpointing (VAD, 600 ms)", 986, GREEN),
    ("send to first byte = ack speaks", 975, BLUE),
]
AFTER_PERCEIVED = 1961
AFTER_ACTUAL = 3568


def waterfall() -> None:
    fig, ax = plt.subplots(figsize=(10, 3.4), dpi=220)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)

    y_before, y_after, h = 1.0, 0.0, 0.42

    x = 0.0
    for _, ms, color in BEFORE:
        ax.barh(y_before, ms, left=x, height=h, color=color, edgecolor=BG, linewidth=0.6)
        x += ms
    before_total = x
    ax.text(before_total + 60, y_before, f"{before_total/1000:.1f} s actual",
            va="center", ha="left", color=INK, fontsize=11, fontweight="bold")

    x = 0.0
    for _, ms, color in AFTER_SOLID:
        ax.barh(y_after, ms, left=x, height=h, color=color, edgecolor=BG, linewidth=0.6)
        x += ms
    ax.barh(y_after, AFTER_ACTUAL - x, left=x, height=h, color=BLUE_DIM,
            edgecolor=BG, linewidth=0.6, alpha=0.45, hatch="//")
    ax.text(AFTER_ACTUAL + 60, y_after, f"{AFTER_ACTUAL/1000:.1f} s actual",
            va="center", ha="left", color=MUTED, fontsize=10)

    # voice-start marker on the after bar
    ax.annotate(
        f"voice starts: {AFTER_PERCEIVED/1000:.2f} s perceived",
        xy=(AFTER_PERCEIVED, y_after - h / 2 - 0.03),
        xytext=(AFTER_PERCEIVED + 150, y_after - 0.52),
        color=AMBER, fontsize=10.5, fontweight="bold",
        arrowprops={"arrowstyle": "->", "color": AMBER, "lw": 1.4},
    )

    ax.set_yticks([y_before, y_after])
    ax.set_yticklabels(["before\n(all flags off)", "after\n(shipped config)"],
                       color=INK, fontsize=10)
    ax.set_xlim(0, 5600)
    ax.set_ylim(-0.85, 1.5)
    ax.set_xticks(range(0, 5501, 1000))
    ax.set_xticklabels([f"{t/1000:.0f}s" for t in range(0, 5501, 1000)],
                       color=MUTED, fontsize=9)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(length=0)
    ax.grid(axis="x", color=SURFACE, linewidth=0.8)
    ax.set_axisbelow(True)

    handles = [
        plt.Rectangle((0, 0), 1, 1, color=GREEN),
        plt.Rectangle((0, 0), 1, 1, color=BLUE),
        plt.Rectangle((0, 0), 1, 1, color=BLUE_DIM),
        plt.Rectangle((0, 0), 1, 1, color=BLUE_DIM, alpha=0.45, hatch="//"),
    ]
    labels = [
        "endpointing",
        "network + first token",
        "tool + reply stream (blocking)",
        "tool + reply stream (under audio)",
    ]
    leg = ax.legend(handles, labels, loc="upper left", bbox_to_anchor=(0, -0.18),
                    ncol=4, frameon=False, fontsize=8.5, handlelength=1.2,
                    columnspacing=1.4)
    for text in leg.get_texts():
        text.set_color(MUTED)

    ax.set_title(
        "Sarjy time-to-first-audio: the same weather question, before and after\n",
        color=INK, fontsize=13, fontweight="bold", loc="left", pad=18,
    )
    ax.text(0, 1.52, "tap mode, warm turns, p50 (n=4 before / n=8 after), measured on the deployed instance",
            transform=ax.get_yaxis_transform(), color=MUTED, fontsize=9)

    fig.tight_layout()
    fig.savefig("charts/before_after_waterfall.png", facecolor=BG,
                bbox_inches="tight", pad_inches=0.35)
    print("wrote charts/before_after_waterfall.png")


if __name__ == "__main__":
    waterfall()
