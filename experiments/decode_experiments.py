"""Phase 4/5 decode experiments: calibration report, baseline vs proposed, scaling sweeps,
expert cache, tornado and ablation. All outputs land in results/ (JSON + PNG).

Every number here is SIMULATED/PROJECTED except the GPU measurements quoted from
data/reported_baseline.yaml.
"""
from __future__ import annotations

import copy
import dataclasses

import matplotlib.pyplot as plt
import numpy as np

from experiments.common import FIG, PALETTE, RESULTS, save_json, style
from experiments.platforms import cal, label, platform, spec
from sim.calibrate import CONFIGS, calibrate
from sim.cost import asic_unit_cost, dollars_per_hour, usd_per_mtok
from sim.energy import asic_area, step_energy
from sim.engine import simulate_step
from sim.expert_cache import che_lru_hit, hit_rate, sticky_zipf_trace
from sim.hardware import load_hw, load_yaml
from sim.workload import DecodeWorkload, decode_step

REP = load_yaml("data/reported_baseline.yaml")
ACCEPT = REP["configs"]["gb300_tp4"]["accept_len"]


def run(hw, wl: DecodeWorkload | None = None, hit: float = 0.0, cost_mode: str = "rental") -> dict:
    wl = wl or DecodeWorkload()
    ops = decode_step(spec(), wl)
    r = simulate_step(ops, hw, hit_rate=hit)
    tok_step = wl.accept_len * wl.batch
    tps = tok_step / r.step_time
    e = step_energy(ops, r, hw, tok_step, hit_rate=hit)
    usd_h = dollars_per_hour(hw, e.watts, mode=cost_mode)
    return {
        "platform": hw.name, "n_chips": hw.n_chips, "batch": wl.batch, "context": wl.context,
        "step_ms": r.step_time * 1e3, "tok_s_user": wl.accept_len / r.step_time, "tok_s_system": tps,
        "tok_s_per_chip": tps / hw.n_chips, "hbm_busy": r.hbm_busy, "hbm_gb_per_chip": r.hbm_bytes / 1e9,
        "watts": e.watts, "tok_per_joule": e.tokens_per_joule, "usd_per_hour": usd_h,
        "usd_per_mtok": usd_per_mtok(tps, usd_h),
        "breakdown_ms": {k: v * 1e3 for k, v in r.breakdown.items()},
        "by_category_ms": {k: v * 1e3 for k, v in r.by_category.items()},
        "energy_parts_j": e.parts,
    }


# ---------------------------------------------------------------------------------------------
def calibration_report() -> dict:
    c = cal()
    out = {"hbm_eff": c.hbm_eff, "kernel_overhead_us": c.kernel_overhead * 1e6, "eff_prior": c.eff_prior,
           "predicted_ms": c.predicted_ms, "measured_ms": c.measured_ms, "loo": c.loo}
    # decomposition of the measured steps
    decomp = {}
    for k in CONFIGS:
        hw = platform("gpu_tp4" if k == "gb300_tp4" else "gpu_tp8")
        wl = DecodeWorkload(verify_head=REP["configs"][k]["verify_head"])
        decomp[k] = run(hw, wl)
    out["decomposition"] = {k: v["breakdown_ms"] for k, v in decomp.items()}
    out["hbm_busy"] = {k: v["hbm_busy"] for k, v in decomp.items()}
    out["n_kernels_per_step"] = sum(o.n_kernels for o in decode_step(spec(), DecodeWorkload()))
    out["n_collectives_per_step"] = sum(1 for o in decode_step(spec(), DecodeWorkload()) if o.coll > 0)
    # leave-one-out error vs the bandwidth-efficiency prior
    loo_curve = []
    for eff in (0.75, 0.80, 0.85, 0.868, 0.90, 0.935, 0.95):
        hw4 = load_hw(CONFIGS["gb300_tp4"], hbm_eff=eff)
        hw8 = load_hw(CONFIGS["b300_tp8"], hbm_eff=eff)
        o4 = decode_step(spec(), DecodeWorkload(verify_head="fp8"))
        o8 = decode_step(spec(), DecodeWorkload(verify_head="bf16"))
        from scipy.optimize import brentq
        ko = brentq(lambda x: simulate_step(o4, hw4.replace(kernel_overhead=x * 1e-6)).step_time * 1e3 - 3.30, 0, 50) * 1e-6
        p8 = simulate_step(o8, hw8.replace(kernel_overhead=ko)).step_time * 1e3
        loo_curve.append({"eff": eff, "kernel_overhead_us": ko * 1e6, "pred_tp8_ms": p8, "err_pct": 100 * (p8 - 2.71) / 2.71})
    out["loo_vs_eff_prior"] = loo_curve
    # robustness of the fit to unidentifiable assumptions
    sens = []
    for name, kw, wkw in (("baseline", {}, {}),
                          ("collective latency 2.37 us", {"coll_latency": 2.37e-6}, {}),
                          ("collective latency 10 us", {"coll_latency": 10e-6}, {}),
                          ("+0.5 us per extra peer", {"coll_latency_per_peer": 0.5e-6}, {}),
                          ("routing locality 0.5", {}, {"locality": 0.5}),
                          ("context 32K", {}, {"context": 32768})):
        cc = _calibrate_with(kw, wkw)
        sens.append({"case": name, **cc})
    out["fit_sensitivity"] = sens
    return out


