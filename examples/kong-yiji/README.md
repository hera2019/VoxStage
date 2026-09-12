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
| Text | 2,613 characters · 68 quoted/prose units · 92 lines |
| Voices | 旁白 and 我 Dylan (the same person) — 孔乙己 Uncle_Fu — 掌柜 and 酒客 two voices cloned from an English preset |
| Audio | 682.8 s, 24 kHz mono |
| Subtitles | 287 cues, longest line 19 characters |
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

## Four men, three male voices

The story has four male speaking parts and the engine ships three Chinese male
presets. The narrator and 我 are the same person and share Dylan. Kong Yiji is
Uncle_Fu. The shopkeeper and the drinkers use two voices cloned from the English
preset Ryan — the cloning path reads Chinese from an English reference, and the
transcribe-back check found their lines intact. Their accent has not been assessed
by a native listener, and whether the two clones sound distinct enough from each
other in the shopkeeper–drinker exchange has not been listened for.

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

**Two characters the engine cannot read.** The 1938 edition spells 偷 as 偸 and 傻 as
儍. The voice produced a different syllable for 偸 on every occurrence — the
recogniser heard 塞, 知, 贼, 气 — which is not the recogniser's fault. Eight lines
were given a replacement reading with the modern characters; the script keeps the
original spelling, and `script.txt` shows both.

## The transcribe-back check on a century-old text

55 of 92 lines clean after review; 37 flagged. What the check tolerated, and shows:

| Basis | Count | Example |
|---|---|---|
| Same pinyin and tone | 84 | `他`/`她` |
| A known character's name heard as common homophones | 25 | `孔乙己`/`空一季` |
| A 1919 particle written the modern way | 9 | `么`/`吗`, `罢`/`吧` |
| 的 / 地 / 得 | 3 | |
| Same number, different writing | 2 | |

The name row is new with this sample. A recogniser cannot know 孔乙己; the project
does, because he is a character in it. A difference inside a known name that reads
the same without tones is reported as a tolerance. Tones are ignored because 乙 (yǐ)
comes back as 一 (yī) every time; 己 heard as 姐 is a different syllable and still
reports — there are seven of those.

What remains flagged is mostly single characters in narration heard one tone off —
`倘`/`糖`, `踱`/`躲`, `煮`/`竹` — on vocabulary a recogniser trained on modern speech
meets rarely. Whether any of them is the voice misreading rather than the recogniser
mishearing is not known: **no line of this sample has been listened to.**

## Measurements

| | |
|---|---|
| Attribution, 68 units | **25 s** |
| Synthesis, 92 lines → 682.8 s of audio | **253 s** (real-time factor 0.37) |
| Transcribe-back check, 92 lines | **106 s** |
| Human corrections | **43** labels, 8 replacement readings, 1 retake, 1 voice change |

## Not verified

- No human listening. The self-written sample was listened to line by line; this one
  has only been checked by machine.
- The two cloned voices: accent, and whether they are told apart.
- The 37 flagged lines: recogniser or reading.
