"""
The look of the whole app: one palette, one stylesheet, a few building blocks.

Every page imports from here, so changing how the app looks means editing
this file (and .streamlit/config.toml) and nothing else.

Theme: a cricket ground on match day. Deep outfield greens, cream cards,
one gold accent, wooden stumps and a red ball. The bold stadium banner is
used on the Home page only; the analysis pages stay calm so tables and
charts are easy to read.

Rule: the look can be decorative, but every NUMBER on screen comes from
the database. Nothing here invents a statistic.
"""

from __future__ import annotations

import streamlit as st

# --------------------------------------------------------------------------
# palette
# --------------------------------------------------------------------------

NIGHT = "#07130F"      # night sky, darkest background
PITCH_DARK = "#0E2118" # sidebar, dark cards
OUTFIELD = "#173D2C"   # deep green
GRASS = "#3D7A50"      # bright grass
GOLD = "#C7A45A"       # the ONE accent colour
GOLD_DEEP = "#A8894E"  # gold dark enough to read on cream
SAND = "#DFC99C"       # pitch strip
BALL_RED = "#8D2B28"   # cricket ball
CREAM = "#F6F7F2"      # page background
INK = "#132018"        # main text
MUTED = "#728078"      # labels, secondary text

# Colours for chart series, used in this fixed order so a series keeps its
# colour when a filter changes how many series are shown.
SERIES = ["#2F6B4A", "#C7A45A", "#8D2B28", "#4F7FA8",
          "#B86B3A", "#7A6BA8", "#6E8B3D", "#9A9A8E"]

# Status colours: always shown with a word beside them, never colour alone.
STATUS = {"good": "#2F7A3F", "warning": "#C7962A", "critical": "#B23A34"}

ACCENT = GOLD


# --------------------------------------------------------------------------
# stylesheet
# --------------------------------------------------------------------------