def _calibrate_with(hw_kw: dict, wl_kw: dict) -> dict:
    from scipy.optimize import least_squares
    meas = {k: REP["configs"][k]["step_ms"] for k in CONFIGS}
    hws = {k: load_hw(v, **hw_kw) for k, v in CONFIGS.items()}
    ops = {k: decode_step(spec(), DecodeWorkload(verify_head=REP["configs"][k]["verify_head"], **wl_kw)) for k in CONFIGS}

    def resid(x):
        return [(simulate_step(ops[k], hws[k].replace(hbm_eff=x[0], kernel_overhead=x[1] * 1e-6)).step_time * 1e3 - meas[k]) / meas[k]
                for k in CONFIGS]

    f = least_squares(resid, x0=[0.85, 2.0], bounds=([0.3, 0.0], [1.0, 20.0]))
    hw4 = hws["gb300_tp4"].replace(hbm_eff=f.x[0], kernel_overhead=f.x[1] * 1e-6)
    r = simulate_step(ops["gb300_tp4"], hw4)
    fixed = (r.breakdown["overhead"] + r.breakdown["collective"]) * 1e3
    # what the ASIC speedup becomes under this alternative calibration
    asic = run(platform("asic"))
    return {"hbm_eff": f.x[0], "kernel_overhead_us": f.x[1], "fixed_ms_tp4": fixed, "fixed_share_tp4": fixed / 3.30,
            "asic_speedup_vs_measured": asic["tok_s_user"] / (ACCEPT / 3.30e-3)}


