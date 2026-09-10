# Sample · *Pride and Prejudice*, opening of Chapter 1

An end-to-end run on real prose, not a fixture: unlabelled public-domain text
in, per-character audio and subtitles out. Every number here was measured on
this run.

| | |
|---|---|
| Source | Jane Austen, *Pride and Prejudice* (1813), public domain, via [Project Gutenberg](https://www.gutenberg.org/ebooks/1342) |
| Text | 1,842 characters as pasted → 1,755 after removing typographic apparatus · 28 lines |
| Voices | Narrator · Ryan — Mr. Bennet · Aiden — Mrs. Bennet · Vivian |
| Audio | 144.7 s, 24 kHz mono |
| Machine | Mac Studio, Apple M2 Max, 32 GB. Fully offline. |

## Files

| | |
|---|---|
| [`source.txt`](source.txt) | What was pasted in — **no speaker labels**, Gutenberg markup intact |
| [`script.txt`](script.txt) | What came out of attribution and human review |
| [`full.mp3`](full.mp3) | The finished audio (WAV was exported; MP3 here for size) |
| [`subtitles.srt`](subtitles.srt) | Built from actual sample counts, not estimates |
| [`timeline.json`](timeline.json) | File boundaries and estimated speech boundaries, separately |
| [`content-check.json`](content-check.json) | Every line transcribed back and compared |

## What the attribution got right

Across 35 units the local model returned **no UNKNOWN and made one mistake**.
It handled the cases that make prose hard:

- **Split quotations.** `"My dear Mr. Bennet," said his lady to him one day,
  "have you heard…"` — both halves attributed to the same speaker.
- **Indirect reference.** "his lady" and "his wife" were resolved to *Mrs.
  Bennet*, a name that appears elsewhere in the passage but not in those lines.
- **Unattributed alternation.** `"What is his name?" / "Bingley." / "Is he
  married or single?"` carries no attribution at all; the alternation was
  tracked correctly.
- **Reported speech.** "Mr. Bennet replied that he had not." is narration, not a
  quoted line, and was labelled as such.

## The one it got wrong — and why it matters

`" cried his wife, impatiently."` was labelled as speech by Mrs. Bennet. It is
narration: a trailing attribution that closes the line before it.

Left uncorrected, the audio would have had Mrs. Bennet say the words "cried his
wife, impatiently."

This is the same failure recorded in the Chinese evaluation
([`results/speaker-attribution-summary.md`](../../results/speaker-attribution-summary.md)),
reproduced in English on unseen text. It matters more than a stray error because
of *how* it fails: the model reported it **confidently**, not as UNKNOWN. The
review screen highlights UNKNOWN; a confident mistake looks like every other
line. It is the kind of error a human reviewer is most likely to miss.

That is the argument for shipping attribution as an editable draft rather than
as unattended batch generation.

## Two checks, two opposite failures

Synthesis can fail in both directions, and one check cannot see both.

**Too little — words silently dropped.** Every line is transcribed locally and
compared with the script. **8 of 28 flagged, none of them a synthesis error:**

| Flag | What it is |
|---|---|
| `neighbourhood` → `neighborhood` | The recogniser normalises to US spelling |
| `bennet` → `bennett` (×3) | Proper noun the recogniser spells differently |
| `let` → `led`, `had` → `did`, `in` → `and` | Recogniser mishearings |
| `design nonsense` → `d iz ai n onsense` | The recogniser broke down on "Design?" |

The check therefore has a floor of false alarms set by the recogniser, not by
the synthesiser. British spelling and proper nouns are its weak points. Word
boundary differences (`Netherfield` → `Nether field`) are treated as
segmentation artefacts and not reported, which halved the flag count.

**Too much — sound added that is not in the text.** "Mr. Bennet replied that he
had not." first came out at **7.68 s of speech for seven words**, more than
twice its natural length, and audibly wrong. Transcription did not catch it:
the words were all there.

A duration check flagged it — 1 of 28, no false positives — and one retake
brought it to **3.44 s**. The cause is sampling, not the text: the same line at
four different seeds gave 6.72 s, 5.24 s, 2.86 s and 2.48 s. So the remedy is
a retake, and the flag says so.

## Measurements

| | |
|---|---|
| Attribution, 35 units | **14.8 s** |
| Synthesis, 28 lines → 144.7 s of audio | **51 s · RTF 0.358 · 2.8× real time** |
| Transcribe-back check, 28 lines | **28 s** |
| Human corrections | **1** label, 2 speakers reassigned after cleanup, **1** retake |

The 0.358 real-time factor is for the **preset-voice path**. It is not
comparable to the 0.842 measured for the reference-cloning path in
[AI-Lab](https://github.com/hera2019/AI-Lab) — a different model variant doing
more work per line.

## Known limitations, visible in these files

- **Subtitle cues are long.** One line per cue means 8 of 28 exceed 90
  characters; the longest runs 173. Splitting them needs word-level timing,
  which this version does not use. Useful as a transcript; not yet as broadcast
  subtitles.
- **English has two preset voices, both male.** Mrs. Bennet is read by a
  Chinese-preset female voice generating English. Its accent was judged
  acceptable by a non-native listener; a native speaker has not assessed it.
- **Short narration fragments read slowly.** The attributions between split
  quotations (" said his lady to him one day,") are 15–30 characters and come
  out at roughly half the delivery rate of full sentences, which reads as an
  oddly heavy tone. It follows from giving narrator and character separate
  voices, and is not solved here.
- **The audio has not been fully listened to.** Automated checks found no
  missing content. That is not the same as confirming it sounds right.

## What the editor removed before synthesis

Project Gutenberg's plain text carries apparatus a reader would never speak.
`source.txt` keeps it so the sample shows the real starting point:

- `_emphasis_` underscores — read out one character at a time
- `[Illustration: … [_Copyright 1894 by George Allen._]]` — removed as a whole
  block, caption included. Stripping only the brackets leaves the caption
  behind as a stray quoted line that then has to be attributed to somebody.

---

Generated by [VoxStage](../../README.md). Synthetic speech throughout; no human
recording was used or imitated.
