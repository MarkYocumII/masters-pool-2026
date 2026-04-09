"""Masters Pool 2026 — Live Scoring Leaderboard"""
import streamlit as st
import pandas as pd
import requests
import re
import unicodedata
from datetime import datetime, timezone

st.set_page_config(
    page_title="Masters Pool 2026",
    page_icon="⛳",
    layout="centered",
)

# Auto-refresh every 3 minutes
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=180_000, key="datarefresh")
except ImportError:
    pass  # works without it, just no auto-refresh


# === SCORING RULES ===
def points_for_position(pos, status=None):
    """Convert tournament position to pool points."""
    if status and status.upper() in ("CUT", "MC", "WD", "DQ"):
        return 0
    if pos is None:
        return 0
    if pos == 1: return 90
    if pos == 2: return 65
    if pos == 3: return 60
    if pos == 4: return 55
    if pos == 5: return 50
    if pos == 6: return 45
    if pos == 7: return 40
    if pos == 8: return 35
    if pos == 9: return 30
    if pos == 10: return 25
    if 11 <= pos <= 15: return 20
    if 16 <= pos <= 20: return 15
    if 21 <= pos <= 25: return 10
    if 26 <= pos <= 30: return 5
    if pos >= 31: return 2
    return 0


# === NAME NORMALIZATION ===
def norm(name):
    """Normalize a golfer name for matching."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    s = s.lower().strip()
    s = re.sub(r"[^a-z\s]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


# Manual aliases for known mismatches
ALIASES = {
    "felletwood tommy": "tommy fleetwood",
    "sungjae im": "sung jae im",
    "neegaard petersen rasmus": "rasmus neergaard petersen",
    "potgeiter aldrich": "aldrich potgieter",
    "im sungjae": "sung jae im",
    "cameron cam smith": "cameron smith",
    "jose maria olazabal": "jose maria olazabal",
    "fifa laopakdee": "pongsapak laopakdee",
    "johnny keefer": "john keefer",
}


def resolve_name(name):
    """Normalize and apply aliases."""
    n = norm(name)
    return ALIASES.get(n, n)


# === FETCH LIVE LEADERBOARD ===
@st.cache_data(ttl=180)
def fetch_leaderboard():
    """Fetch live Masters leaderboard from ESPN API."""
    url = "https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return None, str(e)

    golfers = []
    try:
        events = data.get("events", [])
        if not events:
            return None, "No events found in ESPN data"

        # Find the Masters event
        event = None
        for ev in events:
            if "masters" in ev.get("name", "").lower() or "augusta" in ev.get("name", "").lower():
                event = ev
                break
        if event is None:
            event = events[0]  # fallback to first event

        event_name = event.get("name", "Unknown Event")
        competitions = event.get("competitions", [])
        if not competitions:
            return None, f"No competitions in event: {event_name}"

        competitors = competitions[0].get("competitors", [])
        for idx, comp in enumerate(competitors):
            athlete = comp.get("athlete", {})
            name = athlete.get("displayName", "Unknown")

            # ESPN returns competitors sorted by leaderboard position
            # 'order' field = leaderboard rank, 'score' = score to par string
            order = comp.get("order", idx + 1)
            score_raw = comp.get("score", "-")
            score_display = str(score_raw) if score_raw else "-"

            # Check for status (CUT, WD, DQ) — may be in status dict or sortOrder
            status_info = comp.get("status", {})
            status_type = status_info.get("type", {}).get("name", "") if isinstance(status_info, dict) else ""

            status = None
            pos_int = order  # use ESPN sort order as position proxy

            if status_type.upper() in ("CUT", "MC", "WD", "DQ"):
                status = status_type.upper()
                pos_int = None

            # Determine "thru" from linescores
            thru = "-"
            linescores = comp.get("linescores", [])
            if linescores:
                current_round = linescores[0] if linescores else {}
                hole_scores = current_round.get("linescores", [])
                if hole_scores:
                    thru = len(hole_scores)
                    if thru >= 18:
                        thru = "F"

            # Build position display string
            pos_str = str(order) if pos_int else (status or "-")

            golfers.append({
                "name": name,
                "name_norm": resolve_name(name),
                "pos_str": pos_str,
                "pos_int": pos_int,
                "status": status,
                "score": score_display,
                "thru": thru,
                "points": points_for_position(pos_int, status),
            })
    except Exception as e:
        return None, f"Parse error: {e}"

    return golfers, event_name


# === LOAD ROSTERS ===
@st.cache_data
def load_rosters():
    """Load the pool rosters CSV."""
    df = pd.read_csv("rosters.csv", encoding="utf-8")
    df["Golfer_Norm"] = df["Golfer"].apply(resolve_name)
    return df


# === MAIN APP ===
def main():
    st.markdown("# ⛳ Masters Pool 2026")
    st.markdown("##### Live Scoring Leaderboard — 152 Participants")

    rosters = load_rosters()
    golfers_live, event_info = fetch_leaderboard()

    if golfers_live is None:
        st.error(f"Could not fetch leaderboard: {event_info}")
        st.info("The leaderboard will appear once tournament data is available from ESPN.")
        return

    st.caption(f"Event: **{event_info}** | Last updated: {datetime.now(timezone.utc).strftime('%I:%M %p UTC')} | Auto-refreshes every 3 min")

    # Build lookup: norm_name -> golfer data
    live_lookup = {}
    for g in golfers_live:
        live_lookup[g["name_norm"]] = g

    # Fuzzy fallback for unmatched names
    live_names = list(live_lookup.keys())

    def best_match(roster_norm):
        """Try exact match first, then fuzzy."""
        if roster_norm in live_lookup:
            return live_lookup[roster_norm]
        # Simple fuzzy: check if all parts of one name appear in the other
        roster_parts = set(roster_norm.split())
        for ln in live_names:
            live_parts = set(ln.split())
            if len(roster_parts & live_parts) >= 2:
                return live_lookup[ln]
            # Last name match
            if roster_norm.split()[-1] == ln.split()[-1] and len(roster_norm.split()[-1]) > 3:
                return live_lookup[ln]
        return None

    # Score each participant
    participant_scores = []
    participant_details = {}

    for participant, group in rosters.groupby("Participant"):
        total_pts = 0
        golfer_details = []
        for _, row in group.iterrows():
            match = best_match(row["Golfer_Norm"])
            if match:
                pts = match["points"]
                golfer_details.append({
                    "Golfer": row["Golfer"],
                    "Price": f"${row['Price']:.2f}",
                    "Position": match["pos_str"],
                    "Score": match["score"],
                    "Thru": match["thru"] if match["thru"] else "-",
                    "Points": pts,
                })
            else:
                golfer_details.append({
                    "Golfer": row["Golfer"],
                    "Price": f"${row['Price']:.2f}",
                    "Position": "-",
                    "Score": "-",
                    "Thru": "-",
                    "Points": 0,
                })
            total_pts += golfer_details[-1]["Points"]

        participant_scores.append({
            "Participant": participant,
            "Points": total_pts,
            "Golfers": len(group),
        })
        participant_details[participant] = sorted(golfer_details, key=lambda x: x["Points"], reverse=True)

    # Sort by points descending
    df_scores = pd.DataFrame(participant_scores).sort_values("Points", ascending=False).reset_index(drop=True)
    df_scores.index = df_scores.index + 1
    df_scores.index.name = "Rank"

    # Main leaderboard
    st.markdown("### Pool Leaderboard")

    # Search/filter
    search = st.text_input("Search participant:", "", placeholder="Type a name...")
    if search:
        mask = df_scores["Participant"].str.lower().str.contains(search.lower())
        display_df = df_scores[mask]
    else:
        display_df = df_scores

    st.dataframe(
        display_df,
        use_container_width=True,
        height=min(700, 35 * len(display_df) + 38),
    )

    # Tournament leaderboard (top 20)
    st.markdown("### Masters Leaderboard (Top 20)")
    top_golfers = sorted(golfers_live, key=lambda x: (x["pos_int"] if x["pos_int"] else 999))[:20]
    top_df = pd.DataFrame([{
        "Pos": g["pos_str"],
        "Golfer": g["name"],
        "Score": g["score"],
        "Thru": g["thru"] if g["thru"] else "-",
        "Pool Pts": g["points"],
    } for g in top_golfers])
    st.dataframe(top_df, use_container_width=True, hide_index=True)

    # Drill-down: view a participant's roster
    st.markdown("### View Roster Detail")
    selected = st.selectbox(
        "Select a participant:",
        df_scores["Participant"].tolist(),
    )
    if selected and selected in participant_details:
        detail_df = pd.DataFrame(participant_details[selected])
        total = detail_df["Points"].sum()
        st.markdown(f"**{selected}** — {len(detail_df)} golfers — **{total} points**")
        st.dataframe(detail_df, use_container_width=True, hide_index=True)

    # Footer
    st.markdown("---")
    st.caption("Masters Pool 2026 | Scoring: W=90, 2nd=65, 3rd=60, 4th=55, 5th=50, 6-10=45-25, 11-15=20, 16-20=15, 21-25=10, 26-30=5, 31+=2, MC=0")


if __name__ == "__main__":
    main()