_CSS = """
<style>
:root {
  --cb-night: #07130F;  --cb-pitch: #0E2118;  --cb-outfield: #173D2C;
  --cb-grass: #3D7A50;  --cb-gold: #C7A45A;   --cb-gold-deep: #A8894E;
  --cb-sand: #DFC99C;   --cb-red: #8D2B28;
  --cb-cream: #F6F7F2;  --cb-card: #FFFFFF;   --cb-ink: #132018;
  --cb-ink-2: #3E4C44;  --cb-muted: #728078;  --cb-line: #DFE4DF;
}

.block-container { padding-top: 4.6rem; padding-bottom: 4rem; max-width: 1180px; }

/* ---- page heading (used on every page except Home) ---- */
.cb-eyebrow {
  font-size: 0.72rem; font-weight: 700; letter-spacing: 0.2em;
  text-transform: uppercase; color: var(--cb-gold-deep); margin-bottom: 0.3rem;
}
.cb-title {
  font-size: 2.1rem; font-weight: 850; letter-spacing: -0.035em;
  color: var(--cb-ink); line-height: 1.05; margin: 0 0 0.35rem 0;
}
.cb-sub { font-size: 0.98rem; color: var(--cb-ink-2); margin: 0 0 1.6rem 0; }

/* ---- plain hero number (non-Home pages) ---- */
.cb-hero { margin: 0.4rem 0 1.8rem 0; }
.cb-hero-value {
  font-size: 3.4rem; font-weight: 850; line-height: 1;
  letter-spacing: -0.04em; color: var(--cb-ink);
}
.cb-hero-label { font-size: 1rem; color: var(--cb-ink-2); margin-top: 0.45rem; }

/* ---- stat tiles: dark green with a gold bar ---- */
.cb-tiles { display: flex; gap: 0.75rem; flex-wrap: wrap; margin: 1.2rem 0 1.6rem 0; }
.cb-tile {
  flex: 1 1 130px; background: var(--cb-pitch); color: #E7EFEA;
  border: 1px solid rgba(255,255,255,0.07); border-radius: 16px;
  padding: 0.95rem 1rem 0.85rem 1rem; position: relative; overflow: hidden;
}
.cb-tile::after {
  content: ""; position: absolute; left: 1rem; right: 1rem; bottom: 0.55rem;
  height: 3px; border-radius: 99px; background: var(--cb-gold); opacity: 0.85;
}
.cb-tile-label {
  font-size: 0.66rem; color: #8EA49A; text-transform: uppercase;
  letter-spacing: 0.14em; font-weight: 700;
}
.cb-tile-value {
  font-size: 1.7rem; font-weight: 850; color: #F4F7F3;
  line-height: 1.15; margin-top: 0.3rem; letter-spacing: -0.02em;
}
.cb-tile-note { font-size: 0.74rem; color: #9FB2A8; margin: 0.15rem 0 0.6rem 0; }

/* ---- cards: cream (light) and outfield (dark) ---- */
.cb-card {
  background: var(--cb-card); border: 1px solid var(--cb-line);
  border-radius: 20px; padding: 1.2rem 1.35rem; height: 100%;
}
.cb-card h4 {
  font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.17em;
  color: var(--cb-muted); font-weight: 700; margin: 0 0 0.8rem 0;
}
.cb-card p { color: var(--cb-ink-2); font-size: 0.93rem; line-height: 1.6; margin: 0 0 0.6rem 0; }
.cb-card a { color: var(--cb-gold-deep); font-weight: 600; text-decoration: none; }
.cb-card a:hover { text-decoration: underline; }
.cb-card.dark { background: var(--cb-pitch); border-color: rgba(255,255,255,0.08); }
.cb-card.dark h4 { color: #95AAA0; }
.cb-card.dark p { color: #C9D6CF; }
.cb-card.dark strong { color: #F4F7F3; }

/* ---- page list inside a card ---- */
.cb-nav-item { display: flex; gap: 0.7rem; padding: 0.45rem 0; align-items: baseline;
               border-bottom: 1px solid rgba(255,255,255,0.06); }
.cb-nav-item:last-child { border-bottom: none; }
.cb-nav-name { font-weight: 700; color: var(--cb-gold); font-size: 0.92rem; min-width: 8.5rem; }
.cb-nav-desc { color: #C9D6CF; font-size: 0.88rem; }

/* ---- chips ---- */
.cb-chip {
  display: inline-block; padding: 0.16rem 0.6rem; border-radius: 999px;
  font-size: 0.72rem; font-weight: 700; letter-spacing: 0.06em;
  border: 1px solid var(--cb-line); color: var(--cb-ink-2); margin-right: 0.35rem;
}
.cb-chip-live { color: #fff; background: var(--cb-red); border-color: var(--cb-red); }

/* ---- section heading + rule ---- */
.cb-section {
  font-size: 1.25rem; font-weight: 800; letter-spacing: -0.02em;
  color: var(--cb-ink); margin: 0 0 0.2rem 0;
}
.cb-rule { border: none; border-top: 1px solid var(--cb-line); margin: 2rem 0 1.4rem 0; }

/* ---- tables ---- */
[data-testid="stDataFrame"] { border: 1px solid var(--cb-line); border-radius: 14px; overflow: hidden; }

/* ---- sidebar ---- */
[data-testid="stSidebarNav"] { padding-top: 0.5rem; }
[data-testid="stSidebarNav"] a[aria-current="page"] {
  background: rgba(199,164,90,0.16); border-left: 3px solid var(--cb-gold);
}

/* ================================================================
   STADIUM BANNER (Home page only)
   Drawn entirely with CSS: no images, no JavaScript.
   ================================================================ */
.cb-stadium {
  position: relative; min-height: 500px; border-radius: 24px; overflow: hidden;
  background: linear-gradient(180deg, #07130F 0%, #10231B 42%, #173E2C 67%, #234F37 100%);
  border: 1px solid rgba(255,255,255,0.10); margin-bottom: 0.5rem; color: #EEF4F2;
}
.cb-stadium .lights {
  position: absolute; inset: 0; pointer-events: none;
  background:
    radial-gradient(circle at 12% 4%, rgba(255,244,194,.28), transparent 18%),
    radial-gradient(circle at 88% 8%, rgba(255,244,194,.22), transparent 18%),
    linear-gradient(115deg, transparent 0 18%, rgba(255,255,255,.07) 20%, transparent 23% 77%,
                    rgba(255,255,255,.05) 80%, transparent 83%);
  animation: cbFlicker 6s ease-in-out infinite;
}
.cb-stadium .roof {
  position: absolute; left: 0; right: 0; top: 20px; height: 170px; opacity: .75;
  background: repeating-linear-gradient(90deg, rgba(210,225,219,.10) 0 18px, rgba(7,18,14,.13) 18px 34px);
  clip-path: polygon(0 15%, 100% 0, 100% 100%, 0 100%);
}
.cb-stadium .stands {
  position: absolute; left: 5%; right: 5%; top: 64px; height: 105px; opacity: .34;
  background: repeating-linear-gradient(90deg, #9AAEAD 0 8px, #829896 8px 12px);
  clip-path: polygon(0 0, 100% 9%, 96% 100%, 4% 100%);
}
.cb-stadium .horizon {
  position: absolute; left: 0; right: 0; top: 170px; height: 24px;
  background: linear-gradient(90deg, #152B22, #21382B, #152A21);
  border-top: 1px solid rgba(255,255,255,.10); border-bottom: 1px solid rgba(0,0,0,.35);
}
.cb-stadium .outfield {
  position: absolute; left: -8%; right: -8%; bottom: -125px; height: 365px;
  background: radial-gradient(ellipse at center, #3D7A50 0%, #2B6541 48%, #1D4E36 75%);
  transform: perspective(520px) rotateX(54deg); transform-origin: center top;
}
.cb-stadium .strip {
  position: absolute; left: 56%; width: 28%; bottom: 0; height: 190px;
  background: linear-gradient(90deg, #C5AB78, #DFC99C 49%, #C5AB78);
  clip-path: polygon(30% 0, 70% 0, 100% 100%, 0 100%); opacity: .95;
}
.cb-stadium .crease {
  position: absolute; left: 58%; width: 24%; height: 4px; bottom: 86px; background: #F1EEE5;
  box-shadow: 0 72px 0 rgba(241,238,229,.9);
}

/* ---- the wicket: three stumps, two bails ----
   All three movements (ball, stumps, bails) share ONE 5-second timeline,
   so they stay in step: the ball arrives at 40%, and at that exact moment
   the bails fly and the stumps splay. */
.cb-stadium .wicket {
  position: absolute; left: 70%; bottom: 86px; width: 38px; height: 118px;
  margin-left: -19px; z-index: 4;
}
.cb-stadium .wicket i {
  position: absolute; bottom: 0; width: 8px; height: 118px; border-radius: 4px 4px 2px 2px;
  background: linear-gradient(90deg, #A57B3F, #E2C27C, #9B7139);
  transform-origin: 50% 100%;               /* pivot at the base, like a stump in the ground */
  animation: 5s ease-out infinite;
}
.cb-stadium .wicket .s1 { left: 0;    animation-name: cbStumpLeft; }
.cb-stadium .wicket .s2 { left: 15px; animation-name: cbStumpMiddle; }
.cb-stadium .wicket .s3 { left: 30px; animation-name: cbStumpRight; }

.cb-stadium .bail {
  position: absolute; top: -4px; width: 17px; height: 5px; border-radius: 3px;
  background: #DABD80; box-shadow: 0 1px 0 rgba(0,0,0,.25);
  animation: 5s ease-out infinite;
}
.cb-stadium .b1 { left: 2px;  animation-name: cbBailLeft; }   /* sits on stumps 1 and 2 */
.cb-stadium .b2 { left: 19px; animation-name: cbBailRight; }  /* sits on stumps 2 and 3 */

/* ---- the ball: bowled from our end, bounces once, hits middle stump ---- */
.cb-stadium .ball {
  position: absolute; z-index: 8; left: 70%; bottom: 112px; width: 18px; height: 18px;
  margin-left: -9px; border-radius: 50%; background: #8D2B28;
  box-shadow: 0 0 0 2px rgba(255,255,255,.08), 0 8px 18px rgba(0,0,0,.35);
  animation: cbDelivery 5s linear infinite;
}
.cb-stadium .ball::after {
  content: ""; position: absolute; left: 7px; top: 1px; width: 2px; height: 16px;
  background: #E7D8CB; transform: rotate(25deg); opacity: .85;
}

@keyframes cbDelivery {
  0%   { transform: translate(-60px, 360px) scale(1.7); opacity: 0; }
  6%   { opacity: 1; }
  28%  { transform: translate(-12px, 95px) scale(1.05); animation-timing-function: ease-out; } /* pitches */
  40%  { transform: translate(0, 0) scale(.9); }                                               /* hits the stumps */
  48%  { transform: translate(10px, 34px) scale(.85); opacity: .9; }                           /* drops away */
  56%  { transform: translate(14px, 44px) scale(.85); opacity: 0; }
  100% { transform: translate(14px, 44px) scale(.85); opacity: 0; }
}

/* Stumps: upright, then knocked back and apart at 40%, then fade and reset. */
@keyframes cbStumpLeft {
  0%, 40%  { transform: rotate(0);      opacity: 1; }
  47%      { transform: rotate(-15deg); }
  86%      { transform: rotate(-15deg); opacity: 1; }
  91%      { transform: rotate(-15deg); opacity: 0; }
  92%      { transform: rotate(0);      opacity: 0; }
  100%     { transform: rotate(0);      opacity: 1; }
}
@keyframes cbStumpMiddle {
  0%, 40%  { transform: rotate(0) translateY(0);    opacity: 1; }
  45%      { transform: rotate(-4deg) translateY(3px); }
  86%      { transform: rotate(-4deg) translateY(3px); opacity: 1; }
  91%      { transform: rotate(-4deg) translateY(3px); opacity: 0; }
  92%      { transform: rotate(0) translateY(0);    opacity: 0; }
  100%     { transform: rotate(0) translateY(0);    opacity: 1; }
}
@keyframes cbStumpRight {
  0%, 40%  { transform: rotate(0);     opacity: 1; }
  47%      { transform: rotate(17deg); }
  86%      { transform: rotate(17deg); opacity: 1; }
  91%      { transform: rotate(17deg); opacity: 0; }
  92%      { transform: rotate(0);     opacity: 0; }
  100%     { transform: rotate(0);     opacity: 1; }
}

/* Bails: pop up spinning, then fall to the ground either side. */
@keyframes cbBailLeft {
  0%, 40%  { transform: translate(0, 0) rotate(0);             opacity: 1; animation-timing-function: ease-out; }
  55%      { transform: translate(-30px, -62px) rotate(-260deg); animation-timing-function: ease-in; }
  70%      { transform: translate(-50px, 113px) rotate(-430deg); }
  86%      { transform: translate(-50px, 113px) rotate(-430deg); opacity: 1; }
  91%      { transform: translate(-50px, 113px) rotate(-430deg); opacity: 0; }
  92%      { transform: translate(0, 0) rotate(0);             opacity: 0; }
  100%     { transform: translate(0, 0) rotate(0);             opacity: 1; }
}
@keyframes cbBailRight {
  0%, 40%  { transform: translate(0, 0) rotate(0);             opacity: 1; animation-timing-function: ease-out; }
  53%      { transform: translate(26px, -78px) rotate(300deg); animation-timing-function: ease-in; }
  72%      { transform: translate(52px, 113px) rotate(520deg); }
  86%      { transform: translate(52px, 113px) rotate(520deg); opacity: 1; }
  91%      { transform: translate(52px, 113px) rotate(520deg); opacity: 0; }
  92%      { transform: translate(0, 0) rotate(0);             opacity: 0; }
  100%     { transform: translate(0, 0) rotate(0);             opacity: 1; }
}
@keyframes cbFlicker { 0%, 100% { opacity: 1; } 50% { opacity: .82; } }

.cb-stadium .topbar {
  position: absolute; z-index: 10; left: 26px; right: 26px; top: 22px;
  display: flex; justify-content: space-between; align-items: center; gap: 12px;
}
.cb-stadium .brand { font-weight: 800; letter-spacing: .16em; font-size: 11px; color: #D9E5DF; }
.cb-stadium .brand span { color: var(--cb-gold); }
.cb-stadium .status {
  font-size: 10px; letter-spacing: .14em; text-transform: uppercase; color: #D8E0DA;
  background: rgba(4,15,11,.48); border: 1px solid rgba(255,255,255,.10);
  padding: 8px 12px; border-radius: 999px;
}
.cb-stadium .copy { position: absolute; z-index: 7; left: 28px; top: 78px; max-width: 470px; }
.cb-stadium .eyebrow { font-size: 11px; text-transform: uppercase; letter-spacing: .22em; color: #DDC88F; }
.cb-stadium .title {
  font-size: clamp(32px, 5vw, 54px); line-height: .95; font-weight: 900;
  letter-spacing: -.05em; margin: 12px 0 14px; color: #F4F7F3;
}
.cb-stadium .title span { color: var(--cb-gold); }
.cb-stadium .sub { font-size: 14px; line-height: 1.6; color: #C1CEC8; max-width: 420px; }
.cb-stadium .pill { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 22px; }
.cb-stadium .pill div {
  padding: 11px 14px; background: rgba(7,18,14,.62); border: 1px solid rgba(255,255,255,.11);
  border-radius: 14px; backdrop-filter: blur(8px); min-width: 118px;
}
.cb-stadium .pill small {
  display: block; font-size: 9px; text-transform: uppercase; letter-spacing: .16em; color: #9EB0A7;
}
.cb-stadium .pill strong { display: block; font-size: 24px; font-weight: 850; color: #F4F7F3; margin-top: 2px; }

@media (max-width: 720px) {
  .cb-stadium { min-height: 480px; }
  .cb-stadium .copy { left: 20px; right: 20px; top: 76px; }
  .cb-stadium .strip, .cb-stadium .crease { left: 60%; width: 34%; }
  .cb-stadium .wicket, .cb-stadium .ball { left: 77%; }
  .cb-stadium .status { display: none; }
}
/* Respect the "reduce motion" setting on the viewer's computer. */
@media (prefers-reduced-motion: reduce) {
  .cb-stadium .ball, .cb-stadium .lights,
  .cb-stadium .wicket i, .cb-stadium .bail { animation: none; }
  .cb-stadium .ball { opacity: 0; }
}
/* ================================================================
   TOP NAVIGATION, LIVE STRIP, SIDEBAR
   ================================================================ */
/* Streamlit's top bar: cream, with a thin line under it. */
header[data-testid="stHeader"] { background: rgba(246,247,242,0.94); border-bottom: 1px solid var(--cb-line); }

/* Live-score strip under the navigation */
.cb-strip {
  display: flex; align-items: center; gap: 0.7rem; flex-wrap: wrap;
  background: var(--cb-pitch); color: #DCE6E0; border-radius: 12px;
  padding: 0.5rem 0.9rem; margin: 0 0 1.3rem 0; font-size: 0.84rem;
  border: 1px solid rgba(255,255,255,0.06);
}
.cb-strip-badge {
  font-size: 0.66rem; font-weight: 800; letter-spacing: 0.14em;
  padding: 0.2rem 0.55rem; border-radius: 999px;
  background: rgba(199,164,90,0.16); color: var(--cb-gold);
}
.cb-strip-badge.live { background: var(--cb-red); color: #fff; animation: cbPulse 2s ease-in-out infinite; }
.cb-strip-badge.off  { background: rgba(255,255,255,0.08); color: #9FB2A8; }
.cb-strip-item b { color: #F4F7F3; font-weight: 700; }
.cb-strip-item i { color: #8EA49A; font-style: normal; margin: 0 0.15rem; }
.cb-strip-item em { font-style: normal; font-size: 0.7rem; color: var(--cb-gold); margin-left: 0.3rem; }
.cb-strip-item.muted { color: #8EA49A; }
.cb-strip-sep { color: #4E6A5C; }
@keyframes cbPulse { 0%, 100% { opacity: 1; } 50% { opacity: .65; } }

/* Sidebar blocks */
.cb-side-label {
  font-size: 0.66rem; font-weight: 700; letter-spacing: 0.16em; text-transform: uppercase;
  color: #8EA49A; margin: 1.1rem 0 0.45rem 0;
}

/* One-line takeaway under every chart */
.cb-takeaway {
  font-size: 0.9rem; color: var(--cb-ink-2); line-height: 1.55;
  border-left: 3px solid var(--cb-gold); padding: 0.15rem 0 0.15rem 0.75rem;
  margin: 0.2rem 0 0.8rem 0;
}
.cb-takeaway strong { color: var(--cb-ink); }

/* Active-filters line under the live strip */
.cb-filterbar { display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; }
.cb-filterbar-label {
  font-size: 0.66rem; font-weight: 700; letter-spacing: 0.16em; text-transform: uppercase;
  color: var(--cb-muted); margin-right: 0.3rem;
}
.cb-chip.on { background: rgba(199,164,90,0.14); border-color: rgba(168,137,78,0.45); color: #6E5424; }

/* Sidebar widget labels on the dark background */
[data-testid="stSidebar"] label p { color: #B9C8C0 !important; font-size: 0.8rem; }

.cb-side-hint { font-size: 0.76rem; color: #8EA49A; margin-top: 0.4rem; }
.cb-side-hint b { color: #E7EFEA; font-weight: 600; }
.cb-status { font-size: 0.82rem; color: #C9D6CF; line-height: 1.9; }
.cb-status b { color: #F4F7F3; font-weight: 600; }
.cb-status .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 0.5rem; }
.cb-status .dot.ok   { background: #5FB77A; }
.cb-status .dot.warn { background: var(--cb-gold); }
.cb-status .dot.bad  { background: #D0574F; }
.cb-status .dot.none { background: #4E6A5C; }

@media (prefers-reduced-motion: reduce) { .cb-strip-badge.live { animation: none; } }
</style>
"""


