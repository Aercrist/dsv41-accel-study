"""The platforms compared in every experiment, built once with the GPU calibration applied.

Calibrated GPU baselines take both fitted parameters (hbm_eff, kernel_overhead). Projected
GPU software variants take only the fitted hbm_eff and keep their own overhead model.
"""
from __future__ import annotations

from functools import lru_cache

from sim.calibrate import Calibration, calibrate
from sim.hardware import Hardware, load_hw
from sim.modelspec import ModelSpec

PLATFORMS = {
    # key: (yaml, label, calibration use)
    "gpu_tp4": ("configs/hw/gb300_tp4.yaml", "4x GB300, deepseek-ultrafast (calibrated)", "full"),
    "gpu_tp8": ("configs/hw/b300_tp8.yaml", "8x B300, deepseek-ultrafast (calibrated)", "full"),
    "gpu_mk_tp4": ("configs/hw/gpu_megakernel_tp4.yaml", "4x GB300, fused megakernel (projected)", "eff"),
    "gpu_ideal_tp4": ("configs/hw/gpu_ideal_tp4.yaml", "4x GB300, ideal software (bound)", "eff"),
    "asic": ("configs/hw/asic_mda1.yaml", "MDA-1 ASIC x4 (proposed)", "none"),
    "fpga": ("configs/hw/fpga_v80.yaml", "16x Alveo V80 FPGA", "none"),
    "rubin_tp4": ("configs/hw/rubin_tp4.yaml", "4x Rubin, today's software (projected)", "full"),
    "asic_hbm4": ("configs/hw/asic_mda1_hbm4.yaml", "MDA-1 HBM4 x4 (projected)", "none"),
}


@lru_cache(maxsize=1)
def spec() -> ModelSpec:
    return ModelSpec.load()


@lru_cache(maxsize=1)
def cal() -> Calibration:
    return calibrate(spec())


def platform(key: str, **overrides) -> Hardware:
    path, label, mode = PLATFORMS[key]
    c = cal()
    over: dict = {}
    if mode == "full":
        over = c.as_overrides()
    elif mode == "eff":
        over = {"hbm_eff": c.hbm_eff}
    over.update(overrides)
    hw = load_hw(path, **over)
    hw.name = label if "name" not in overrides else overrides["name"]
    return hw


def label(key: str) -> str:
    return PLATFORMS[key][1]
