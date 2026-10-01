import pandas as pd
import streamlit as st

from components import charts, common

common.page_setup("Model health")
st.caption(
    "How good are the projections? A rolling backtest on last season (the model only sees data from "
    "before each gameweek) and live tracking of this season's pre-deadline projections."
)

summ = common.output("backtest_summary.json")
if summ is None:
    st.info("No backtest yet. Run `mm backtest` (about 2 minutes) or wait for the scheduled job.")
else:
    st.subheader(f"Backtest · {summ['season']} · {len(summ['gws'])} gameweeks")
    met = pd.DataFrame(summ["metrics"])
    sub = st.radio("Players", list(dict.fromkeys(met["subset"])), horizontal=True)
    m = met[met["subset"] == sub].drop(columns=["subset"])
    st.dataframe(
        m,
        hide_index=True,
        width="stretch",
        column_config={
            "predictor": "Predictor",
            "n": "Player-GWs",
            "rmse": st.column_config.NumberColumn("RMSE", format="%.3f"),
            "mae": st.column_config.NumberColumn("MAE", format="%.3f"),
            "bias": st.column_config.NumberColumn("Bias", format="%+.3f"),
            "spearman_within_pos": st.column_config.NumberColumn(
                "Rank correlation (within position)", format="%.3f"
            ),
        },
    )
    st.caption(
        "Lower RMSE/MAE is better; higher rank correlation is better. Even a perfect model has RMSE "
        "around 2.7–2.9 for players who play, because FPL points are noisy. "
        "FPL ep is FPL's own pre-deadline prediction, taken from the same news snapshot the model uses. Team "
        "news comes from the snapshot after the previous gameweek, a few days before the deadline. See the "
        "**Hindcast** page for whole-XI picks scored against reality."
    )
    c1, c2 = st.columns([3, 2])
    cal = pd.DataFrame(summ["calibration"])
    c1.plotly_chart(
        charts.scatter_calibration(
            cal, "predicted", "actual", "Calibration: average actual vs predicted points (deciles)"
        ),
        width="stretch",
        theme=None,
    )
    top = pd.DataFrame(summ["top_picks"])
    c2.markdown("**Average actual points of each gameweek's top-10 picks**")
    c2.dataframe(top.round(2), hide_index=True, width="stretch")

st.subheader("This season, live")
from midweek_merchant.backtest.run import live_tracking  # noqa: E402

live = live_tracking(common.SETTINGS)
if live.empty:
    st.write(
        "Projections are archived before every deadline by the scheduled job; once a gameweek has been "
        "played, its accuracy appears here."
    )
else:
    rows = []
    for gw, g in live.groupby("gw"):
        err = g["xpts"] - g["points"]
        rows.append(
            {
                "gw": int(gw),
                "players": len(g),
                "rmse": float((err**2).mean() ** 0.5),
                "mae": float(err.abs().mean()),
                "predicted_total": float(g["xpts"].sum()),
                "actual_total": float(g["points"].sum()),
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
