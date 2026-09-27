# VoxStage

A local script-to-voice workstation for Apple Silicon Macs. Paste prose as
it is written — a chapter, no speaker labels — and get a multi-character
reading you can audition line by line, correct, redo and export, with every
line transcribed back and checked against its text, and the source text
guaranteed intact.

> **Development preview.** The workflow runs end to end. It is not a released
> product, and listening review covers specific things and not others — see
> [What listening has covered](#what-listening-has-covered).

*Also available in Chinese: [中文说明](README.zh-CN.md)*

---

## What it does

Give it prose as it is written:

```
Mr. Bennet made no answer.
“Do not you want to know who has taken it?” cried his wife, impatiently.
“_You_ want to tell me, and I have no objection to hearing it.”
```

A local model labels each unit narration or dialogue and names the speaker,
and hands you the draft to correct — in the evaluation below most scenes
needed a correction, so the review is the product, not a formality. A script
already written as `Speaker: line` skips the draft. Then assign a voice per
character, generate, and work line by line — listen, redo, split, merge, set
the pauses — and export. Chinese and English are both supported today; a text
longer than a chapter is kept as a book: one sub-project per chapter, the
book's voices and settings inherited by every chapter unless a chapter
overrides them, and the whole book exported in one go.

Output: the full audio (WAV, and MP3 when ffmpeg is installed); subtitles (SRT
and VTT) cut where the voice pauses and timed from the actual samples; a
timeline; a delivery package of one file per line for an editor, with an FCP7
XML timeline; and the content-check report.

## Why not just use a TTS tool

Six properties, each a deliberate design choice rather than a feature:

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

**The work is done before you open the editor.** Cutting a text into lines,
deciding who speaks, keeping a book's cast and aliases from chapter to
chapter, carrying settings forward — these are the program's job, and the
target is that reviewing a draft means confirming, not typing. Where the
program is unsure it says so, in yellow; where it has no idea, in orange; and
it learns from every correction you make on the page. A local model is not an
excuse to hand the editing back to the person.

**Models are parts, not the product.** The speaker-draft model, the speech
engine and the recogniser are each behind an interface with an identity that
reaches the generation fingerprint, pinned by hash and chosen in settings; the
draft model is already switchable, and a second engine or recogniser is meant
to plug in the same way rather than be built in.

## Quick start

On a configured Mac, double-click **Start VoxStage.command**. Use
**Check VoxStage.command** for an environment report that downloads nothing.

On a new Mac, follow **[Installing VoxStage](docs/public/setup.md)**: what
the Mac needs (Apple Silicon; 16 GB for the small models, 32 GB recommended),
the tools, which models to download for your memory, and how to start. In
short:

```sh
brew install python@3.12 uv node git ffmpeg llama.cpp
uv venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.lock.txt
npm --prefix frontend ci && npm --prefix frontend run build
.venv/bin/python scripts/setup_model.py      # built-in voices, ~2.5 GB; the guide lists the rest
.venv/bin/python -m runtime.launcher
```

The interface is in English or Chinese (the switch is at the bottom of the
sidebar). Then [the first run](docs/public/quickstart.md): from a passage of prose to a
multi-voice recording. Every model is Apache-2.0 and pinned to a revision;
nothing leaves the Mac.

## Three finished samples

[*Pride and Prejudice*, opening of Chapter 1](examples/pride-and-prejudice-ch1/) —
unlabelled public-domain prose in, three-character audio and subtitles out, run
end to end on one Mac. Attribution made **one mistake in 35 units**, and the
sample says which one and why that particular kind of mistake matters. Timings,
the transcribe-back results and the known limitations are all in that folder.

[A Chinese scene written to be difficult](examples/zh-hard-cases/) — the
opposite approach: four characters in 440 characters of text, built to stack the
cases attribution is known to get wrong. It caught the trailing attribution that
had failed twice before, and gave one character two names, which for synthesis
means one person speaking in two voices.

[Lu Xun's *Kong Yiji*](examples/kong-yiji/) — a whole story, ten minutes, and a
century old. The model named the right speaker every time it named one, and still
needed 43 corrections, because it kept labelling four-character prose like `掌柜说：`
as speech. The engine cannot read two 1938 character forms; the duration check caught
a twelve-character line that came out at thirteen seconds; the transcribe-back
check learned that it cannot expect a recogniser to know a character's name; and
three of the five voices — the narrator among them — were designed from a written
sentence after the author rejected every preset for the part.

## What works today

| Capability | State |
|---|---|
| Paste unlabelled prose → speaker draft → review → project, in one flow | Built all three samples; the draft's post-rules are measured on human-labelled projects (the citation rule: 0 spoken lines silenced in 376 quoted units across 14 projects, after its first form silenced 21) |
| A coloured Word manuscript (.docx): each colour asked once, the author's marks used as they are, the model never asked; headings kept and not read | A 76-paragraph, six-colour manuscript: 80 lines in 0.0 s, speakers exactly as coloured |
| A long text kept as a book: one sub-project per chapter; voices, models, pauses, lexicon and cast set once on the book and inherited by every chapter unless a chapter overrides them; a name renamed once for the whole book; chapters split, merged, reordered, attached or detached with a plan shown first and the old project kept as a snapshot; names and aliases confirmed earlier are known later | 阿Q正传, 22,152 characters into ten chapters, checked in the browser; the structure operations and the whole-book export verified on a throwaway server with a self-written three-chapter text and the real 30B model |
| A chapter's speaker draft made in batches sized to the machine and the model, resumable after a failure, then reviewed and confirmed in place | End to end in the browser, 2026-09-21 |
| The whole book exported at once — MP3, WAV, subtitles, timeline, XML, package, report — with a chosen pause between chapters; the last batch stays downloadable and is marked stale once the book changes | Automated checks pass; a real-book export is the author's next check |
| Review page in three tiers — named, filled in yellow, orange to choose — with rules beside the model: a speech tag names its speaker (and the person after 对/见/望着 is the one spoken to), a character spoken to is not the speaker, two lines running are seldom one person's, a line that reads like the other sex's is not this speaker's, a speaker the story never names (有的叫道, 旁人问道) gets a stand-in renamed once; rules relay only within one exchange and learn only from lines you settled; a character's sex is set on the voices page, apart from the voice; a settled name re-scores the rest | On a private two-chapter text of the author's, agreement with their own labels went from 25/32 to 31/33; Kong Yiji from raw text: the author's first review changed 13 lines in 21 minutes, and with the rules since, the same text drafts with none orange and none wrong: renaming the three stand-ins once each (众人 and 一个喝酒的人 to 酒客, 某人 to 孔乙己) matches all 35 of the author's labels (three renames, by estimate; not yet re-reviewed by the author) |
| One character, many voices: a crowd drawn from a tagged pool line by line | Automated checks pass; never the same voice twice running |
| Colours per character, settings templates, tags on voices, continuous listening | In use by the author |
| Import, edit, save, reload, undo/redo | Automated checks pass |
| One audio asset per sentence; edit one → regenerate one | Automated checks pass |
| Split a line where the cursor is; merge with a neighbour; leave a line out of the recording | Automated checks pass; used on the Chinese samples |
| Per-sentence retake; run-away takes retried once before anyone hears them | Automated checks pass; four run-away takes caught on 2026-09-13 |
| Transcribe-back content check with visible tolerances (pinyin, numbers, known names, period particles) | Used on every sample; the tolerances are listed per sample |
| Duration check for sound the engine added | Caught a 16-character line rendered as 31.7 s |
| Subtitles cut where the voice pauses, wrapped for a screen, VTT and SRT in step | All three samples; longest line 20 / 42 characters |
| Portable delivery package rebuilding full.wav to the sample; FCP7 XML at 24–60 fps | Zero-sample rebuild verified; imported into DaVinci Resolve 21 |
| 0.6B and 1.7B preset models, chosen per project; pronunciation lexicon | Measured 2026-09-13; the author judged 1.7B more natural |
| Voice library: keep a take, design a voice from a description, or supply a recording | Three designed voices carry the Kong Yiji sample; consent gate for supplied recordings is in code |
| Waveform editing, clip reorder/split, speed | Implemented; listening review pending |

Every row links to a run under [`results/`](results/), recorded as both
Markdown and JSON. Acceptance criteria were written **before** implementation:
[`docs/public/acceptance.md`](docs/public/acceptance.md).

> Most verification records under `results/` are written in Chinese, since that
> is the language this was built in. The documents linked from this page —
> acceptance criteria and the attribution evaluation — are in English, and every
> record has a machine-readable JSON companion beside it.

## What listening has covered

**Same-speaker continuity was accepted on 2026-09-10.** Six consecutive
narrator lines per language, about 32 seconds each, one take per line at a
fixed seed with no selection among takes; the author judged timbre, acoustic
space, pronunciation and completeness consistent in both languages. The day
before, the same criterion had failed on two lines — that record stays in
[`acceptance.md`](docs/public/acceptance.md) next to the pass and its scope:
two presets, no retake, no span beyond 32 seconds, no seed change. A character
still sounding like themselves in sentence 300 is not claimed.

**Not listened to:** the published *Kong Yiji* sample line by line — the author
chose its voices by ear and confirmed one line, the rest is checked by machine
only; the 1.7B model beyond the lines the author compared on 2026-09-13. A file
that exists is not a file that has passed.

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

## Speaker attribution: measured, then shipped as a draft

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
generalisation claim. The draft has since been wired into the app, with
program-side rules on top of the model that are measured in the table above.
The prompt now asks the model for its best judgement of every speaker plus
whether the passage settles it; an unsettled name reaches the reviewer as a
yellow pre-filled suggestion, and a line the model cannot place at all may be
filled from the way that character talked in chapters already confirmed. On
the same 20 scenes the best-judgement prompt names 33–34 of 40 explicit
speakers; its extra kind errors are all unquoted units, which the quote rule
repairs. Corpus, prompts and scoring:
[`evals/speaker_attribution/`](evals/speaker_attribution/) · results:
[`results/speaker-attribution-summary.md`](results/speaker-attribution-summary.md)

The September 2026 round — eight local models on eleven reviewed texts
including a blind chapter, the rules measured one by one against a frozen
set of model answers, and the blind listening that chose the cloning model —
is recorded with its scoring and its limits in
[`docs/public/evaluation.md`](docs/public/evaluation.md)
([中文](docs/public/evaluation-zh.md)).

## Limits

- The speaker draft is a draft. Most scenes in the evaluation needed at least
  one correction, so the review step cannot be skipped. A chapter is drafted
  in batches of 3,000 / 6,000 / 12,000 characters on a 16 / 32 / 64 GB Mac
  (fewer with the 30B model, which is capped at 100 units a batch), and a
  text longer than a chapter is cut into chapters first.
- Nine preset voices, two of them English and both male. A voice library lifts
  that ceiling: keep a take you liked under a name, or supply your own recording
  after confirming you may. Either way the reference stays on the machine and
  out of version control, and a supplied recording is never labelled synthetic.
- Subtitles use energy-based speech boundaries — estimates that need review,
  not forced alignment.
- Peak normalisation, not loudness-standard compliance.
- Cancellation takes effect between sentences.
- Mac only; no installer signing or updates. The service listens on this
  machine alone unless started with `--lan`, which opens it to the local
  network behind a key typed once per device (the browser keeps it); recording
  from a phone is not possible over plain HTTP, so a phone supplies a
  recording as a file instead.
- Content-check matching ignores ordinary punctuation and case but keeps
  negation, numbers and meaningful symbols. Homophone and number-wording
  differences cause false alarms. **No accuracy percentage is claimed** — it has
  not been measured.

## Ethics

- Fixed character voices are built from the model's own synthetic output,
  stored with checksums and the text that produced them. A recording you
  supply is accepted only after you confirm you have the right to use it — the
  gate is in the library code, not only a checkbox on the screen — and is
  stored as `synthetic_audio: false`, `consent_confirmed: true`, on this
  machine and outside version control.
- Generated audio is never presented as a real person.
- Scripts you supply remain your responsibility with respect to content rights.

**Responsible use.** Obey the laws where you are and respect other people's
privacy and likeness. Do not use VoxStage to make sexual content involving
minors, intimate or sexual material of anyone without their consent,
fraudulent impersonation, harassment, extortion, or anything else unlawful.
You are responsible for how you use the models and what you generate.

## Checks

```sh
.venv/bin/python tests/run_checks.py
cd frontend && npm run build
HF_HUB_OFFLINE=1 .venv/bin/python tests/real_model_check.py   # writes local audio
```

## Licence

Copyright © 2026 Houjun Co., Ltd. VoxStage is available under the
[GNU AGPL-3.0](LICENSE) (AGPL-3.0-only) or, for closed-source or hosted use
that cannot meet it, under a commercial licence — see
[LICENSING.md](LICENSING.md); contact support@houjun.dev. Contributions:
[CONTRIBUTING.md](CONTRIBUTING.md). The speech and language models are
downloaded separately and keep their own licences (Apache-2.0), recorded next
to the weights — do not infer this application's licence from them, or the
reverse.

---

Built on Apple Silicon with llama.cpp, MLX and whisper.cpp.
Companion research: [hera2019/AI-Lab](https://github.com/hera2019/AI-Lab)