# ---------------------------------------------------------------------------------------------
def baseline_vs_proposed() -> dict:
    rows = []
    for key in ("gpu_tp4", "gpu_tp8", "gpu_mk_tp4", "gpu_ideal_tp4", "asic", "fpga", "rubin_tp4", "asic_hbm4"):
        hw = platform(key)
        wl = DecodeWorkload(verify_head="bf16" if key == "gpu_tp8" else "fp8")
        r = run(hw, wl)
        r["key"] = key
        if hw.kind == "gpu":
            r["usd_per_mtok_owned"] = run(hw, wl, cost_mode="owned")["usd_per_mtok"]
        else:
            r["usd_per_mtok_owned"] = r["usd_per_mtok"]
        rows.append(r)
    asic = platform("asic")
    out = {"rows": rows, "asic_area_mm2": asic_area(asic), "asic_unit_cost": asic_unit_cost(asic),
           "asic_hbm4_area_mm2": asic_area(platform("asic_hbm4")), "asic_hbm4_unit_cost": asic_unit_cost(platform("asic_hbm4"))}
    # measured reference
    out["measured"] = {k: {"tok_s": v["decode_tok_s"], "step_ms": v["step_ms"]} for k, v in REP["configs"].items()}

    style()
    keys = ["gpu_tp4", "gpu_mk_tp4", "gpu_ideal_tp4", "asic"]
    sel = [r for r in rows if r["key"] in keys]
    fig, ax = plt.subplots(figsize=(7.4, 3.6))
    parts = [("memory", "#2471a3", "weight/KV streaming (HBM)"), ("compute", "#16a085", "compute-bound"),
             ("collective", "#e67e22", "collectives"), ("overhead", "#c0392b", "kernel / barrier / pipeline overhead")]
    y = np.arange(len(sel))
    left = np.zeros(len(sel))
    for k, col, lab in parts:
        v = np.array([r["breakdown_ms"][k] for r in sel])
        ax.barh(y, v, left=left, color=col, label=lab, height=0.6)
        left += v
    for i, r in enumerate(sel):
        ax.text(left[i] + 0.04, i, f'{r["step_ms"]:.2f} ms  ->  {r["tok_s_user"]:,.0f} tok/s/user', va="center", fontsize=8)
    ax.set_yticks(y, [label(r["key"]) for r in sel], fontsize=8)
    ax.invert_yaxis()
    ax.set_xlim(0, max(left) * 1.55)
    ax.set_xlabel("decode step time (ms), batch 1, 4 chips, 8 TB/s HBM per chip (simulated)")
    ax.set_title("Where a DeepSeek-V4.1-Flash decode step goes")
    ax.legend(fontsize=7, loc="lower right")
    fig.savefig(FIG / "fig_step_breakdown.png")
    plt.close(fig)
    return out


def strong_scaling() -> dict:
    out = {}
    chips = [2, 4, 8, 16]
    for key in ("gpu_tp4", "gpu_mk_tp4", "gpu_ideal_tp4", "asic"):
        pts = []
        for n in chips:
            hw = platform(key, n_chips=n, coll_latency_per_peer=0.1e-6)
            r = run(hw)
            pts.append({"n_chips": n, "tok_s_user": r["tok_s_user"], "step_ms": r["step_ms"], "usd_per_mtok": r["usd_per_mtok"]})
        out[key] = pts
    style()
    fig, ax = plt.subplots(figsize=(6.0, 3.8))
    for key, col, m in (("gpu_tp4", PALETTE["gpu"], "o"), ("gpu_mk_tp4", "#a6acaf", "^"), ("gpu_ideal_tp4", "#5d6d7e", "s"), ("asic", PALETTE["asic"], "D")):
        ax.plot(chips, [p["tok_s_user"] for p in out[key]], marker=m, color=col, label=label(key))
    for k, v in REP["configs"].items():
        n = 4 if k == "gb300_tp4" else 8
        ax.scatter([n], [v["decode_tok_s"]], marker="*", s=140, color="black", zorder=5, label="measured (deepseek-ultrafast README)" if n == 4 else None)
    ax.set_xscale("log", base=2)
    ax.set_xticks(chips, [str(c) for c in chips])
    ax.set_xlabel("chips per sequence (tensor-parallel width)")
    ax.set_ylabel("tokens / s / user (batch 1)")
    ax.set_title("Fixed per-layer latency caps GPU strong scaling (simulated)")
    ax.legend(fontsize=7)
    fig.savefig(FIG / "fig_strong_scaling.png")
    plt.close(fig)
    return out


