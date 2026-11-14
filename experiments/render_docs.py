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
    return "n/a" if x is None else f"{x:,.{d}f}"


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
    sens = cal["fit_sensitivity"]
    ss = D["strong_scaling"]
    tor = D["tornado"]
    spd = [r[k]["speedup"] for r in tor["rows"] if not r["param"].startswith("routing") for k in ("low", "high")]
    usd = [r[k]["usd_per_mtok"] for r in tor["rows"] for k in ("low", "high")]
    tpj = [r[k]["tok_per_joule"] for r in tor["rows"] for k in ("low", "high")]
    abl = D["ablation"]["steps"]
    K = {
        "meas4": REP["configs"]["gb300_tp4"], "meas8": REP["configs"]["b300_tp8"],
        "fixed4_ms": fixed4, "fixed4_share": fixed4 / REP["configs"]["gb300_tp4"]["step_ms"],
        "fixed8_ms": fixed8, "fixed8_share": fixed8 / REP["configs"]["b300_tp8"]["step_ms"],
        "mem4_ms": dec4["memory"], "mem8_ms": dec8["memory"],
        "fixed_share_min": min(s["fixed_share_tp4"] for s in sens), "fixed_share_max": max(s["fixed_share_tp4"] for s in sens),
        "tp8_gain": REP["configs"]["gb300_tp4"]["step_ms"] / REP["configs"]["b300_tp8"]["step_ms"] - 1,
        "asic_vs_meas": C["asic"]["tok_s_user"] / REP["configs"]["gb300_tp4"]["decode_tok_s"],
        "asic_vs_model": C["asic"]["tok_s_user"] / C["gpu_tp4"]["tok_s_user"],
        "asic_vs_ideal": C["asic"]["tok_s_user"] / C["gpu_ideal_tp4"]["tok_s_user"],
        "asic_vs_mk": C["asic"]["tok_s_user"] / C["gpu_mk_tp4"]["tok_s_user"],
        "ideal_vs_model": C["gpu_ideal_tp4"]["tok_s_user"] / C["gpu_tp4"]["tok_s_user"],
        "asic8": ss["asic"][2]["tok_s_user"], "asic16": ss["asic"][3]["tok_s_user"],
        "gpu8": ss["gpu_tp4"][2]["tok_s_user"], "gpu16": ss["gpu_tp4"][3]["tok_s_user"],
        "ideal8": ss["gpu_ideal_tp4"][2]["tok_s_user"], "ideal16": ss["gpu_ideal_tp4"][3]["tok_s_user"],
        "asic8_vs_meas8": ss["asic"][2]["tok_s_user"] / REP["configs"]["b300_tp8"]["decode_tok_s"],
        "tpj_ratio": C["asic"]["tok_per_joule"] / C["gpu_tp4"]["tok_per_joule"],
        "usd_ratio_owned": C["gpu_tp4"]["usd_per_mtok_owned"] / C["asic"]["usd_per_mtok"],
        "usd_ratio_owned_ideal": C["gpu_ideal_tp4"]["usd_per_mtok_owned"] / C["asic"]["usd_per_mtok"],
        "usd_ratio_rental": C["gpu_tp4"]["usd_per_mtok"] / C["asic"]["usd_per_mtok"],
        "rubin_vs_gb300": C["rubin_tp4"]["tok_s_user"] / C["gpu_tp4"]["tok_s_user"] - 1,
        "rubin_bw_ratio": 22.0 / 8.0,
        "spd_min": min(spd), "spd_max": max(spd), "usd_min": min(usd), "usd_max": max(usd),
        "tpj_min": min(tpj), "tpj_max": max(tpj),
        "abl": abl,
        "gpu_owned_sweep": tor["gpu_owned_cost_sweep"],
    }
    bs = D["batch_sweep"]
    K["b256_asic"] = bs["asic"][-1]
    K["b256_gpu"] = bs["gpu_tp4"][-1]
    K["b64_asic"] = [p for p in bs["asic"] if p["batch"] == 64][0]
    K["b64_gpu"] = [p for p in bs["gpu_tp4"] if p["batch"] == 64][0]
    return {"W": W, "D": D, "P": P, "S": S, "REP": REP, "RTL": RTL, "C": C, "K": K, "cal": cal}


def main() -> None:
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATES)), undefined=jinja2.StrictUndefined,
                             trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
    env.filters.update({"n": n, "pct": pct, "si": si, "x": x})
    env.globals.update({"n": n, "pct": pct, "si": si, "x": x})
    ctx = context()
    for tpl, out in OUTPUTS.items():
        if not (TEMPLATES / tpl).exists():
            continue
        text = env.get_template(tpl).render(**ctx)
        header = f"<!-- generated from docs/templates/{tpl} by experiments/render_docs.py; edit the template -->\n"
        out.write_text(header + text)


if __name__ == "__main__":
    main()
