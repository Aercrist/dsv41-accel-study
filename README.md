<!-- generated from docs/templates/README.md.j2 by experiments/render_docs.py; edit the template -->
# Decode silicon for DeepSeek-V4.1-Flash

**A modeled hardware-architecture study of [deepseek-ultrafast](https://github.com/basetenlabs/deepseek-ultrafast).
It shows where the time goes, what a custom accelerator gives, and how much of that gain software can give first.**
All MDA-1 and projected-GPU numbers are **simulated/projected**. We quote the numbers marked *measured* from the deepseek-ultrafast README.

> **Status:** This is a performance-model study with one verified RTL block. There is no silicon, no synthesis and no GPU profile.
> We revised the claims after an adversarial review ([what changed](docs/05_limitations.md#revisions-after-adversarial-review)).

## Abstract

deepseek-ultrafast serves DeepSeek-V4.1-Flash one request at a time. DeepSeek-V4.1-Flash is a
552B-parameter MoE with FP4 experts. The engine gets 1,740 tok/s on 4 x GB300 and 2,060 tok/s on 8 x B300 (*measured*).
We rebuilt the workload from the Rust/CUDA source of the engine and the checkpoint headers of the model. Then
we built an op-level performance simulator and calibrated it to the two reported step times.

1. **About half of each decode step is fixed latency, not weight streaming.** The calibrated model
   attributes 1.85 ms of the 3.30 ms step (56%) to dependent-stage
   latency and collective latency. The range is 43%-62% across all alternative calibrations.
   The average HBM rate is 37% of peak.
2. **The fix is an execution model, not FLOPs.** The execution model replaces dependent kernel launches with one
   persistent program in a static order. Each stage hands off to the next stage with flags. The program streams the
   dense weights of the next layers while the experts of the current layer are in transit. On the **same 4 x GB300**
   the model projects **3,596 tok/s/user (2.1x the measured engine)**. The
   gain has three parts:
   - The persistent program gives +61% if a stage hand-off can decrease to ~1 µs. This is the least certain step.
   - Flags give +7%.
   - Cross-layer weight prefetch gives +23%.
3. **Custom silicon that uses that execution model gets the same speed. It is not faster.** MDA-1 is a
   decode ASIC. It has 2 dies, 8 x HBM3E at the 8 TB/s of GB300, 2 PF FP8, a hardware MoE router (RTL-verified)
   and in-fabric all-reduce. The model projects **3,656 tok/s/user**, 94% of the HBM roofline of MDA-1.

   We draw all assumptions of MDA-1 jointly. Then the result is 1.6x-2.3x the measured engine (5th-95th percentile). It is
   0.92x-1.19x the same-bandwidth GPU software (median 1.01x).

   **The case for MDA-1 is economic.** MDA-1 gets
   1.5x lower $/M tokens and 1.8x tokens/J against GPUs that run the same software.
   These GPUs are owned at $45K and draw 60% of TDP. Across $25-65K per GPU and 40-100% of TDP, those ratios are
   0.9x-2.1x and 1.2x-3.0x. Break-even is about 9,000 chips at $300M NRE.
4. **Bandwidth alone does not fix it.** Rubin has 19.2 TB/s (2.4x GB300). With the per-stage
   latency of today, the model projects only +35% for Rubin over GB300. With dataflow-style software on both,
   the bandwidth of Rubin gives 1.71x (6,149 vs 3,596 tok/s/user).

![Where a decode step goes](results/fig_step_breakdown.png)

![Ablation: software vs silicon](results/fig_ablation.png)

## Key results (batch 1, 4 chips; simulated unless marked)

| platform | tok/s/user | tokens/J † | $/M tok, owned ‡ |
|---|---|---|---|
| 4 x GB300, deepseek-ultrafast: *measured* 1,740; calibrated model | 1,697 | 0.51 | 0.91 |
| 4 x GB300, barrier-synced persistent kernel (projected) | 2,728 | 0.81 | 0.57 |
| **4 x GB300, dataflow-style software (projected)** | **3,596** | 1.07 | 0.43 |
| 16 x Alveo V80 FPGA | 1,180 | 0.49 | 1.36 |
| **4 x MDA-1 (proposed)** | **3,656** | **1.95** | **0.27** |
| 4 x Rubin, today's software / dataflow software (projected) | 2,284 / 6,149 | 0.53 / 1.42 | |
| 4 x MDA-1 with HBM4 at Rubin's bandwidth (projected) | 6,159 | 2.67 | 0.19 |

† GPU power is an *assumption* (60% of TDP). MDA-1 power is bottom-up. ‡ GPUs are at an *assumed* $45K all-in,
because there is no public B300 price. MDA-1 is at manufacturing cost plus $300M NRE over 20K chips. The life is 4 years.

A GPU prefill pool adds $0.027/M to each row equally. At the market rental of $9.50/GPU-hr, the GPU baseline is
$6.22/M.

## Method

1. **Workload from code** ([docs/01](docs/01_workload.md)). We read the engine kernels, TP layout, padded expert layout, fusions and DSpark speculation from the Rust/CUDA source. Shapes and bytes come from the 48 safetensors headers. These headers reproduce the 552B / 196B / 16B / 8B parameters and the 890 B/token KV of the tech report.
2. **Simulator** ([docs/06](docs/06_simulator.md)). The simulator is an op-level, event-driven scheduler for compute, chunked prioritized HBM and links. Its two policies are GPU kernels and a statically scheduled dataflow with a prefetch window. Platforms differ only in constants. We set same-physics constants equal across platforms: HBM efficiency, DRAM first-byte latency, and the best measured 4-GPU all-reduce.
3. **Calibration.** We fitted 2 free GPU parameters to 2 measured step times. We refitted them under 10 alternative assumptions, which include the run-to-run extremes of the README. The leave-one-out errors are +2.3% / -1.9% with an independent STREAM bandwidth prior. That is a weak test. An adversarial reviewer checked the study two times ([what changed](docs/05_limitations.md#revisions-after-adversarial-review)).
4. **Design and trade study** ([02](docs/02_design_rationale.md), [03](docs/03_architecture.md)). The GPU software, FPGA, SRAM-only, wafer-scale and ASIC options run on one simulator. The MoE router is SystemVerilog. We verified it against a golden model (256/256, 98 cycles). We cross-checked the matrix engine with SCALE-Sim v3. That check corrected our model by 1.6x.
5. **Experiments** ([04](docs/04_results.md)). The experiments are:
   - baseline vs proposed vs software
   - joint Monte Carlo
   - sweeps over chips, batch, context, HBM bandwidth and SRAM
   - an expert-cache study (LRU/LFU/Belady)
   - a tornado
   - an ablation that separates software steps from silicon

## Reproduce

```bash
pip install -r requirements.txt     # numpy, scipy, pyyaml, matplotlib, jinja2, pytest (+ scalesim)
make reproduce                      # all experiments -> results/, renders README + docs from results (~1-2 min)
make test                           # invariants + calibration checks
make rtl                            # router RTL vs golden model (needs iverilog; run by reproduce if present)
python3 -m tools.model_vs_nsys      # our per-kernel-group prediction, to compare with one nsys profile
```

`experiments/render_docs.py` renders each number in this README and `docs/` from `results/*.json`.
Edit `docs/templates/`. Do not edit the generated files.

## Limitations (short version)

This is a modeled projection, not silicon. We calibrated the GPU model on two points from one engine
and one prompt. The fixed-latency share is a range, not a measurement. One `nsys` profile can
confirm or refute it.

The constants of MDA-1 are bottom-up assumptions. We give sources where possible, and we sweep the constants
jointly. Prefill is **not** calibrated: the measured prefill is 5.4x slower than our model.
GPU power, the price of an owned GPU, MAC and SerDes area, NRE and volume are assumptions. Full list:
[docs/05_limitations.md](docs/05_limitations.md).

## Layout

```
data/        HF config, checkpoint manifest (from safetensors headers), reported baseline numbers
configs/hw/  GPU / GPU-software projections / ASIC / FPGA descriptions; every constant keyed to docs/sources.md
sim/         simulator (see docs/06)
experiments/ one script per study; run_all.py drives them
results/     generated JSON + figures
rtl/         MoE top-k router + testbench
docs/        01 workload · 02 rationale · 03 architecture · 04 results · 05 limitations · 06 simulator · sources
tools/       fetch_checkpoint_manifest.py (network), model_vs_nsys.py (profile comparison)
LICENSE      MIT
```

## Acknowledgments

This study uses the public work of Baseten ([deepseek-ultrafast](https://github.com/basetenlabs/deepseek-ultrafast))
and DeepSeek-AI ([DeepSeek-V4.1-Flash](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash) and its technical report).
This study is independent. It is not affiliated with or endorsed by Baseten or DeepSeek-AI.

## License

MIT. See [LICENSE](LICENSE). `data/` includes DeepSeek-V4.1-Flash configuration files (MIT, DeepSeek-AI)
and a manifest derived from the checkpoint headers of the model. This repository includes no code from deepseek-ultrafast.
We quote its measurements with attribution.

## About Aercrist

This study is by [Aercrist](https://github.com/Aercrist). We work on hardware architecture for
AI inference. If you have questions, corrections or a GPU profile for comparison, open an issue on
this repository.
