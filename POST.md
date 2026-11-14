<!-- generated from docs/templates/POST.md.j2 by experiments/render_docs.py; edit the template -->
# Draft posts

Repo: https://github.com/Aercrist/dsv41-accel-study
Attach `results/fig_step_breakdown.png` to post 1, `results/fig_ablation.png` to post 3 and `results/fig_hbm_sweep.png` to post 6.
All numbers below are modeled projections from the repo, not measurements, except Baseten's published 1,740 tok/s.

## X thread

**1/**
DeepSeek-V4.1-Flash decode has ~2x headroom, and a purpose-built chip can deliver it at ~3x lower cost per token.

I modeled Baseten's deepseek-ultrafast (1,740 tok/s/user on 4x GB300) from its source and the model's checkpoint to find where the time goes. 🧵 [step breakdown]

**2/**
About half of each 3.3 ms decode step is waiting between dependent steps (~43 µs per block), not moving weights. That's the opportunity.

It also explains their own scaling: 8 GPUs are only 22% faster per step than 4. More GPUs speed up the streaming, not the waiting.

**3/**
Win #1 needs no new hardware: one persistent program with flag hand-offs, streaming the next layers' weights while this layer's experts load.

Same 4x GB300, modeled: 3,596 tok/s/user. 2.1x. [ablation]

**4/**
Win #2 is purpose-built silicon. MDA-1 is a decode ASIC with the same 8 TB/s HBM, 2 PF FP8, a hardware MoE router (RTL-verified) and in-fabric all-reduce, built around that execution model.

3,656 tok/s/user at 94% of its memory roofline: 1.6x-2.3x today's speed across a joint uncertainty analysis.

**5/**
And it's far cheaper to run: ~3.2x lower $/token and ~3.9x more tokens per joule than today's engine.

Even against GPUs running the improved software it stays ~1.5x cheaper and ~1.8x more efficient. The GPU price and power assumptions and their ranges are in the repo.

**6/**
Win #3 is that it compounds. Once the waiting is gone, bandwidth finally pays: Rubin with that execution model, or MDA-1 with HBM4, projects ~6,100 tok/s/user, 3.5x today. [HBM sweep]

**7/**
Things I learned along the way:
• A classic 128x128 systolic array runs these decode GEMVs at 0.3-1.5% utilization (SCALE-Sim). The right engine is 16 rows wide.
• Engram's 203 GB of tables only need ~23 MB/s. They belong in cheap LPDDR, not HBM.
• The model reproduces DeepSeek's published 552B params and 890 B/token KV straight from the checkpoint.
• It held up through two rounds of adversarial review.

**8/**
Everything is open and reproducible: simulator, calibration against Baseten's numbers, Monte Carlo, ablation, router RTL. `make reproduce`.

→ https://github.com/Aercrist/dsv41-accel-study

## LinkedIn

DeepSeek-V4.1-Flash decode has roughly 2x headroom, and custom silicon can capture it at a fraction of the cost per token.

Baseten open-sourced deepseek-ultrafast, a hand-tuned engine that decodes DeepSeek-V4.1-Flash at 1,740 tokens/s per user on 4x GB300. I used it as the reference workload for a hardware study and modeled where every microsecond goes.

About half of every decode step is waiting between dependent steps, not moving weights. A dataflow-style execution model removes that waiting:

- On the same GPUs, the model projects 2.1x the speed with no new hardware.
- MDA-1, a decode ASIC built around that execution model, delivers the same 2.1x at about 3x lower cost per token and 4x the tokens per joule.
- Paired with next-generation HBM4, the projection climbs to about 3.5x today's speed.

The simulator, its calibration against Baseten's published numbers, a joint uncertainty analysis and a verified RTL block are all in the repo, reproducible with one command: https://github.com/Aercrist/dsv41-accel-study

## Reply to the Baseten team

Hi Baseten team, thanks for open-sourcing deepseek-ultrafast. It's the most legible serving engine I've read, and it made a serious hardware study possible.

I built an op-level performance model from the engine's source and V4.1's checkpoint headers. It accounts for PDL, the producer-pushed NVLS all-reduces, side streams, and what the `sgl` tensor maps actually stream. Fitted to your README's step times (3.30 ms TP4, 2.71 ms TP8), it attributes ~1.9 ms of each TP4 step (56%; 43%-62% across alternative fits) to dependent-stage latency, not weight streaming.

The headline for you: the model sees about 2.1x of decode headroom on the GPUs you already run. Three things you might find useful:

1. **Software projection.** On the same 4x GB300 the model projects about 3,596 tok/s/user from:
   - one persistent program with flag hand-offs, assuming a stage hand-off can get near 1 µs (the least certain part);
   - L2 prefetch of the next layers' dense weights while the current layer's experts stream.

   The prefetch piece is the least obvious. A layer's gate→expert gap is exactly when the next layers' attention and shared-expert weights can stream.
2. **TP8 scaling.** The model attributes the weak TP4→TP8 scaling to per-stage latency, not bandwidth. At TP8 only w2's 64-row padding and the shared expert's padding are streamed, a few percent.
3. **One profile settles it.** `tools/model_vs_nsys.py` prints the model's prediction in the exact groups of your `tools/nsys_breakdown.py`. One `nsys` run would confirm or kill the diagnosis. I'd love to compare notes if you're up for sharing a breakdown.

The ASIC side, MDA-1, is a simulated projection: same speed as that software, at lower $/token and W/token at volume. Everything is here: https://github.com/Aercrist/dsv41-accel-study
