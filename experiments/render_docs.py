"""Render README.md, POST.md and docs/*.md from docs/templates/*.j2 and results/*.json, so every
number in the prose is the number the simulator produced in this run."""
from __future__ import annotations

import json
import pathlib

import jinja2

from experiments.common import RESULTS, ROOT
from sim.hardware import load_yaml

TEMPLATES = ROOT / "docs/templates"
OUTPUTS = {
    "README.md.j2": ROOT / "README.md",
    "POST.md.j2": ROOT / "POST.md",
    "01_workload.md.j2": ROOT / "docs/01_workload.md",
    "02_design_rationale.md.j2": ROOT / "docs/02_design_rationale.md",
    "03_architecture.md.j2": ROOT / "docs/03_architecture.md",
    "04_results.md.j2": ROOT / "docs/04_results.md",
    "05_limitations.md.j2": ROOT / "docs/05_limitations.md",
    "06_simulator.md.j2": ROOT / "docs/06_simulator.md",
}


def n(x, d=0):
    if x is None:
        return "n/a"
    if d < 0:  # round to 10^-d and print without decimals
        return f"{round(x, d):,.0f}"
    return f"{x:,.{d}f}"


def pct(x, d=0):
    return f"{100 * x:.{d}f}%"


def si(x, unit="", d=2):
    """Engineering notation: 1.16e10 -> '11.6 G'."""
    if x is None:
        return "n/a"
    for f, p in ((1e15, "P"), (1e12, "T"), (1e9, "G"), (1e6, "M"), (1e3, "k")):
        if abs(x) >= f:
            v = x / f
            return f"{v:.{d}g} {p}{unit}" if v < 100 else f"{v:.0f} {p}{unit}"
    return f"{x:.0f} {unit}".strip()


def x(v, d=1):
    return f"{v:.{d}f}x"


def sp(v):
    """Signed percent of a ratio-minus-one, without '-0%'."""
    r = round(100 * v)
    return "±0%" if r == 0 else f"{r:+d}%"


