# Sample · 孔乙己 (Lu Xun, 1919)

The other two samples are short. This one is a whole story — Lu Xun's *Kong Yiji*,
2,613 characters, eleven minutes of audio — and it was chosen for being hard in the
ways that matter: dense dialogue with no speaker named, a crowd that talks, a
narrator who is also a character, and a century-old text full of words and
character forms a modern model has not seen.

Public domain: Lu Xun died in 1936. Text from Wikisource (the 1938 *Complete Works*
edition); the edition's 『』 quotation marks are written as “” here, nothing else is
changed.

| | |
|---|---|
| Text | 2,613 characters · 68 quoted/prose units · 93 lines |
| Voices | 旁白 Aiden (an English preset) — 我 and 孔乙己 two voices cloned from the English preset Ryan — 掌柜 Uncle_Fu — 酒客 Dylan |
| Audio | 694.6 s, 24 kHz mono |
| Subtitles | 251 cues, longest line 20 characters |
| Machine | Mac Studio, Apple M2 Max, 32 GB. Fully offline. |

## Files

| | |
|---|---|
| [`source.txt`](source.txt) | What was pasted in — **no speaker labels** |
| [`script.txt`](script.txt) | After attribution and review; lines read with a replacement text say so |
| [`full.mp3`](full.mp3) | The finished audio |
| [`subtitles.srt`](subtitles.srt) · [`timeline.json`](timeline.json) | Cut on the pauses in the audio, timed from actual sample counts |
| [`content-check.json`](content-check.json) | Every line transcribed back and compared |

## Attribution: the model never named the wrong person, and still needed 43 corrections

Of 68 units, the model named a speaker for 19 quoted lines and **all 19 were right**.
Its failures were of other kinds:

| What it did | Count | Example |
|---|---|---|
| Labelled a prose unit as speech, with the speaker of the quote beside it | **24** | `掌柜说：` → dialogue, 掌柜 |
| Labelled a quoted phrase inside narration as speech | 3 | `“上大人孔乙己”`, `“君子固穷”` |
| Abstained (UNKNOWN) on a line whose speaker is only implied | 16 | `“后来怎么样？”` — the shopkeeper asking |

The first row did not appear in the [self-written sample](../zh-hard-cases/), where
prose between quotes is a full sentence. Here it is often four characters — `掌柜说：`,
`他说，` — and the model treats them as part of the utterance. That is a hypothesis
about why; the count is a measurement.

Review followed three stated rules, applied to every unit and recorded in the
project: a unit that does not open with a quotation mark is narration; three quoted
phrases that are not speech are narration; abstentions were resolved by reading
the passage — ten to the unnamed drinkers (酒客), five to the shopkeeper, one to
Kong Yiji himself.

## Five parts, three Chinese male presets

The story has a narrator and four male speaking parts; the engine ships three
Chinese male presets. In the published audio the narrator is read by **Aiden, an
English preset**, and 我 and Kong Yiji by **two voices cloned from the English
preset Ryan** — the cloning path reads Chinese from an English reference. The
shopkeeper is Uncle_Fu and the drinkers Dylan. The transcribe-back check found
the English-voiced lines intact. (The first export of this sample used Dylan for
the narrator and 我, Uncle_Fu for Kong Yiji and the two Ryan clones for the
shopkeeper and the drinkers; the author swapped voices before the published
export, and an earlier revision of this README still described the first
assignment.)

Whether an English-trained voice reads Chinese acceptably is a question for a
native ear: the author, listening to an earlier revision in the app, found
English voices reading Chinese "problematic", which is why a version with
Chinese voices for every part — the 1.7B presets plus voices designed from a
written description — is being prepared for listening. The narrator and 我 are
the same person and here have different voices; that too is for the ear.

The Sichuan-accented preset Eric was tried for the drinkers first and dropped:
all ten of their lines were flagged, and swapping the voice cleared six of them
without touching the text. The accent was defeating the recogniser, not the
reading.

## What the checks caught

**One real synthesis failure.** Line 20, twelve characters, came out at 13.5 seconds —
over a second per character against a normal third. The duration check flagged it;
a retake with a different seed produced it in 2.2 seconds. This is the failure the
duration check exists for: sound the engine added, which no transcript comparison
would notice.

**Four more duration flags stand in the published audio**, on lines 14, 43, 57 and
83: 9.2, 16.0, 12.8 and 5.2 seconds of speech against roughly 4.2, 7.3, 3.3 and
2.5 expected from their length. They were not retaken — the automatic retry that
now re-rolls a run-away line before anyone hears it was added after this export.
The 12.8-second one, the shopkeeper's 孔乙己长久没有来了, also transcribes with an
extra 啊 at its start. Whether the other three are drawn-out delivery or added
sound is for the ear.

**Two characters the engine cannot read.** The 1938 edition spells 偷 as 偸 and 傻 as
儍. The voice produced a different syllable for 偸 on every occurrence — the
recogniser heard 塞, 知, 贼, 气 — which is not the recogniser's fault. Eight lines
were given a replacement reading with the modern characters; the script keeps the
original spelling, and `script.txt` shows both.

## The transcribe-back check on a century-old text

56 of 93 lines clean after review; 37 flagged. What the check tolerated, and shows:

| Basis | Count | Example |
|---|---|---|
| Same pinyin and tone | 89 | `他`/`她` |
| A known character's name heard as common homophones | 23 | `孔乙己`/`空一季` |
| A 1919 particle written the modern way | 10 | `么`/`吗`, `罢`/`吧` |
| 的 / 地 / 得 | 9 | |

The name row is new with this sample. A recogniser cannot know 孔乙己; the project
does, because he is a character in it. A difference inside a known name that reads
the same without tones is reported as a tolerance. Tones are ignored because 乙 (yǐ)
comes back as 一 (yī) every time; 己 heard as 姐 is a different syllable and still
reports — there are seven of those.

The lines are 93 rather than 92 because the slicer was changed after the first
run: it no longer cuts a long sentence so that an eight-character tail is left
on its own, and one line moved as a result. Seven lines were regenerated.

What remains flagged is mostly single characters in narration heard one tone off —
`倘`/`糖`, `踱`/`躲`, `煮`/`竹` — on vocabulary a recogniser trained on modern speech
meets rarely. Whether any of them is the voice misreading rather than the recogniser
mishearing is not known: **no line of this sample has been listened to.**

## Measurements

| | |
|---|---|
| Attribution, 68 units | **25 s** |
| Synthesis, 92 lines → 682.8 s of audio, first full run | **253 s** (real-time factor 0.37) |
| Transcribe-back check, 92 lines, first full run | **106 s** |
| Human corrections | **43** labels, 8 replacement readings, 1 retake, 1 voice change |

## Not verified

- No human listening. The self-written sample was listened to line by line; this one
  has only been checked by machine.
- The two cloned voices: accent, and whether they are told apart.
- The 37 flagged lines: recogniser or reading.

---

Generated by [VoxStage](../../README.md). Synthetic speech throughout; no human
recording was used or imitated — the two cloned voices were cloned from a preset.
