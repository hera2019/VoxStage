# VoxStage

A local script-to-voice workspace for Apple Silicon Macs. Turn a labelled
script into per-sentence audio you can audition, redo and export — with the
source text guaranteed intact.

> **Development preview.** The workflow runs end to end. It is not a released
> product, and one quality criterion has explicitly **not** passed — see
> [Open quality issue](#open-quality-issue).

*[中文说明](README.zh-CN.md)*

---

## What it does

Give it a script where each line is `Speaker: sentence`:

```
旁白：雨点轻轻敲着窗。
小林：你听见了吗？
阿宁：别担心，那只是风。
```

Assign a voice per speaker, generate, then work sentence by sentence — listen,
redo the ones you dislike, adjust timing, export. Chinese and English are both
supported today.

Output: a WAV, an SRT built from the actual audio samples, and a content-check
report.

## Why not just use a TTS tool

Four properties, each a deliberate design choice rather than a feature:

**Your text is never rewritten.** Analysis and checks may *annotate* text; only
you change it. Reading adjustments (how a number or abbreviation is spoken)
live in a separate field, so subtitles keep your original wording.

**Changing one sentence regenerates one sentence.** Every segment has a stable
identity and a generation fingerprint covering the exact text sent to the
engine, the voice and the parameters. Editing line 40 of 400 leaves the other
399 audio files untouched — verified by comparing bytes and modification times,
not by assumption.

**Generated speech is transcribed back and compared to the script.** Text-to-speech
can drop words while sounding completely natural — [we measured a case where 17%
of a passage vanished inaudibly](#where-this-came-from). So finished audio is
transcribed locally and diffed against what was supposed to be said.
Disagreements are flagged for your ear, never auto-corrected.

**Nothing leaves the machine.** Models run locally on Apple Silicon. No account,
no cloud generation, no per-character billing. Scripts and reference audio stay
in your own files and never enter version control.

## Quick start

On a configured Mac, double-click **Start VoxStage.command**. Use
**Check VoxStage.command** for an environment report that downloads nothing.

Chinese walkthroughs: [第一次试用](docs/public/quickstart-zh.md) ·
[环境与模型准备](docs/public/setup-zh.md)

From a fresh checkout (Python 3.12, uv and Node.js required):

```sh
uv venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.lock.txt
cd frontend && npm ci && npm run build && cd ..
.venv/bin/python scripts/setup_model.py      # ~2.5 GB, pinned revision
.venv/bin/python -m runtime.launcher
```

For the content check, install a compatible `whisper-cli`, then
`scripts/setup_asr.py --cli <path>` (~547 MiB, SHA-256 verified).

This is a developer setup, not a consumer installer.

## A finished sample

[*Pride and Prejudice*, opening of Chapter 1](examples/pride-and-prejudice-ch1/) —
unlabelled public-domain prose in, three-character audio and subtitles out, run
end to end on one Mac. Attribution made **one mistake in 35 units**, and the
sample says which one and why that particular kind of mistake matters. Timings,
the transcribe-back results and the known limitations are all in that folder.

## What works today

| Capability | State |
|---|---|
| Import, edit, save, reload, undo/redo | Automated checks pass |
| One audio asset per sentence; edit one → regenerate one | Automated checks pass |
| Per-sentence retake, keeping the previous take | Automated checks pass |
| Failed sentence recorded, batch continues, retry works | Automated checks pass |
| WAV + SRT export from actual sample counts | Automated checks pass |
| Chinese and English preset voices, real model | Integration run recorded |
| Transcribe-back content check | Implemented; detection rate not measured |
| Voice library: keep a take, or supply a recording | Used in the sample; broader listening pending |
| Waveform editing, clip reorder/split, speed | Implemented; listening review pending |
| Speaker attribution from unlabelled prose | Evaluated, **not integrated** |

Every row links to a run under [`results/`](results/), recorded as both
Markdown and JSON. Acceptance criteria were written **before** implementation:
[`docs/public/acceptance.md`](docs/public/acceptance.md).

## Open quality issue

**Same-speaker continuity has not passed listening review.** Two narrator lines
from the same character were judged insufficiently consistent in perceived
voice and acoustic space. Fixing a preset ID and a seed is not sufficient, and
matching waveform metrics do not satisfy this criterion.

This is the current primary issue, and it matters more than any feature above:
a multi-character reading is only usable if a character still sounds like
themselves in sentence 300. It is tracked in
[`acceptance.md`](docs/public/acceptance.md) and is **not** claimed as working.

## Where this came from

VoxStage grew out of a local-model study that found a specific failure: a
voice-cloning run reproduced a passage naturally and recognisably while
silently skipping 40 characters from the middle. Nobody could hear it — the
skipped span still read as a fluent sentence.

Two design rules follow directly, and both are in the product:

- **Generate sentence by sentence.** Long-form generation is where the skip
  occurred; short segments also give per-sentence caching and subtitle timing.
- **Transcribe back and compare.** A silent failure cannot be caught by
  listening. Only a check that can disagree with the output will find it.

Full record: [AI-Lab / voice cloning verification](https://github.com/hera2019/AI-Lab/blob/main/qwen3-tts-0.6b-voice-clone-mlx/results/phase-1-iphone-repeat-verification.md)

## Speaker attribution: measured, not shipped

For unlabelled prose, a local model can propose who says what. Measured on 20
self-written bilingual scenes with two local models, using a pipeline where the
program — not the model — reconstructs the text:

| | Qwen3 4B Q8 | Qwen2.5 1.5B Q4 |
|---|---:|---:|
| Source text preserved (guaranteed by the program) | 20/20 | 20/20 |
| Explicit dialogue attributed correctly | 34/40 | 15/40 |
| Ambiguous lines correctly marked UNKNOWN | 4/4 | 1/4 |
| **Entire scene fully correct** | **8/20** | 1/20 |

That last row is the one that decides product behaviour. **Roughly 60% of
scenes need human correction**, so attribution ships as *an editable draft for
review*, never as unattended batch generation. The 20/20 text preservation is
the program's doing, not the model's.

Reference answers were drafted by the assistant before the models ran and have
not been independently reviewed; 16 of the 20 scenes had been seen in an
earlier baseline. This is engineering evidence for a selection decision, not a
generalisation claim. Corpus, prompts and scoring:
[`evals/speaker_attribution/`](evals/speaker_attribution/) · results:
[`results/speaker-attribution-summary.md`](results/speaker-attribution-summary.md)

## Limits

- Speakers come from you. Attribution is not wired into the app yet.
- Nine preset voices, two of them English and both male. A voice library lifts
  that ceiling: keep a take you liked under a name, or supply your own recording
  after confirming you may. Either way the reference stays on the machine and
  out of version control, and a supplied recording is never labelled synthetic.
- Subtitles use energy-based speech boundaries — estimates that need review,
  not forced alignment.
- Peak normalisation, not loudness-standard compliance.
- Cancellation takes effect between sentences.
- Mac only. No LAN pairing, mobile access, installer signing or updates.
- Content-check matching ignores ordinary punctuation and case but keeps
  negation, numbers and meaningful symbols. Homophone and number-wording
  differences cause false alarms. **No accuracy percentage is claimed** — it has
  not been measured.

## Ethics

- No human reference-audio upload path exists. Fixed character voices are built
  from the model's own synthetic output, stored with checksums and the text
  that produced them.
- Generated audio is never presented as a real person.
- Scripts you supply remain your responsibility with respect to content rights.

## Checks

```sh
.venv/bin/python tests/run_checks.py
cd frontend && npm run build
HF_HUB_OFFLINE=1 .venv/bin/python tests/real_model_check.py   # writes local audio
```

## Licence

[Apache-2.0](LICENSE). The speech model's licence is separate and is recorded
next to the downloaded weights — do not infer this application's licence from
it, or the reverse.

---

Built on Apple Silicon with llama.cpp, MLX and whisper.cpp.
Companion research: [hera2019/AI-Lab](https://github.com/hera2019/AI-Lab)
