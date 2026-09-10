# Sample · *Pride and Prejudice*, opening of Chapter 1

An end-to-end run on real prose, not a fixture: unlabelled public-domain text
in, per-character audio and subtitles out. Every number here was measured on
this run.

| | |
|---|---|
| Source | Jane Austen, *Pride and Prejudice* (1813), public domain, via [Project Gutenberg](https://www.gutenberg.org/ebooks/1342) |
| Text | 1,803 characters after cleanup · 35 quoted/prose units · 30 lines |
| Voices | Narrator · Ryan — Mr. Bennet · Aiden — Mrs. Bennet · Vivian |
| Audio | 150.7 s, 24 kHz mono |
| Machine | Mac Studio, Apple M2 Max, 32 GB. Fully offline. |

## Files

| | |
|---|---|
| [`source.txt`](source.txt) | What was pasted in — **no speaker labels** |
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

## The transcribe-back check

Every generated line was transcribed locally and compared with the script.
**8 of 30 flagged, and none of them is a synthesis error:**

| Flag | What it is |
|---|---|
| `neighbourhood` → `neighborhood` | The recogniser normalises to US spelling |
| `bennet` → `bennett` (×3) | Proper noun the recogniser spells differently |
| `let` → `led`, `had` → `did`, `in` → `and` | Recogniser mishearings |
| `is` → `s` | "he is" heard as "he's" |
| `design nonsense` → `d iz ai n onsense` | The recogniser broke down on "Design?" |

So the check has a floor of false alarms set by the recogniser, not by the
synthesiser. British spelling and proper nouns are its weak points here. That
floor is a limitation to know, not a result to hide — the check is there to
catch content the synthesiser silently dropped, and on this passage it found
none.

Word-boundary differences (`Netherfield` → `Nether field`) are recognised as
segmentation artefacts and not reported, which halved the flag count from 16.

## Measurements

| | |
|---|---|
| Attribution, 35 units | **14.8 s** |
| Synthesis, 30 lines → 150.7 s of audio | **51 s · RTF 0.358 · 2.8× real time** |
| Transcribe-back check, 30 lines | **31 s** |
| Human corrections | **1** label, plus two speakers reassigned after cleanup |

The 0.358 real-time factor is for the **preset-voice path**. It is not
comparable to the 0.842 measured for the reference-cloning path in
[AI-Lab](https://github.com/hera2019/AI-Lab) — a different model variant doing
more work per line.

## Known limitations, visible in these files

- **Subtitle cues are long.** One line per cue means 8 of 30 exceed 90
  characters; the longest runs 14.6 s. Splitting them needs word-level timing,
  which this version does not use. Useful as a transcript; not yet as broadcast
  subtitles.
- **English has two preset voices, both male.** Mrs. Bennet is read by a
  Chinese-preset female voice generating English. Its accent was judged
  acceptable by a non-native listener; a native speaker has not assessed it.
- **The audio has not been fully listened to.** Automated checks found no
  missing content. That is not the same as confirming it sounds right.
- The source retains Austen's punctuation. Project Gutenberg's typographic
  markup (`_emphasis_`, `[Illustration: …]`) was removed before synthesis — the
  editor flags both, since they would otherwise be read aloud.

---

Generated by [VoxStage](../../README.md). Synthetic speech throughout; no human
recording was used or imitated.