def batch_sweep() -> dict:
    out = {}
    batches = [1, 2, 4, 8, 16, 32, 64, 128, 256]
    for key in ("gpu_tp4", "gpu_ideal_tp4", "asic"):
        pts = []
        for B in batches:
            r = run(platform(key), DecodeWorkload(batch=B))
            ro = run(platform(key), DecodeWorkload(batch=B), cost_mode="owned") if key.startswith("gpu") else r
            pts.append({"batch": B, "tok_s_user": r["tok_s_user"], "tok_s_system": r["tok_s_system"], "step_ms": r["step_ms"],
                        "usd_per_mtok": r["usd_per_mtok"], "usd_per_mtok_owned": ro["usd_per_mtok"], "tok_per_joule": r["tok_per_joule"],
                        "hbm_busy": r["hbm_busy"]})
        out[key] = pts
    style()
    fig, axs = plt.subplots(1, 2, figsize=(10.5, 3.9))
    for key, col, m in (("gpu_tp4", PALETTE["gpu"], "o"), ("gpu_ideal_tp4", "#5d6d7e", "s"), ("asic", PALETTE["asic"], "D")):
        p = out[key]
        axs[0].plot([q["tok_s_system"] / 4 for q in p], [q["tok_s_user"] for q in p], marker=m, color=col, label=label(key))
        for q in p:
            if q["batch"] in (1, 16, 256):
                axs[0].annotate(f'B={q["batch"]}', (q["tok_s_system"] / 4, q["tok_s_user"]), fontsize=6, xytext=(3, 3), textcoords="offset points")
        axs[1].plot([q["tok_s_user"] for q in p], [q["usd_per_mtok_owned"] for q in p], marker=m, color=col, label=label(key))
    axs[0].set_xscale("log"); axs[0].set_yscale("log")
    axs[0].set_xlabel("throughput per chip (tok/s)")
    axs[0].set_ylabel("interactivity (tok/s/user)")
    axs[0].set_title("Throughput-interactivity frontier, 4 chips (simulated)")
    axs[1].set_xscale("log"); axs[1].set_yscale("log")
    axs[1].set_xlabel("interactivity (tok/s/user)")
    axs[1].set_ylabel("$ / M output tokens (owned-hardware basis)")
    axs[1].set_title("Cost vs interactivity (GPU purchase price is an assumption)")
    axs[0].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(FIG / "fig_batch_frontier.png")
    plt.close(fig)
    return out


def context_sweep() -> dict:
    out = {}
    ctxs = [4096, 16384, 65536, 262144, 1 << 20]
    for key in ("gpu_tp4", "asic"):
        for B in (1, 16):
            out[f"{key}_b{B}"] = [{"context": c, **{k: v for k, v in run(platform(key), DecodeWorkload(context=c, batch=B)).items()
                                                    if k in ("tok_s_user", "tok_s_system", "step_ms", "hbm_gb_per_chip")}} for c in ctxs]
    style()
    fig, ax = plt.subplots(figsize=(6.0, 3.6))
    for key, col in (("gpu_tp4", PALETTE["gpu"]), ("asic", PALETTE["asic"])):
        for B, ls in ((1, "-"), (16, "--")):
            p = out[f"{key}_b{B}"]
            ax.plot(ctxs, [q["tok_s_user"] for q in p], ls, marker="o", color=col, label=f"{label(key)}, batch {B}")
    ax.set_xscale("log", base=2)
    ax.set_xlabel("context length (tokens)")
    ax.set_ylabel("tok/s/user")
    ax.set_title("Decode speed vs context (CSA2 keeps it nearly flat; simulated)")
    ax.legend(fontsize=6)
    fig.savefig(FIG / "fig_context_sweep.png")
    plt.close(fig)
    return out


