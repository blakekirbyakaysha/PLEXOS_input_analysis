"""Detailed NSW ESS and EV analysis for July-August 2026."""
from pathlib import Path
import calendar
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import compare_to_actuals as cta

BASE = Path(__file__).resolve().parent
OUTPUT_DIR = BASE / "Comparison_ESS_EV_JulAug2026"
TRACE_TYPES = ["ESS", "EV"]
TARGET_DATASET = "ISP_NSW_STEP_CHANGE_POE50"
REGION = "NSW"
START = pd.Timestamp("2026-07-01 00:30:00")
END = pd.Timestamp("2026-09-01 00:00:00")  # period ending midnight after 31 Aug
WEEKDAY = {0:"Mon",1:"Tue",2:"Wed",3:"Thu",4:"Fri",5:"Sat",6:"Sun"}


def load_traces():
    old = cta.DATASET
    try:
        cta.DATASET = TARGET_DATASET
        loaded = cta.load_forecast_multi(TRACE_TYPES)
    finally:
        cta.DATASET = old
    out = {}
    for t in TRACE_TYPES:
        if t not in loaded:
            raise ValueError(f"Missing trace type {t}. Returned: {sorted(loaded)}")
        df = loaded[t]
        df = df[df["region"] == REGION].copy()
        df["datetime"] = pd.to_datetime(df["datetime"], errors="raise")
        df = df[(df["datetime"] >= START) & (df["datetime"] <= END)].copy()
        if df.empty:
            raise ValueError(f"{t}: no {REGION} rows from {START} to {END}")
        dups = df.duplicated(["reference_year", "datetime"], keep=False)
        if dups.any():
            raise ValueError(f"{t}: duplicate reference_year/datetime rows after NSW filtering")
        out[t] = prepare(df, t)
        print(f"{t}: {len(out[t]):,} NSW rows, {out[t]['reference_year'].nunique()} reference years")
    return out


