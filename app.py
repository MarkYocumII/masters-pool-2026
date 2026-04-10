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
    pass


# === SCORING RULES ===
def points_for_position(pos, status=None):
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
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    s = s.lower().strip()
    s = re.sub(r"[^a-z\s]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


ALIASES = {
    # Typos in roster spreadsheet
    "tommy felletwood": "tommy fleetwood",
    "felletwood tommy": "tommy fleetwood",
    "aldrich potgeiter": "aldrich potgieter",
    # Højgaard -> hjgaard after NFKD normalization (ø drops the o)
    "rasmus hojgaard": "rasmus hjgaard",
    "nicolai hojgaard": "nicolai hjgaard",
    # Neergaard spelling variants
    "rasmus neegaardpetersen": "rasmus neergaardpetersen",
    "neegaard petersen rasmus": "rasmus neergaardpetersen",
    # Sungjae Im variants
    "sungjae im": "sung jae im",
    "im sungjae": "sung jae im",
    # Other known mismatches
    "fifa laopakdee": "pongsapak laopakdee",
    "johnny keefer": "john keefer",
    "cameron cam smith": "cameron smith",
    "jose maria olazabal": "jose maria olazabal",
}


def resolve_name(name):
    n = norm(name)
    return ALIASES.get(n, n)


# === FETCH LIVE LEADERBOARD ===
@st.cache_data(ttl=180)
def fetch_leaderboard():
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

        event = None
        for ev in events:
            if "masters" in ev.get("name", "").lower() or "augusta" in ev.get("name", "").lower():
                event = ev
                break
        if event is None:
            event = events[0]

        event_name = event.get("name", "Unknown Event")
        competitions = event.get("competitions", [])
        if not competitions:
            return None, f"No competitions in event: {event_name}"

        competitors = competitions[0].get("competitors", [])

        # First pass: collect raw data sorted by ESPN order
        raw_golfers = []
        for idx, comp in enumerate(competitors):
            athlete = comp.get("athlete", {})
            name = athlete.get("displayName", "Unknown")
            order = comp.get("order", idx + 1)
            score_raw = comp.get("score", "-")
            score_display = str(score_raw) if score_raw else "-"

            status_info = comp.get("status", {})
            status_type = status_info.get("type", {}).get("name", "") if isinstance(status_info, dict) else ""

            status = None
            if status_type.upper() in ("CUT", "MC", "WD", "DQ"):
                status = status_type.upper()

            thru = "-"
            linescores = comp.get("linescores", [])
            if linescores:
                # Find the current/latest round: last round with hole data
                current_round = linescores[-1]  # latest round entry
                hole_scores = current_round.get("linescores", [])
                if hole_scores:
                    thru = len(hole_scores)
                    if thru >= 18:
                        thru = "F"
                elif len(linescores) >= 2:
                    # Latest round has no holes yet — player hasn't started
                    # Check if prior round is complete
                    prev_round = linescores[-2]
                    prev_holes = prev_round.get("linescores", [])
                    if prev_holes and len(prev_holes) >= 18:
                        thru = "-"  # finished prior round, not started current

            # Today's round score
            today = "-"
            if linescores and len(linescores) >= 1:
                latest = linescores[-1]
                today_val = latest.get("displayValue", "-")
                if today_val and today_val != "-":
                    today = today_val

            raw_golfers.append({
                "name": name,
                "name_norm": resolve_name(name),
                "order": order,
                "status": status,
                "score": score_display,
                "today": today,
                "thru": thru,
            })

        # Second pass: compute tied positions
        # Golfers with the same score get the same position (e.g. T1, T1, 3, T4, T4, 6...)
        # Group active golfers by score, assign position = first index in that group
        active = [g for g in raw_golfers if g["status"] is None]
        inactive = [g for g in raw_golfers if g["status"] is not None]

        # Active golfers are already sorted by ESPN order; group consecutive same-score runs
        pos = 1
        i = 0
        while i < len(active):
            j = i
            while j < len(active) and active[j]["score"] == active[i]["score"]:
                j += 1
            tied = j - i > 1
            for k in range(i, j):
                active[k]["pos_int"] = pos
                # Zero-pad so string sort = numeric sort (T01, T02, ... T14)
                active[k]["pos_str"] = f"T{pos:02d}" if tied else f"{pos:02d}"
            pos = j + 1
            i = j

        for g in active:
            golfers.append({
                "name": g["name"],
                "name_norm": g["name_norm"],
                "pos_str": g["pos_str"],
                "pos_int": g["pos_int"],
                "status": None,
                "score": g["score"],
                "today": g["today"],
                "thru": g["thru"],
                "points": points_for_position(g["pos_int"], None),
            })

        for g in inactive:
            golfers.append({
                "name": g["name"],
                "name_norm": g["name_norm"],
                "pos_str": g["status"] or "-",
                "pos_int": None,
                "status": g["status"],
                "score": g["score"],
                "today": g.get("today", "-"),
                "thru": g["thru"],
                "points": 0,
            })
    except Exception as e:
        return None, f"Parse error: {e}"

    return golfers, event_name


def score_sort_val(score_str):
    """Convert score string to numeric for proper sorting: -5 < E(0) < +3."""
    s = str(score_str).strip()
    if s == "E": return 0
    if s == "-" or s == "": return 999
    try:
        return int(s)
    except ValueError:
        return 999


# === LOAD ROSTERS ===
@st.cache_data(ttl=300)
def load_rosters():
    df = pd.read_csv("rosters.csv", encoding="utf-8")
    df["Golfer_Norm"] = df["Golfer"].apply(resolve_name)
    return df


# === COMPUTE SCORES ===
def compute_pool_scores(rosters, golfers_live):
    live_lookup = {}
    for g in golfers_live:
        live_lookup[g["name_norm"]] = g

    live_names = list(live_lookup.keys())

    def best_match(roster_norm):
        if roster_norm in live_lookup:
            return live_lookup[roster_norm]
        roster_parts = set(roster_norm.split())
        # Pass 1: 2+ word overlap
        for ln in live_names:
            live_parts = set(ln.split())
            if len(roster_parts & live_parts) >= 2:
                return live_lookup[ln]
        # Pass 2: last name exact match (>3 chars)
        for ln in live_names:
            if roster_norm.split()[-1] == ln.split()[-1] and len(roster_norm.split()[-1]) > 3:
                return live_lookup[ln]
        # Pass 3: first name match + last name starts with same 3 chars (catches hojgaard/hjgaard)
        for ln in live_names:
            r_parts = roster_norm.split()
            l_parts = ln.split()
            if len(r_parts) >= 2 and len(l_parts) >= 2:
                if r_parts[0] == l_parts[0] and r_parts[-1][:3] == l_parts[-1][:3]:
                    return live_lookup[ln]
        return None

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
                    "_pos_sort": match["pos_int"] if match["pos_int"] else 999,
                    "Score": match["score"],
                    "Today": match.get("today", "-"),
                    "Thru": match["thru"] if match["thru"] else "-",
                    "Points": pts,
                })
            else:
                golfer_details.append({
                    "Golfer": row["Golfer"],
                    "Price": f"${row['Price']:.2f}",
                    "Position": "-",
                    "_pos_sort": 999,
                    "Score": "-",
                    "Today": "-",
                    "Thru": "-",
                    "Points": 0,
                })
            total_pts += golfer_details[-1]["Points"]

        participant_scores.append({
            "Participant": participant,
            "Points": total_pts,
            "Golfers": len(group),
        })
        participant_details[participant] = sorted(golfer_details, key=lambda x: (-x["Points"], score_sort_val(x["Score"]), x["_pos_sort"]))

    df_scores = pd.DataFrame(participant_scores).sort_values("Points", ascending=False).reset_index(drop=True)
    df_scores.index = df_scores.index + 1
    df_scores.index.name = "Rank"

    return df_scores, participant_details


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

    st.caption(f"**{event_info}** | Updated: {datetime.now(timezone.utc).strftime('%I:%M %p UTC')} | Auto-refreshes every 3 min")

    df_scores, participant_details = compute_pool_scores(rosters, golfers_live)

    # ============================================
    # TOP 3 PODIUM
    # ============================================
    if len(df_scores) >= 3:
        st.markdown("### Podium")
        cols = st.columns(3)
        medals = ["🥇", "🥈", "🥉"]
        for i, col in enumerate(cols):
            row = df_scores.iloc[i]
            col.metric(
                label=f"{medals[i]} {row['Participant']}",
                value=f"{row['Points']} pts",
                delta=f"{row['Golfers']} golfers",
            )
    st.markdown("")

    # ============================================
    # FULL POOL LEADERBOARD + ROSTER DETAIL (linked)
    # ============================================
    st.markdown("### 📊 Full Pool Leaderboard")
    st.caption("Select a participant to view their roster below")

    participant_list = df_scores["Participant"].tolist()

    selected = st.selectbox(
        "🔍 Find participant:",
        ["-- Show All --"] + participant_list,
    )

    if selected and selected != "-- Show All --":
        # Highlight selected in leaderboard
        display_df = df_scores[df_scores["Participant"] == selected]
    else:
        display_df = df_scores

    st.dataframe(
        display_df if selected == "-- Show All --" or not selected else df_scores,
        use_container_width=True,
        height=min(700, 35 * min(len(df_scores), 20) + 38),
    )

    # Show roster detail for selected participant
    if selected and selected != "-- Show All --" and selected in participant_details:
        st.markdown(f"---")
        detail_df = pd.DataFrame(participant_details[selected]).drop(columns=["_pos_sort"], errors="ignore")
        total = detail_df["Points"].sum()
        rank = participant_list.index(selected) + 1
        st.markdown(f"### 🔎 {selected}")
        st.markdown(f"**Rank #{rank}** — {len(detail_df)} golfers — **{total} points**")
        st.dataframe(detail_df, use_container_width=True, hide_index=True)

    # ============================================
    # BEST VALUE PICKS (most points per dollar spent)
    # ============================================
    st.markdown("### 💰 Best Value Picks (Points per Dollar)")
    value_picks = []
    seen = set()
    for g in golfers_live:
        if g["points"] <= 0:
            continue
        matches = rosters[rosters["Golfer_Norm"] == g["name_norm"]]
        if matches.empty:
            for _, r in rosters.iterrows():
                rp = set(r["Golfer_Norm"].split())
                gp = set(g["name_norm"].split())
                if len(rp & gp) >= 2:
                    matches = rosters[rosters["Golfer_Norm"] == r["Golfer_Norm"]]
                    break
        if not matches.empty and g["name"] not in seen:
            price = matches.iloc[0]["Price"]
            if price > 0:
                value_picks.append({
                    "Golfer": g["name"],
                    "Score": g["score"],
                    "Pool Pts": g["points"],
                    "Price": f"${price:.2f}",
                    "Pts/$": round(g["points"] / price, 1),
                })
                seen.add(g["name"])
    if value_picks:
        value_picks.sort(key=lambda x: x["Pts/$"], reverse=True)
        st.dataframe(pd.DataFrame(value_picks[:12]), use_container_width=True, hide_index=True)

    # ============================================
    # MASTERS LEADERBOARD + OWNERSHIP (combined)
    # ============================================
    st.markdown("### ⛳ Masters Leaderboard & Ownership (Full Field)")
    top_golfers = sorted(golfers_live, key=lambda x: (x["pos_int"] if x["pos_int"] else 999))
    combined_rows = []
    for g in top_golfers:
        gn = g["name_norm"]
        count = 0
        for _, r in rosters.iterrows():
            if r["Golfer_Norm"] == gn:
                count += 1
                continue
            rp = set(r["Golfer_Norm"].split())
            gp = set(gn.split())
            if len(rp & gp) >= 2:
                count += 1
        combined_rows.append({
            "#": g["pos_int"] if g["pos_int"] else 999,
            "Pos": g["pos_str"],
            "Golfer": g["name"],
            "Score": g["score"],
            "Today": g.get("today", "-"),
            "Thru": g["thru"] if g["thru"] else "-",
            "Pool Pts": g["points"],
            "Rostered": f"{count}/154",
            "Own %": f"{count/154*100:.0f}%",
        })
    combined_df = pd.DataFrame(combined_rows)
    combined_df["_score_sort"] = combined_df["Score"].apply(score_sort_val)
    combined_df = combined_df.sort_values(["_score_sort", "#"]).drop(columns=["#", "_score_sort"]).reset_index(drop=True)
    st.dataframe(combined_df, use_container_width=True, hide_index=True)

    # Footer
    st.markdown("---")
    st.caption("Masters Pool 2026 | Scoring: W=90, 2nd=65, 3rd=60, 4th=55, 5th=50, 6-10=45-25, 11-15=20, 16-20=15, 21-25=10, 26-30=5, 31+=2, MC=0")
    st.caption("Data: ESPN | Built with Streamlit | Auto-refreshes every 3 minutes")


if __name__ == "__main__":
    main()