def hbm_sweep() -> dict:
    out = {}
    bws = [4e12, 6e12, 8e12, 12e12, 16e12, 22e12]
    for key in ("gpu_tp4", "gpu_ideal_tp4", "asic"):
        out[key] = [{"hbm_tb_s": b / 1e12, "tok_s_user": run(platform(key, hbm_bw=b))["tok_s_user"]} for b in bws]
    style()
    fig, ax = plt.subplots(figsize=(6.0, 3.6))
    for key, col, m in (("gpu_tp4", PALETTE["gpu"], "o"), ("gpu_ideal_tp4", "#5d6d7e", "s"), ("asic", PALETTE["asic"], "D")):
        ax.plot([p["hbm_tb_s"] for p in out[key]], [p["tok_s_user"] for p in out[key]], marker=m, color=col, label=label(key))
    ax.axvline(8, color="0.6", lw=0.8, ls=":")
    ax.text(8.2, ax.get_ylim()[1] * 0.92, "B300 / GB300", fontsize=7, color="0.4")
    ax.axvline(22, color="0.6", lw=0.8, ls=":")
    ax.text(18.5, ax.get_ylim()[1] * 0.92, "Rubin", fontsize=7, color="0.4")
    ax.set_xlabel("HBM bandwidth per chip (TB/s)")
    ax.set_ylabel("tok/s/user (batch 1, 4 chips)")
    ax.set_title("Who converts memory bandwidth into speed (simulated)")
    ax.legend(fontsize=7)
    fig.savefig(FIG / "fig_hbm_sweep.png")
    plt.close(fig)
    return out


def sram_sweep() -> dict:
    """Staging-buffer size: how much SRAM the dataflow prefetcher needs."""
    out = []
    for mb in (0, 4, 8, 16, 32, 64, 128, 256):
        hw = platform("asic", stage_bytes=mb * 1e6, sram_bytes=max(mb, 32) * 2**20 + 128 * 2**20)
        r = run(hw)
        out.append({"stage_mb": mb, "tok_s_user": r["tok_s_user"], "hbm_busy": r["hbm_busy"],
                    "die_mm2": asic_area(hw)["total"], "usd_per_mtok": r["usd_per_mtok"]})
    style()
    fig, ax = plt.subplots(figsize=(6.0, 3.4))
    ax.plot([max(p["stage_mb"], 1) for p in out], [p["tok_s_user"] for p in out], "D-", color=PALETTE["asic"])
    ax.set_xscale("log", base=2)
    ax.set_xticks([max(p["stage_mb"], 1) for p in out], ["0"] + [str(p["stage_mb"]) for p in out[1:]])
    ax.set_xlabel("weight staging buffer per chip (MB)")
    ax.set_ylabel("tok/s/user (batch 1)")
    ax.set_title("MDA-1: prefetch window needed to hide dependency bubbles (simulated)")
    fig.savefig(FIG / "fig_sram_sweep.png")
    plt.close(fig)
    return {"points": out}