def prepare(df, trace_type):
    df = df[["region","reference_year","datetime","forecast_mw"]].copy()
    df["forecast_mw"] = pd.to_numeric(df["forecast_mw"], errors="raise")
    diffs = df.sort_values(["reference_year","datetime"]).groupby("reference_year")["datetime"].diff()
    hours = diffs.dropna().dt.total_seconds().div(3600)
    interval_hours = float(hours[hours > 0].mode().iloc[0])
    if not np.isclose(interval_hours, 0.5):
        raise ValueError(f"{trace_type}: expected 0.5-hour data, inferred {interval_hours}")
    period_start = df["datetime"] - pd.Timedelta(minutes=30)
    df["date"] = period_start.dt.normalize()
    df["month"] = period_start.dt.month
    df["month_name"] = df["month"].map(lambda x: calendar.month_name[x])
    df["dow"] = period_start.dt.dayofweek
    df["day_name"] = df["dow"].map(WEEKDAY)
    df["day_type"] = np.where(df["dow"] < 5, "Weekday", "Weekend")
    df["interval"] = (period_start.dt.hour * 2 + period_start.dt.minute // 30 + 1).astype("int8")
    df["hour_ending"] = df["interval"] / 2
    df["energy_mwh"] = df["forecast_mw"] * 0.5
    return df.sort_values(["reference_year","datetime"]).reset_index(drop=True)


def qstats(group_cols, df):
    return df.groupby(group_cols)["forecast_mw"].agg(
        mean_mw="mean",
        p10_mw=lambda s: s.quantile(.10),
        p50_mw="median",
        p90_mw=lambda s: s.quantile(.90),
        min_mw="min",
        max_mw="max",
    ).reset_index()


def save(path):
    plt.tight_layout()
    plt.savefig(path, dpi=170, bbox_inches="tight")
    plt.close()


def plot_halfhour_quantiles(profile, title, path):
    fig, ax = plt.subplots(figsize=(12,5))
    x = profile["hour_ending"].to_numpy(float)
    p10 = profile["p10_mw"].to_numpy(float)
    p50 = profile["p50_mw"].to_numpy(float)
    p90 = profile["p90_mw"].to_numpy(float)
    ax.fill_between(x, p10, p90, alpha=.25, label="P10-P90 across reference years")
    ax.plot(x, p50, linewidth=2, label="P50")
    ax.axhline(0, color="black", linewidth=.8)
    ax.set(xlabel="Hour ending", ylabel="MW", title=title, xlim=(.5,24))
    ax.set_xticks(range(0,25,2)); ax.grid(alpha=.25); ax.legend(loc="upper left")
    fig.tight_layout(); fig.savefig(path,dpi=170); plt.close(fig)


def analyse_one(t, df):
    root = OUTPUT_DIR / t
    charts = root / "charts"
    root.mkdir(parents=True, exist_ok=True); charts.mkdir(parents=True, exist_ok=True)
    df.to_csv(root / "interval_data_jul_aug_2026.csv", index=False)

    # Reference-year x month x half-hour profiles.
    ref_profile = df.groupby(["reference_year","month","month_name","interval","hour_ending"])["forecast_mw"].mean().reset_index()
    ref_profile.to_csv(root / "reference_year_monthly_halfhour_profiles.csv", index=False)

    # Quantiles ACROSS reference years after forming each reference year's monthly mean shape.
    profile_q = qstats(["month","month_name","interval","hour_ending"], ref_profile)
    profile_q.to_csv(root / "monthly_halfhour_reference_year_quantiles.csv", index=False)

    # Daily energy/throughput and extrema per reference year.
    daily = df.groupby(["reference_year","date","month","month_name","day_type"]).agg(
        net_energy_mwh=("energy_mwh","sum"),
        positive_energy_mwh=("energy_mwh",lambda s: s.clip(lower=0).sum()),
        negative_energy_mwh=("energy_mwh",lambda s: s.clip(upper=0).sum()),
        min_mw=("forecast_mw","min"), max_mw=("forecast_mw","max"),
        mean_mw=("forecast_mw","mean"),
    ).reset_index()
    daily.to_csv(root / "daily_statistics_by_reference_year.csv", index=False)

    # Weekday/weekend reference-year shapes, then cross-ref-year quantiles.
    daytype_ref = df.groupby(["reference_year","month","month_name","day_type","interval","hour_ending"])["forecast_mw"].mean().reset_index()
    daytype_q = qstats(["month","month_name","day_type","interval","hour_ending"], daytype_ref)
    daytype_ref.to_csv(root / "weekday_weekend_profiles_by_reference_year.csv", index=False)
    daytype_q.to_csv(root / "weekday_weekend_reference_year_quantiles.csv", index=False)

    # Daily date x half-hour heatmap uses mean across reference years.
    heat = df.groupby(["date","interval"])["forecast_mw"].mean().unstack("interval").reindex(columns=range(1,49))
    heat.to_csv(root / "daily_halfhour_mean_across_reference_years.csv")
    fig, ax = plt.subplots(figsize=(13,10))
    im=ax.imshow(heat.to_numpy(), aspect="auto", origin="upper", cmap="coolwarm")
    fig.colorbar(im,ax=ax,label="Mean MW across reference years")
    ticks=np.arange(0,len(heat),5); ax.set_yticks(ticks); ax.set_yticklabels([heat.index[i].strftime("%d %b") for i in ticks])
    ax.set_xticks([0,7,15,23,31,39,47]); ax.set_xticklabels(["00:30","04:00","08:00","12:00","16:00","20:00","24:00"])
    ax.set(xlabel="Period ending",ylabel="Date",title=f"{t}: daily half-hour profile, Jul-Aug 2026 (mean across reference years)")
    fig.tight_layout(); fig.savefig(charts/"daily_halfhour_heatmap.png",dpi=170); plt.close(fig)

    for month in [7,8]:
        mname=calendar.month_name[month]
        rp=ref_profile[ref_profile.month==month]
        pq=profile_q[profile_q.month==month]
        plot_halfhour_quantiles(pq, f"{t}: {mname} 2026 half-hour profile", charts/f"{month:02d}_{mname.lower()}_quantiles.png")
        fig,ax=plt.subplots(figsize=(12,5))
        for ry,g in rp.groupby("reference_year"):
            ax.plot(g.hour_ending,g.forecast_mw,linewidth=.7,alpha=.45,label=str(ry))
        ax.axhline(0,color="black",linewidth=.8); ax.set(xlabel="Hour ending",ylabel="MW",title=f"{t}: {mname} 2026, all reference-year mean profiles",xlim=(.5,24))
        ax.set_xticks(range(0,25,2)); ax.grid(alpha=.25)
        # fixed legend placement avoids expensive loc='best'
        ax.legend(title="Reference year",bbox_to_anchor=(1.01,1),loc="upper left",fontsize=7,ncol=1)
        fig.tight_layout(); fig.savefig(charts/f"{month:02d}_{mname.lower()}_all_reference_years.png",dpi=170,bbox_inches="tight"); plt.close(fig)
        for dtype in ["Weekday","Weekend"]:
            d=daytype_q[(daytype_q.month==month)&(daytype_q.day_type==dtype)]
            plot_halfhour_quantiles(d,f"{t}: {mname} 2026 {dtype.lower()} profile",charts/f"{month:02d}_{mname.lower()}_{dtype.lower()}_quantiles.png")


def combined_analysis(traces):
    root=OUTPUT_DIR/"combined"; charts=root/"charts"; root.mkdir(parents=True,exist_ok=True); charts.mkdir(parents=True,exist_ok=True)
    ess=traces["ESS"].rename(columns={"forecast_mw":"ess_mw"})
    ev=traces["EV"].rename(columns={"forecast_mw":"ev_mw"})
    keys=["reference_year","datetime"]
    combined=ess[keys+["ess_mw"]].merge(ev[keys+["ev_mw"]],on=keys,how="inner",validate="one_to_one")
    combined["combined_mw"]=combined.ess_mw+combined.ev_mw
    ps=combined.datetime-pd.Timedelta(minutes=30)
    combined["month"]=ps.dt.month; combined["interval"]=(ps.dt.hour*2+ps.dt.minute//30+1).astype("int8"); combined["hour_ending"]=combined.interval/2
    combined.to_csv(root/"ess_ev_interval_combined.csv",index=False)
    ref=combined.groupby(["reference_year","month","interval","hour_ending"])[["ess_mw","ev_mw","combined_mw"]].mean().reset_index()
    ref.to_csv(root/"monthly_halfhour_by_reference_year.csv",index=False)
    for month in [7,8]:
        g=ref[ref.month==month].groupby(["interval","hour_ending"])[["ess_mw","ev_mw","combined_mw"]].median().reset_index()
        fig,ax=plt.subplots(figsize=(12,5))
        for col,label in [("ess_mw","ESS"),("ev_mw","EV"),("combined_mw","ESS + EV")]: ax.plot(g.hour_ending,g[col],label=label,linewidth=2 if col=="combined_mw" else 1.4)
        ax.axhline(0,color="black",linewidth=.8); ax.set(xlabel="Hour ending",ylabel="MW",title=f"ESS and EV: {calendar.month_name[month]} 2026 P50 reference-year profile",xlim=(.5,24)); ax.set_xticks(range(0,25,2)); ax.grid(alpha=.25); ax.legend(loc="upper left")
        fig.tight_layout(); fig.savefig(charts/f"{month:02d}_ess_ev_p50_profile.png",dpi=170); plt.close(fig)


def main():
    OUTPUT_DIR.mkdir(parents=True,exist_ok=True)
    print(f"Loading {REGION} {TARGET_DATASET} ESS/EV traces")
    print("Detailed window: 1 July 2026 to 31 August 2026, half-hourly")
    traces=load_traces()
    for t in TRACE_TYPES:
        print(f"\n=== {t} ==="); analyse_one(t,traces[t])
    combined_analysis(traces)
    print(f"\nDone. Outputs written to {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