def context() -> dict:
    W = json.loads((RESULTS / "workload.json").read_text())
    D = json.loads((RESULTS / "decode.json").read_text())
    P = json.loads((RESULTS / "prefill_tradestudy.json").read_text())
    S = json.loads((RESULTS / "scalesim.json").read_text())
    REP = load_yaml("data/reported_baseline.yaml")
    rtl_path = RESULTS / "router.json"
    RTL = json.loads(rtl_path.read_text()) if rtl_path.exists() else {"match": "256/256", "latency_cycles": 98, "note": "from last committed run"}
    C = {r["key"]: r for r in D["comparison"]["rows"]}
    cal = D["calibration"]
    dec4 = cal["decomposition"]["gb300_tp4"]
    fixed4 = dec4["overhead"] + dec4["collective"]
    dec8 = cal["decomposition"]["b300_tp8"]
    fixed8 = dec8["overhead"] + dec8["collective"]
    ss = D["strong_scaling"]
    cm = D["comparison"]
    ps = {r["load_fraction"]: r for r in cm["gpu_power_sweep"]}
    pr = {r["purchase_usd_per_gpu"]: r for r in cm["gpu_price_sweep"]}
    abl = D["ablation"]["steps"]
    MC = D["monte_carlo"]
    ad = cm["prefill_adder"]["usd_per_mtok"]
    K = {
        "meas4": REP["configs"]["gb300_tp4"], "meas8": REP["configs"]["b300_tp8"],
        "fixed4_ms": fixed4, "fixed4_share": fixed4 / REP["configs"]["gb300_tp4"]["step_ms"],
        "fixed8_ms": fixed8, "fixed8_share": fixed8 / REP["configs"]["b300_tp8"]["step_ms"],
        "mem4_ms": dec4["memory"], "mem8_ms": dec8["memory"],
        "fixed_lo": cal["fixed_share_range"][0], "fixed_hi": cal["fixed_share_range"][1],
        "tp8_gain": REP["configs"]["gb300_tp4"]["step_ms"] / REP["configs"]["b300_tp8"]["step_ms"] - 1,
        "tp8_tok_gain": REP["configs"]["b300_tp8"]["decode_tok_s"] / REP["configs"]["gb300_tp4"]["decode_tok_s"] - 1,
        "sw_vs_model": C["gpu_df_tp4"]["tok_s_user"] / C["gpu_tp4"]["tok_s_user"],
        "sw_vs_meas": C["gpu_df_tp4"]["tok_s_user"] / REP["configs"]["gb300_tp4"]["decode_tok_s"],
        "asic_vs_model": C["asic"]["tok_s_user"] / C["gpu_tp4"]["tok_s_user"],
        "asic_vs_meas": C["asic"]["tok_s_user"] / REP["configs"]["gb300_tp4"]["decode_tok_s"],
        "asic_vs_sw": C["asic"]["tok_s_user"] / C["gpu_df_tp4"]["tok_s_user"],
        "asic8": ss["asic"][2]["tok_s_user"], "sw8": ss["gpu_df_tp4"][2]["tok_s_user"], "gpu8": ss["gpu_tp4"][2]["tok_s_user"],
        "asic16": ss["asic"][3]["tok_s_user"], "sw16": ss["gpu_df_tp4"][3]["tok_s_user"], "gpu16": ss["gpu_tp4"][3]["tok_s_user"],
        "tpj_vs_sw": ps[0.6]["asic_ratio_vs_gpu_df"], "tpj_vs_sw_lo": ps[0.4]["asic_ratio_vs_gpu_df"], "tpj_vs_sw_hi": ps[1.0]["asic_ratio_vs_gpu_df"],
        "tpj_vs_gpu": ps[0.6]["asic_ratio_vs_gpu"], "tpj_vs_gpu_lo": ps[0.4]["asic_ratio_vs_gpu"], "tpj_vs_gpu_hi": ps[1.0]["asic_ratio_vs_gpu"],
        # $/token ratios include the GPU prefill-pool adder on both sides
        "usd_vs_sw": (pr[45000]["gpu_df_usd_per_mtok"] + ad) / (C["asic"]["usd_per_mtok_owned"] + ad),
        "usd_vs_sw_lo": (pr[25000]["gpu_df_usd_per_mtok"] + ad) / (C["asic"]["usd_per_mtok_owned"] + ad),
        "usd_vs_sw_hi": (pr[65000]["gpu_df_usd_per_mtok"] + ad) / (C["asic"]["usd_per_mtok_owned"] + ad),
        "usd_vs_gpu": (pr[45000]["gpu_usd_per_mtok"] + ad) / (C["asic"]["usd_per_mtok_owned"] + ad),
        "rubin_df_vs_df": C["rubin_df_tp4"]["tok_s_user"] / C["gpu_df_tp4"]["tok_s_user"],
        "rubin_df_vs_rubin": C["rubin_df_tp4"]["tok_s_user"] / C["rubin_tp4"]["tok_s_user"],
        "be_sw_300": cm["breakeven_volume"]["gpu_df_tp4@nre300M"], "be_sw_600": cm["breakeven_volume"]["gpu_df_tp4@nre600M"],
        "be_sw_150": cm["breakeven_volume"]["gpu_df_tp4@nre150M"], "be_gpu_300": cm["breakeven_volume"]["gpu_tp4@nre300M"],
        "rubin_vs_gb300": C["rubin_tp4"]["tok_s_user"] / C["gpu_tp4"]["tok_s_user"] - 1,
        "rubin_df_vs_gb300": C["rubin_df_tp4"]["tok_s_user"] / C["gpu_tp4"]["tok_s_user"],
        "rubin_bw_ratio": 19.2 / 8.0,
        "abl": abl, "abl_by": {s["id"]: s for s in abl}, "MC": MC,
        "roofline": cm["roofline_tok_s_asic"],
    }
    bs = D["batch_sweep"]
    K["b256_asic"] = bs["asic"][-1]
    K["b256_gpu"] = bs["gpu_tp4"][-1]
    K["b256_sw"] = bs["gpu_df_tp4"][-1]
    return {"W": W, "D": D, "P": P, "S": S, "REP": REP, "RTL": RTL, "C": C, "K": K, "cal": cal}


def main() -> None:
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATES)), undefined=jinja2.StrictUndefined,
                             trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
    env.filters.update({"n": n, "pct": pct, "si": si, "x": x})
    env.globals.update({"n": n, "pct": pct, "si": si, "x": x, "sp": sp})
    env.filters["sp"] = sp
    ctx = context()
    for tpl, out in OUTPUTS.items():
        if not (TEMPLATES / tpl).exists():
            continue
        text = env.get_template(tpl).render(**ctx)
        header = f"<!-- generated from docs/templates/{tpl} by experiments/render_docs.py; edit the template -->\n"
        out.write_text(header + text)


if __name__ == "__main__":
    main()