def expert_cache_study() -> dict:
    """Hit rate needed vs SRAM it costs. Synthetic traces calibrated to a published LRU miss rate."""
    s = spec()
    # 1) calibrate the sticky-Zipf locality so that DeepSeek-V2-Lite-like routing (64 experts,
    #    top-6) gives LRU hit 72% with 32 slots (src: expert-locality: 28% miss)
    best = None
    for stay in (0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7):
        for zs in (0.0, 0.5, 0.8, 1.0, 1.2):
            tr = sticky_zipf_trace(400, 64, 6, 1, stay, zs, seed=1)
            h = hit_rate(tr, 32, "lru")
            if best is None or abs(h - 0.72) < abs(best[2] - 0.72):
                best = (stay, zs, h)
    stay, zs, h_cal = best
    # 2) apply that locality to V4.1 (384 experts, top-6, 6 verify rows per step)
    caps = [6, 12, 24, 48, 96, 192]
    tr = sticky_zipf_trace(300, s.n_routed_experts, s.n_activated_experts, 6, stay, zs, seed=2)
    curves = {pol: [{"slots": c, "hit": hit_rate(tr, c, pol)} for c in caps] for pol in ("lru", "lfu", "opt")}
    per_slot_mb = s.expert_bytes / 4 / 1e6  # one expert's TP4 shard per chip
    for pol in curves:
        for p in curves[pol]:
            p["sram_gb_per_chip"] = p["slots"] * s.n_layers * per_slot_mb / 1e3
    che = [{"slots": c, "hit": che_lru_hit(np.ones(s.n_routed_experts), c)} for c in caps]
    # 3) what a hit rate buys on MDA-1
    gains = [{"hit": h, "tok_s_user": run(platform("asic"), hit=h)["tok_s_user"]} for h in (0.0, 0.1, 0.2, 0.4, 0.6, 0.8)]
    sram_mb = platform("asic").sram_bytes / 2**20
    slots_fit = (sram_mb * 2**20 / 1e6 * 0.5) / (s.n_layers * per_slot_mb)  # if half the SRAM were an expert cache
    style()
    fig, axs = plt.subplots(1, 2, figsize=(10, 3.6))
    for pol, col in (("lru", "#c0392b"), ("lfu", "#e67e22"), ("opt", "#2471a3")):
        axs[0].plot([p["sram_gb_per_chip"] for p in curves[pol]], [p["hit"] * 100 for p in curves[pol]], "o-", color=col, label=pol.upper() if pol != "opt" else "Belady OPT (bound)")
    axs[0].plot([c["slots"] * s.n_layers * per_slot_mb / 1e3 for c in che], [c["hit"] * 100 for c in che], ":", color="0.5", label="Che approx., no locality")
    axs[0].axvline(sram_mb / 1024 / 2, color="0.3", lw=0.8, ls="--")
    axs[0].text(sram_mb / 1024 / 2 * 1.1, 5, "half of MDA-1 SRAM", fontsize=7)
    axs[0].set_xscale("log")
    axs[0].set_xlabel("expert-cache capacity per chip (GB)")
    axs[0].set_ylabel("hit rate (%)")
    axs[0].set_title("Synthetic traces, locality fit to DeepSeek-V2-Lite LRU data")
    axs[0].legend(fontsize=7)
    axs[1].plot([g["hit"] * 100 for g in gains], [g["tok_s_user"] for g in gains], "D-", color=PALETTE["asic"])
    axs[1].set_xlabel("expert-cache hit rate (%)")
    axs[1].set_ylabel("MDA-1 tok/s/user")
    axs[1].set_title("What a hit rate would buy")
    fig.tight_layout()
    fig.savefig(FIG / "fig_expert_cache.png")
    plt.close(fig)
    return {"locality_fit": {"stay": stay, "zipf_s": zs, "lru_hit_dsv2lite": h_cal, "target": 0.72},
            "curves": curves, "che_uniform": che, "gains": gains, "slots_per_layer_in_half_sram": slots_fit,
            "per_slot_mb": per_slot_mb}


# ---------------------------------------------------------------------------------------------
TORNADO = [
    # (label, kind, key, low, high) ; kind: hw (ASIC field), gpu (GPU field), wl, cost, area, power
    ("ASIC HBM efficiency (0.80-0.95)", "hw", "hbm_eff", 0.80, 0.95),
    ("ASIC collective latency (0.7-3 us)", "hw", "coll_latency", 3.0e-6, 0.7e-6),
    ("ASIC per-op pipeline overhead (0.05-0.6 us)", "hw", "op_overhead", 0.6e-6, 0.05e-6),
    ("ASIC dependent-fetch latency (0.2-2 us)", "hw", "hbm_latency", 2.0e-6, 0.2e-6),
    ("ASIC router latency (0.05-2 us)", "hw", "router_latency", 2.0e-6, 0.05e-6),
    ("ASIC staging buffer (16-256 MB)", "hw", "stage_bytes", 16e6, 256e6),
    ("routing locality (0-0.6)", "wl", "locality", 0.0, 0.6),
    ("acceptance length (5.1-6.1)", "wl", "accept_len", 5.1, 6.1),
    ("context length (2.6K-128K)", "wl", "context", 131072, 2600),
    ("NRE ($100M-$600M)", "cost", "nre_usd", 600e6, 100e6),
    ("production volume (5K-100K chips)", "cost", "volume_units", 5000, 100000),
    ("HBM price ($10-20/GB)", "cost", "hbm_usd_per_gb", 20.0, 10.0),
    ("system share per chip ($4K-16K)", "cost", "system_usd_per_chip", 16000, 4000),
    ("SRAM density (0.3-0.8 mm2/MiB)", "area", "mm2_per_mib_sram", 0.8, 0.3),
    ("FP8 MAC area (40-200 um2)", "area", "um2_per_fp8_mac", 200.0, 40.0),
    ("HBM pJ/bit (3-6)", "power", "hbm_pj_per_bit", 6.0, 3.0),
    ("ASIC static power (75-300 W)", "power", "static_w", 300.0, 75.0),
]


