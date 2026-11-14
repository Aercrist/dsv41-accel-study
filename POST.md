<!-- generated from docs/templates/POST.md.j2 by experiments/render_docs.py; edit the template -->
# Draft posts

Repo link placeholder: `https://github.com/benblaine/dsv41-accel-study` (update once published).
Attach `results/fig_step_breakdown.png` to post 1 and `results/fig_strong_scaling.png` to post 4.

## X thread

**1/**
Baseten's deepseek-ultrafast decodes DeepSeek-V4.1-Flash at 1,740 tok/s on 4x GB300.

I modeled where the time goes. Only ~42% of each 3.3 ms step moves weights. The other 58% is fixed per-layer latency: kernel boundaries + all-reduces.

The HBM sits idle most of the step. 🧵 [step breakdown]

**2/**
That one fact explains their own numbers. 8x B300 is only 22% faster per step than 4x GB300: more GPUs shrink the streaming part, not the 1.9 ms of latency.

Same reason Rubin's 2.75x bandwidth buys only ~37% with today's per-layer overheads (modeled).

**3/**
How I know: an op-level simulator built from the engine's Rust/CUDA source and the checkpoint's safetensors headers. It reproduces DeepSeek's 552B / 16B-active / 890 B-per-token KV exactly.

Calibrated on TP4, it predicts the TP8 step time to within 1.6%.

**4/**
So I designed silicon around the bottleneck: MDA-1, a decode-only ASIC with *the same* 8 TB/s HBM as a B300, a static compiled schedule (no kernels), weight prefetch, a hardware MoE router and in-fabric all-reduce.

Simulated: 4,040 tok/s/user on 4 chips (2.3x), 6,464 on 8 (3.1x the measured 8x B300). [strong scaling]

**5/**
It's not about FLOPs. MDA-1 carries 40% of a B300's compute. The win is converting bandwidth into tokens: HBM 97% busy vs 42%.

Modeled 4.9x tokens/J and 3.8x lower $/M tokens than the same GPUs owned.

**6/**
Things that surprised me:
• A 128x128 systolic array runs decode GEMVs at 0.3-1.5% utilization (SCALE-Sim). The engine has to be 16 rows wide.
• Caching experts in SRAM is a dead end. It needs GBs per chip.
• Engram's 203 GB of tables need ~23 MB/s. Put them in LPDDR.

**7/**
Software headroom is real too: an ideal GPU stack bounds at 3,151 tok/s on the same 4 GPUs. Silicon pulls ahead as you scale out (1.51x at 8 chips) and on energy and cost.

Everything is open: simulator, calibration, tornado, ablation, RTL. `make reproduce`.
→ https://github.com/benblaine/dsv41-accel-study

## LinkedIn

Baseten open-sourced deepseek-ultrafast, a hand-tuned engine that decodes DeepSeek-V4.1-Flash at 1,740 tokens/s per user on 4x GB300. I used it as the reference workload for a hardware study.

The headline: about 58% of every decode step is fixed per-layer latency, not memory bandwidth. It explains why 8 GPUs are only 22% faster than 4.

Designing around that, a decode-only ASIC with the same HBM bandwidth as a B300 projects 4,040 tokens/s per user on 4 chips and 6,464 on 8. That's 4.9x the tokens per joule, from a statically scheduled pipeline, a hardware MoE router and in-fabric collectives.

Simulator, calibration against Baseten's published numbers, sensitivity analysis and a verified RTL block are in the repo, reproducible with one command. All MDA-1 numbers are modeled projections.

## Reply to the Baseten team

Hi Baseten team, thanks for open-sourcing deepseek-ultrafast. It's the most legible serving engine I've read, and it made a serious hardware study possible.

I built an op-level performance model from the engine's source and V4.1's checkpoint headers. Calibrated to your README's step times (3.30 ms TP4, 2.71 ms TP8), it predicts one configuration from the other within ~1.6%.

It says about 1.9 ms of each 3.30 ms step is fixed per-layer latency: roughly 44 µs per block across ~13 dependent kernels and 2 all-reduces. HBM averages ~37% of peak over the step.

Two things you might find useful:

1. The model puts the software ceiling on the same 4x GB300 at about 3,151 tok/s: persistent kernel, cross-layer L2 prefetch of the next layers' attention/shared weights while experts stream, and a ~2.4 µs all-reduce. The prefetch piece is the least obvious. Next-layer dense weights can stream during the current layer's gate→expert gap.
2. One `nsys` run through your `tools/nsys_breakdown.py` would confirm or kill the diagnosis. I'd love to compare notes if you're up for sharing a breakdown.

The ASIC side, MDA-1, is a simulated projection: 4,040 tok/s/user on 4 chips at iso-HBM bandwidth. Everything is in the repo: https://github.com/benblaine/dsv41-accel-study