def apply_theme() -> None:
    """Inject the stylesheet. Called once, in app.py, before any page runs."""
    st.markdown(_CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------
# building blocks
# --------------------------------------------------------------------------

def stadium_banner(title_html: str, subtitle: str, stats: list[tuple[str, str]],
                   eyebrow: str = "The game · the ground · the numbers",
                   status: str = "Live data · SQL analytics") -> None:
    """The animated stadium scene at the top of the Home page.

    title_html  may contain <span> to colour a word gold.
    stats       small boxes in the bottom-left corner: (label, value).
                Pass REAL numbers from the database only.
    """
    boxes = "".join(f"<div><small>{label}</small><strong>{value}</strong></div>"
                    for label, value in stats)
    st.html(
        '<section class="cb-stadium" aria-label="Animated cricket ground">'
        '<div class="lights"></div><div class="roof"></div><div class="stands"></div>'
        '<div class="horizon"></div><div class="outfield"></div>'
        '<div class="strip"></div><div class="crease"></div>'
        '<div class="wicket"><i class="s1"></i><i class="s2"></i><i class="s3"></i>'
        '<b class="bail b1"></b><b class="bail b2"></b></div>'
        '<div class="ball" aria-hidden="true"></div>'
        '<div class="topbar"><div class="brand">CRICBUZZ <span>LIVESTATS</span></div>'
        f'<div class="status">{status}</div></div>'
        f'<div class="copy"><div class="eyebrow">{eyebrow}</div>'
        f'<div class="title">{title_html}</div><div class="sub">{subtitle}</div>'
        f'<div class="pill">{boxes}</div></div>'
        '</section>'
    )


def page_header(title: str, subtitle: str = "", eyebrow: str = "") -> None:
    """Heading for every page except Home."""
    st.markdown(
        (f'<div class="cb-eyebrow">{eyebrow}</div>' if eyebrow else "")
        + f'<div class="cb-title">{title}</div>'
        + (f'<div class="cb-sub">{subtitle}</div>' if subtitle else ""),
        unsafe_allow_html=True,
    )


def section(title: str) -> None:
    """A smaller heading inside a page."""
    st.markdown(f'<div class="cb-section">{title}</div>', unsafe_allow_html=True)


def hero(value: str, label: str) -> None:
    """One big number, for pages that lead with a single figure."""
    st.markdown(
        f'<div class="cb-hero"><div class="cb-hero-value">{value}</div>'
        f'<div class="cb-hero-label">{label}</div></div>',
        unsafe_allow_html=True,
    )


def tiles(items: list[tuple[str, str, str]]) -> None:
    """A row of stat tiles: (label, value, note). Wraps on narrow screens."""
    cells = "".join(
        f'<div class="cb-tile"><div class="cb-tile-label">{label}</div>'
        f'<div class="cb-tile-value">{value}</div>'
        + (f'<div class="cb-tile-note">{note}</div>' if note else '<div class="cb-tile-note">&nbsp;</div>')
        + '</div>'
        for label, value, note in items
    )
    st.markdown(f'<div class="cb-tiles">{cells}</div>', unsafe_allow_html=True)


def card(title: str, body_html: str, dark: bool = False) -> None:
    """A rounded card. dark=True gives the outfield-green version."""
    css = "cb-card dark" if dark else "cb-card"
    st.markdown(f'<div class="{css}"><h4>{title}</h4>{body_html}</div>',
                unsafe_allow_html=True)


def rule() -> None:
    st.markdown('<hr class="cb-rule">', unsafe_allow_html=True)


def compact(n: float) -> str:
    """166275 -> '166.3K'. For tiles, where width is tight."""
    n = float(n)
    for limit, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if abs(n) >= limit:
            return f"{n / limit:.1f}{suffix}".replace(".0", "")
    return f"{n:,.0f}"