def _asic_with(kind, key, val):
    hw = platform("asic")
    wl = DecodeWorkload()
    if kind == "hw":
        hw = hw.replace(**{key: val})
    elif kind == "wl":
        wl = dataclasses.replace(wl, **{key: val})
    else:
        d = {"cost": hw.cost, "area": hw.area, "power": hw.power}[kind]
        d = copy.deepcopy(d)
        d[key] = val
        hw = hw.replace(**{kind: d})
    return hw, wl


def tornado() -> dict:
    base = run(platform("asic"))
    gpu_tok = ACCEPT / 3.30e-3
    rows = []
    for lab, kind, key, lo, hi in TORNADO:
        res = {}
        for tag, v in (("low", lo), ("high", hi)):
            hw, wl = _asic_with(kind, key, v)
            r = run(hw, wl)
            res[tag] = {"value": v, "tok_s_user": r["tok_s_user"], "usd_per_mtok": r["usd_per_mtok"], "tok_per_joule": r["tok_per_joule"]}
        rows.append({"param": lab, **res})
    # GPU-side uncertainties: speedup vs the calibrated GPU under alternative GPU assumptions
    gpu_rows = []
    for lab, kw in (("GPU purchase price $25K", {"cost": {"purchase_usd_per_gpu": 25000}}),
                    ("GPU purchase price $65K", {"cost": {"purchase_usd_per_gpu": 65000}})):
        gpu_rows.append({"case": lab})
    out = {"base": {k: base[k] for k in ("tok_s_user", "usd_per_mtok", "tok_per_joule")}, "rows": rows,
           "gpu_measured_tok_s": gpu_tok}
    style()
    fig, axs = plt.subplots(1, 3, figsize=(13.5, 5.2), sharey=True)
    metrics = (("tok_s_user", "MDA-1 tok/s/user"), ("usd_per_mtok", "MDA-1 $/M tokens (TCO)"), ("tok_per_joule", "MDA-1 tokens/J"))
    order = sorted(range(len(rows)), key=lambda i: -abs(rows[i]["high"]["tok_s_user"] - rows[i]["low"]["tok_s_user"])
                   - 1e-3 * abs(rows[i]["high"]["usd_per_mtok"] - rows[i]["low"]["usd_per_mtok"]))
    y = np.arange(len(rows))
    for ax, (m, title) in zip(axs, metrics):
        b = base[m]
        for yi, i in enumerate(order):
            lo, hi = rows[i]["low"][m], rows[i]["high"][m]
            ax.barh(yi, lo - b, left=b, color="#95a5a6", height=0.6)
            ax.barh(yi, hi - b, left=b, color=PALETTE["asic"], height=0.6)
        ax.axvline(b, color="black", lw=0.8)
        ax.set_title(title, fontsize=9)
    axs[0].set_yticks(y, [rows[i]["param"] for i in order], fontsize=7)
    axs[0].invert_yaxis()
    axs[0].axvline(gpu_tok, color=PALETTE["gpu"], ls="--", lw=1)
    axs[0].text(gpu_tok, len(rows) - 0.3, " measured 4xGB300", fontsize=7, color="0.3")
    fig.suptitle("Tornado: one-at-a-time sensitivity (red = favourable end of range; simulated)", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIG / "fig_tornado.png")
    plt.close(fig)
    return out


