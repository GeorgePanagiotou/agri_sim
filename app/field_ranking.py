"""Interactive field-history matching and preference scoring for the Evia pilot."""
import pandas as pd
import streamlit as st
from field_profiles import save_widget

from agrisim.config import REF
from agrisim.decision_engine.ranking import COLUMNS, rank_rotations

LABELS = ("Soil cover", "Water efficiency", "Feed", "Bee forage", "Market")


def render_ranking(row, names, field, profile):
    phases = pd.read_csv(REF / "rotations.csv").sort_values("year")
    crops = pd.read_csv(REF / "crops.csv").set_index("crop_id").name.to_dict()
    st.subheader("Field history")
    st.caption("Enter consecutive main crops, most recent first. For a catch crop, start with the crop harvested immediately before it. Changes are saved automatically for the selected field and growing season.")
    history = []
    for offset, col in enumerate(st.columns(3)):
        setting = f"prior:{row.season}:{offset}"
        key = f"prior_{field}_{row.season}_{offset}"
        if key not in st.session_state:
            st.session_state[key] = profile.get(setting)
        history.append(col.selectbox(["Previous crop", "Two crops back", "Three crops back"][offset],
            [None, *crops, "other"], format_func=lambda c: crops.get(c, "Other crop" if c else "Unknown"),
            key=key, on_change=save_widget, args=(field,setting,key)))
    candidates = []
    for sid, group in phases.groupby("strategy_id"):
        sequence = group.crop_id.tolist()
        matched, excluded = [], []
        for i, phase in enumerate(group.itertuples()):
            catch = phase.catch_crop_id == row.crop_id
            if not catch and (phase.crop_id != row.crop_id or
                    (row.crop_id == "sainfoin" and sequence[i-1] == "sainfoin")):
                continue
            previous = [sequence[(i + int(catch) - j - 1) % len(sequence)] for j in range(len(history))]
            phase_label = f"Year {phase.year}" + (" catch crop" if catch else "")
            conflicts = [f"{j+1} crop(s) back expected {crops.get(p,p)}" for j,p in enumerate(previous)
                         if history[j] is not None and history[j] != p]
            if conflicts:
                excluded.append(phase_label + " · " + ", ".join(conflicts))
            else:
                matched.append(phase_label + " after " + crops.get(previous[0],previous[0]))
        if matched:
            candidates.append(dict(strategy_id=sid, candidate_crop=row.crop_id, rotation=" → ".join(crops[c] for c in sequence),
                                   matches="; ".join(matched)))
        elif excluded:
            st.caption(f"{sid} · {names[sid]} excluded: " + "; ".join(excluded))
    if not candidates:
        st.info("No phase in the four draft rotations matches this crop and field history.")
        return
    st.subheader("Preference ranking")
    st.caption("Score each strategy from 0 (least preferred) to 5 (most preferred). Each criterion contributes one fifth. Blank scores are missing. Scores are saved automatically for this field across seasons.")
    for option in candidates:
        sid = option["strategy_id"]
        with st.expander(f"{sid} · {names[sid]} — enter scores"):
            st.write(option["rotation"])
            st.caption(option["matches"])
            for col, criterion, title in zip(st.columns(5), COLUMNS, LABELS):
                key = f"{sid}_{criterion}"
                widget = f"score_{field}_{key}"
                if widget not in st.session_state:
                    st.session_state[widget] = int(profile[key]) if profile.get(key) is not None else None
                option[criterion] = col.number_input(title, min_value=0, max_value=5, step=1,
                                                     value=None, key=widget, on_change=save_widget, args=(field,key,widget))
    ranked = rank_rotations(pd.DataFrame(candidates))
    if not any(history):
        st.info("These matches are conditional until you enter field history.")
    if ranked.priority_rank.isna().any():
        st.caption("Ranks compare the fully scored matches. Completing another strategy can change their order.")
    for r in ranked.itertuples():
        title = f"{r.strategy_id} · {names[r.strategy_id]}"
        if pd.isna(r.priority_rank):
            missing = [name for c,name in zip(COLUMNS,LABELS) if pd.isna(getattr(r,c))]
            st.markdown(f"**{title} · awaiting scores**")
            st.write("Missing: " + ", ".join(missing))
        else:
            st.markdown(f"**Rank {int(r.priority_rank)} · {title} · {r.relative_priority_score:.1f}/5**")
            st.write(" + ".join(f"{name} {int(getattr(r,c))}" for c,name in zip(COLUMNS,LABELS)) +
                     f" = {int(round(5*r.relative_priority_score))} points across 5 criteria.")
        st.caption(r.matches)
    return ranked
