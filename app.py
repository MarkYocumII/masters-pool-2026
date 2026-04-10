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


# === PROJECTED CUT LINE ===
# Update this as ESPN updates the projected cut. Set to None before cut is projected.
PROJECTED_CUT = 3  # +3 means golfers at +4 or worse are projected to miss the cut


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

            thru = None  # None = not started, will be Int64 NA
            tee_time_str = ""
            linescores = comp.get("linescores", [])
            if linescores:
                current_round = linescores[-1]
                hole_scores = current_round.get("linescores", [])
                if hole_scores:
                    thru = len(hole_scores)
                    if thru >= 18:
                        thru = 18  # Styler will format as F
                else:
                    # Not started — extract tee time for display
                    stats = current_round.get("statistics", {})
                    cats = stats.get("categories", []) if stats else []
                    for cat in cats:
                        for s in cat.get("stats", []):
                            dv = s.get("displayValue", "")
                            if ("AM" in dv or "PM" in dv or "PDT" in dv or
                                "PST" in dv or "EDT" in dv or "EST" in dv):
                                try:
                                    # Determine timezone offset to convert to EST/EDT
                                    offset_hours = 0
                                    if " PDT " in dv:
                                        offset_hours = 3  # PDT -> EDT = +3
                                    elif " PST " in dv:
                                        offset_hours = 3  # PST -> EST = +3
                                    # EDT/EST already Eastern, no offset
                                    cleaned = dv
                                    for tz in (" PDT ", " PST ", " EDT ", " EST "):
                                        cleaned = cleaned.replace(tz, " ")
                                    dt = __import__("datetime").datetime.strptime(
                                        cleaned, "%a %b %d %H:%M:%S %Y")
                                    dt = dt + __import__("datetime").timedelta(hours=offset_hours)
                                    h = dt.hour
                                    ampm = "AM" if h < 12 else "PM"
                                    if h > 12: h -= 12
                                    if h == 0: h = 12
                                    tee_time_str = f"T{h}:{dt.minute:02d} {ampm}"
                                except Exception:
                                    pass

            # Today's round score
            today = tee_time_str if tee_time_str else "-"
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
                "tee_time": tee_time_str,
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
            # Check if projected to miss cut
            score_num = score_to_int(g["score"])
            proj_mc = False
            if PROJECTED_CUT is not None and score_num is not None and score_num > PROJECTED_CUT:
                proj_mc = True
            pts = 0 if proj_mc else points_for_position(g["pos_int"], None)
            golfers.append({
                "name": g["name"],
                "name_norm": g["name_norm"],
                "pos_str": g["pos_str"],
                "pos_int": g["pos_int"],
                "status": None,
                "score": g["score"],
                "today": g["today"],
                "thru": g["thru"],
                "tee_time": g.get("tee_time", ""),
                "points": pts,
                "proj_mc": proj_mc,
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
                "tee_time": g.get("tee_time", ""),
                "points": 0,
                "proj_mc": True,
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


def score_to_int(score_str):
    """Convert golf score to integer. E=0, -=None, -5=-5, +3=3.
    Streamlit sorts integers correctly in both directions."""
    s = str(score_str).strip()
    if s == "E":
        return 0
    if s == "-" or s == "" or s == "None":
        return None
    try:
        return int(s)
    except ValueError:
        return None


def force_numeric_cols(df):
    """Force Score, Today, Thru, Points, and Pool Pts columns to numeric dtype
    so Streamlit sorts them as numbers, not strings."""
    for col in ["Score", "Points", "Pool Pts", "Own %", "Pts/$"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    if "Thru" in df.columns:
        df["Thru"] = pd.to_numeric(df["Thru"], errors="coerce").astype("Int64")
    return df


def golf_display_df(df):
    """Prepare a dataframe for display: duplicate Score/Today as hidden numeric
    sort columns, then replace the visible ones with golf-formatted strings.
    Use st.dataframe column_order to hide the sort columns."""
    out = df.copy()
    for col in ["Score", "Today"]:
        if col not in out.columns:
            continue
        sort_col = f"_{col}_sort"
        out[sort_col] = out[col]  # keep numeric copy
        # Format display: 0 -> E, NaN -> -, negative stays, positive gets +
        def fmt(v):
            if pd.isna(v):
                return "-"
            n = int(v)
            if n == 0:
                return "E"
            if n > 0:
                return f"+{n}"
            return str(n)
        out[col] = out[col].apply(fmt)
    if "Thru" in out.columns:
        sort_col = "_Thru_sort"
        out[sort_col] = out["Thru"]
        out["Thru"] = out["Thru"].apply(lambda v: "F" if not pd.isna(v) and int(v) >= 18 else ("-" if pd.isna(v) else str(int(v))))
    return out


def _fmt_golf_score(v):
    """Format a single golf score value for display."""
    if pd.isna(v):
        return "-"
    n = int(v)
    if n == 0:
        return "E"
    if n > 0:
        return f"+{n}"
    return str(n)


def _fmt_thru(v):
    """Format Thru value."""
    if pd.isna(v):
        return "-"
    try:
        n = int(v)
        if n >= 18:
            return "F"
        return str(n)
    except (ValueError, TypeError):
        return str(v)  # tee time string passes through


def _fmt_own_pct(v):
    """Format Own % value."""
    if pd.isna(v):
        return "-"
    return f"{int(v)}%"


def golf_dataframe(df, height=None, **kwargs):
    """Render a golf table with proper golf formatting."""
    display = df.copy()
    display = display[[c for c in display.columns if not c.startswith("_")]]

    # Force numeric columns for sorting (NOT Today — it has tee time strings)
    for col in ["Score", "Points", "Pool Pts", "Own %", "Pts/$"]:
        if col in display.columns:
            display[col] = pd.to_numeric(display[col], errors="coerce").astype("Int64")

    # Today: format scores nicely but keep as string (may contain tee times)
    if "Today" in display.columns:
        def _fmt_today_str(v):
            s = str(v).strip()
            if s.startswith("T") and ("AM" in s or "PM" in s):
                return s  # tee time, pass through
            if s == "-" or s == "" or s == "None":
                return "-"
            if s == "E":
                return "E"
            try:
                n = int(s)
                if n == 0: return "E"
                if n > 0: return f"+{n}"
                return str(n)
            except ValueError:
                return s
        display["Today"] = display["Today"].apply(_fmt_today_str)

    # Thru: convert to numeric, then format. Tee times handled below.
    if "Thru" in display.columns and "tee_time" not in display.columns:
        display["Thru"] = pd.to_numeric(display["Thru"], errors="coerce").astype("Int64")

    # If tee_time column exists, merge into Thru display then drop
    if "tee_time" in display.columns:
        display["Thru"] = pd.to_numeric(display["Thru"], errors="coerce").astype("Int64")
        # Build the formatted Thru column as strings
        def _merge_thru(row):
            if pd.isna(row["Thru"]):
                tt = row.get("tee_time", "")
                return tt if tt else "-"
            n = int(row["Thru"])
            if n >= 18:
                return "F"
            return str(n)
        display["Thru"] = display.apply(_merge_thru, axis=1)
        display = display.drop(columns=["tee_time"])

    # Build Styler format dict
    fmt = {}
    for col in display.columns:
        if col == "Score":
            fmt[col] = _fmt_golf_score
        # Today is pre-formatted as string (scores + tee times), skip Styler
        elif col == "Thru" and display["Thru"].dtype != object:
            # Only format if still numeric (no tee times merged)
            fmt[col] = _fmt_thru
        elif col == "Own %":
            fmt[col] = _fmt_own_pct

    # Apply red shading to rows projected to miss the cut
    proj_mc_mask = None
    if "_proj_mc" in display.columns:
        proj_mc_mask = display["_proj_mc"].fillna(False)
        display = display.drop(columns=["_proj_mc"])

    styled = display.style.format(fmt, na_rep="-", precision=0)

    if proj_mc_mask is not None and proj_mc_mask.any():
        def _highlight_mc(row):
            if proj_mc_mask.iloc[row.name]:
                return ["background-color: #ffcccc"] * len(row)
            return [""] * len(row)
        styled = styled.apply(_highlight_mc, axis=1)

    # Build column_config for right-alignment
    col_config = {}
    for col in display.columns:
        if col in ("Today", "Thru", "Score", "Points", "Pool Pts", "Own %", "Pts/$", "Pos"):
            col_config[col] = st.column_config.TextColumn(col, alignment="right")

    kw = {**kwargs}
    if height:
        kw["height"] = height
    st.dataframe(styled, column_config=col_config, **kw)


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
                    "_proj_mc": match.get("proj_mc", False),
                    "Score": score_to_int(match["score"]),
                    "Today": match.get("today", "-"),
                    "Thru": match["thru"],
                    "tee_time": match.get("tee_time", ""),
                    "Points": pts,
                })
            else:
                golfer_details.append({
                    "Golfer": row["Golfer"],
                    "Price": f"${row['Price']:.2f}",
                    "Position": "-",
                    "_pos_sort": 999,
                    "_proj_mc": True,
                    "Score": score_to_int("-"),
                    "Today": "-",
                    "Thru": None,
                    "tee_time": "",
                    "Points": 0,
                })
            total_pts += golfer_details[-1]["Points"]

        participant_scores.append({
            "Participant": participant,
            "Points": total_pts,
            "Golfers": len(group),
        })
        participant_details[participant] = sorted(golfer_details, key=lambda x: (-x["Points"], x["Score"] if x["Score"] is not None else 999, x["_pos_sort"]))

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
        # _proj_mc handled inside golf_dataframe
        detail_df = force_numeric_cols(detail_df)
        total = detail_df["Points"].sum()
        rank = participant_list.index(selected) + 1
        st.markdown(f"### 🔎 {selected}")
        st.markdown(f"**Rank #{rank}** — {len(detail_df)} golfers — **{total} points**")
        golf_dataframe(detail_df, use_container_width=True, hide_index=True)

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
                    "Score": score_to_int(g["score"]),
                    "Pool Pts": g["points"],
                    "Price": f"${price:.2f}",
                    "Pts/$": round(g["points"] / price, 1),
                })
                seen.add(g["name"])
    if value_picks:
        value_picks.sort(key=lambda x: x["Pts/$"], reverse=True)
        vp_df = force_numeric_cols(pd.DataFrame(value_picks[:12]))
        golf_dataframe(vp_df, use_container_width=True, hide_index=True)

    # ============================================
    # MASTERS LEADERBOARD + OWNERSHIP (combined)
    # ============================================
    st.markdown("### ⛳ Masters Leaderboard & Ownership (Full Field)")
    if PROJECTED_CUT is not None:
        st.caption(f"Projected cut: +{PROJECTED_CUT}. Golfers at +{PROJECTED_CUT + 1} or worse highlighted in red (0 pool points).")
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
            "_proj_mc": g.get("proj_mc", False),
            "Pos": g["pos_str"],
            "Golfer": g["name"],
            "Score": score_to_int(g["score"]),
            "Today": g.get("today", "-"),
            "Thru": g["thru"],
            "tee_time": g.get("tee_time", ""),
            "Pool Pts": g["points"],
            "Rostered": f"{count}/154",
            "Own %": round(count/154*100),
        })
    combined_df = pd.DataFrame(combined_rows)
    combined_df = combined_df.sort_values(["#"]).drop(columns=["#"]).reset_index(drop=True)
    combined_df = force_numeric_cols(combined_df)
    golf_dataframe(combined_df, use_container_width=True, hide_index=True)

    # Footer
    st.markdown("---")
    st.caption("Masters Pool 2026 | Scoring: W=90, 2nd=65, 3rd=60, 4th=55, 5th=50, 6-10=45-25, 11-15=20, 16-20=15, 21-25=10, 26-30=5, 31+=2, MC=0")
    st.caption("Data: ESPN | Built with Streamlit | Auto-refreshes every 3 minutes")


if __name__ == "__main__":
    main()