def ablation() -> dict:
    """Walk from the calibrated GPU to MDA-1 on the same HBM bandwidth, one feature at a time."""
    c = cal()
    g = platform("gpu_tp4")
    a = platform("asic")
    steps = [
        ("A0  4x GB300, deepseek-ultrafast (calibrated)", g, {}),
        ("A1  + one persistent program (no launches; barrier per stage)", g, {"kernel_overhead": 1.0e-6}),
        ("A2  + statically scheduled pipeline (no barriers)", g, {"prefetch": True, "stage_bytes": 0.0, "op_overhead": a.op_overhead,
                                                                 "router_latency": 1.0e-6, "hbm_latency": a.hbm_latency}),
        ("A3  + cross-layer weight prefetch (128 MB staging SRAM)", g, {"prefetch": True, "stage_bytes": a.stage_bytes, "op_overhead": a.op_overhead,
                                                                       "router_latency": 1.0e-6, "hbm_latency": a.hbm_latency}),
        ("A4  + hardware MoE router (gate -> expert DMA in 0.1 us)", g, {"prefetch": True, "stage_bytes": a.stage_bytes, "op_overhead": a.op_overhead,
                                                                        "router_latency": a.router_latency, "hbm_latency": a.hbm_latency}),
        ("A5  + in-fabric all-reduce (5 -> 1.4 us)", g, {"prefetch": True, "stage_bytes": a.stage_bytes, "op_overhead": a.op_overhead,
                                                         "router_latency": a.router_latency, "hbm_latency": a.hbm_latency, "coll_latency": a.coll_latency}),
        ("A6  = MDA-1 (its HBM efficiency 0.90, compute, Engram in LPDDR)", a, {}),
    ]
    out = []
    for lab, base, kw in steps:
        hw = base.replace(**kw)
        r = run(hw)
        out.append({"step": lab, "tok_s_user": r["tok_s_user"], "step_ms": r["step_ms"], "hbm_busy": r["hbm_busy"],
                    "breakdown_ms": r["breakdown_ms"]})
    extra = run(a, DecodeWorkload(shard_replicated=True))
    style()
    fig, ax = plt.subplots(figsize=(7.4, 3.6))
    vals = [o["tok_s_user"] for o in out]
    ax.bar(range(len(vals)), vals, color=[PALETTE["gpu"]] + ["#d98880"] * (len(vals) - 2) + [PALETTE["asic"]])
    for i, v in enumerate(vals):
        ax.text(i, v + 50, f"{v:,.0f}", ha="center", fontsize=7)
    ax.set_xticks(range(len(vals)), [o["step"].split()[0] for o in out])
    ax.set_ylabel("tok/s/user (batch 1, 4 chips, 8 TB/s each)")
    ax.set_title("Ablation: which architectural feature buys what (simulated)")
    fig.savefig(FIG / "fig_ablation.png")
    plt.close(fig)
    return {"steps": out, "shard_replicated_on_mda1": {"tok_s_user": extra["tok_s_user"]}, "calibration": {"hbm_eff": c.hbm_eff}}


def main() -> dict:
    out = {
        "calibration": calibration_report(),
        "comparison": baseline_vs_proposed(),
        "strong_scaling": strong_scaling(),
        "batch_sweep": batch_sweep(),
        "context_sweep": context_sweep(),
        "hbm_sweep": hbm_sweep(),
        "sram_sweep": sram_sweep(),
        "expert_cache": expert_cache_study(),
        "tornado": tornado(),
        "ablation": ablation(),
    }
    save_json(out, RESULTS / "decode.json")
    return out


if __name__ == "__main__":
    import json
    r = main()
    print(json.dumps({k: r["comparison"]["rows"][i]["tok_s_user"] for i, k in enumerate(["tp4", "tp8", "mk", "ideal", "asic", "fpga", "rubin", "asic4"])}, indent=1))
