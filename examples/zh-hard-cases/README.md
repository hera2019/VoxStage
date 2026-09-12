# Sample · Chinese, written to be difficult

The English sample is real prose taken as it comes. This one is the opposite: a
short scene **written to stack the cases that attribution is known to get
wrong**, so the failures are visible rather than waiting to be discovered.

Self-written, so no copyright question. Four characters in 440 characters of
text.

| | |
|---|---|
| Text | 440 characters · 37 quoted/prose units · 29 lines |
| Voices | 旁白 Serena — 林小雪 Vivian — 周远 Dylan — 张师傅 Uncle_Fu |
| Audio | 114.9 s, 24 kHz mono |
| Machine | Mac Studio, Apple M2 Max, 32 GB. Fully offline. |

## Files

| | |
|---|---|
| [`source.txt`](source.txt) | What was pasted in — **no speaker labels** |
| [`script.txt`](script.txt) | After attribution and human review |
| [`full.mp3`](full.mp3) | The finished audio |
| [`subtitles.srt`](subtitles.srt) · [`timeline.json`](timeline.json) | Built from actual sample counts |
| [`content-check.json`](content-check.json) | Every line transcribed back and compared |

## The cases it was built to break

Eight, all present in 440 characters:

| Case | In the text |
|---|---|
| Trailing attribution | `“我们约好的。”林小雪说。` |
| Unattributed alternation | `“盘点呢。” / “我们约好的。” / “约好的也得等。”` |
| Three speakers present | 林小雪, 周远, 张师傅 |
| Referred to, not named | 那姑娘 · 她 · 门后的人 |
| Written text, nobody speaking | the notice `“今日盘点，暂停营业”` |
| Inner thought | `他想，这人怕是记错了日子。` |
| Split quotation | `“可门关着。”周远把手插进口袋，“我早说了先打个电话。”` |
| Numbers and a Latin abbreviation | `三百二` · `一千零八十` · `CD 机` |

## What it got right

**The trailing attribution, which has failed twice before.** `林小雪说。`,
`她问。`, `张师傅翻了翻本子，` and `张师傅说完又补了一句，` were all labelled
narration. The same construction was mislabelled in the earlier Chinese
evaluation and again in the English sample; here it held.

Also correct: the split quotation with both halves going to 周远; the inner
thought as narration; and `“雪”` — a single quoted character inside prose,
describing ink on a page rather than anyone speaking — correctly **not**
treated as dialogue.

## What it got wrong, and which mattered

**One character got two names.** The man behind the door is labelled 门后的人 in
his first two lines and 张师傅 once his name appears. Both are right in ordinary
reading. For synthesis they are a defect: two names mean two characters, two
voice assignments and **the same person speaking in two different voices**.

This is why the review screen lists every name it saw and asks for one name per
person. It is also the correction most easily missed, because nothing about it
looks wrong.

The other two were flagged rather than guessed:

- The notice on the door came back as dialogue by UNKNOWN. Wrong type, but
  marked for review, so it was caught.
- `“是。”`, a bare one-word answer, came back UNKNOWN. Either character could
  have said it, so abstaining is a reasonable answer.

**Four corrections in total: one type, one abstention resolved, two names
unified.** No line needed its text changed.

## The transcribe-back check reads differently in Chinese

Two lines of 29 flagged: `远`→`元` and `约`→`越`. Both are near-homophones
differing only by tone, and neither is a synthesis error — the recogniser wrote
a different character for something read correctly.

Seven differences passed silently, and what tolerates them is worth separating:

| Basis | Count | Example |
|---|---|---|
| Same pinyin and tone | 5 | `他`/`她` |
| Same number, different writing | 2 | `三百二`/`320`, `一千零八十`/`1080` |

**The number row was a reported failure in the first run of this sample.**
Nothing had been misread: `三百二` was spoken correctly and transcribed as
`320`, and comparing written forms flagged it every time. The fix went into the
comparison rather than the voice. It is shown as a visible tolerance rather than
a silent pass, because normalising `一千八十` and `一千零八十` to the same value
also hides a genuinely dropped `零`.

Zero duration anomalies in this run.

## Measurements

| | |
|---|---|
| Attribution, 37 units | **15.1 s** |
| Synthesis, 29 lines → 114.9 s of audio | **47 s** |
| Transcribe-back check, 29 lines | **28 s** |
| Human corrections | **4** labels, no text changes, no retakes |

## Subtitles are shorter here than in English

Subtitles are not the segments. The 29 lines of audio become **44 cues**, cut
where the voice actually stops rather than where the script has a full stop,
then stripped of what a screen does not need — quotation marks and sentence-final
punctuation go, commas become spaces, and `？` and `！` stay because losing them
changes how a line reads.

| | |
|---|---|
| Longest line | **15 characters** |
| Lines per cue | 1 |
| Cue length | 0.5 – 3.1 s |

Before this, one cue ran 41 characters over 8.9 seconds and overflowed the frame.
A segment has to serve a voice, which wants whole sentences; a cue has to serve a
reader, who has two seconds. They are now separate objects, and the timing comes
from measuring the silences in the finished audio.

## Known limits

- **Nobody has listened to all of it.** Automated checks found no missing
  content, which says nothing about how it sounds.
- Four characters, four presets — Chinese has exactly four, so a fifth character
  would have to share or use a kept voice.
- Half-width punctuation mixed into Chinese text is **not** currently detected by
  the script checker, though it affects both splitting and reading. This text
  uses full-width throughout, so the sample does not exercise it.

---

Generated by [VoxStage](../../README.md). Synthetic speech throughout; no human
recording was used or imitated.
