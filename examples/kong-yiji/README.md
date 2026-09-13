# Sample · 孔乙己 (Lu Xun, 1919)

The other two samples are short. This one is a whole story — Lu Xun's *Kong Yiji*,
2,613 characters, ten minutes of audio — and it was chosen for being hard in the
ways that matter: dense dialogue with no speaker named, a crowd that talks, a
narrator who is also a character, and a century-old text full of words and
character forms a modern model has not seen.

Public domain: Lu Xun died in 1936. Text from Wikisource (the 1938 *Complete Works*
edition); the edition's 『』 quotation marks are written as “” here, nothing else is
changed.

| | |
|---|---|
| Text | 2,613 characters · 68 quoted/prose units · 94 lines |
| Voices | Three designed from a sentence — 旁白 说书人, 孔乙己 老年读书人, 酒客 市井粗嗓 — and two presets on the 1.7B model, 掌柜 Uncle_Fu and 我 Dylan |
| Audio | 581.6 s, 24 kHz mono |
| Subtitles | 259 cues, longest line 20 characters |
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

## Five parts, five voices, three of them written

The story has a narrator and four male speaking parts; the engine ships three
Chinese male presets. Two are used here on the 1.7B model: Uncle_Fu for the
shopkeeper, Dylan for the narrator's one spoken line as a boy. The other three
voices were **designed from a sentence** and kept in the voice library — the
narrator's 说书人 by the author ("a male storyteller's voice, fit for narration,
crisp and steady"), 孔乙己's 老年读书人 (a man in his sixties, hoarse and short of
breath, the manner of an old-style scholar) and the drinkers' 市井粗嗓 (a loud,
rough thirty-year-old who likes to jeer). Each designed voice is a reference
sample that the cloning model reads from, so all three parts go through the
cloning path; the presets go through the preset path.

The voices got here by ear. The first export used Dylan for the narrator and
two clones of the English preset Ryan for the shopkeeper and the drinkers; the
author then tried the English preset Aiden as narrator, and in a full 1.7B
rebuild Dylan again — and rejected him for the part: a Beijing street accent,
"fit for the drinkers, not the narrator". The narrator you hear was designed
after that. The Sichuan-accented preset Eric was tried for the drinkers early
and dropped: all ten of their lines were flagged, and swapping the voice
cleared six without touching the text — the accent was defeating the
recogniser, not the reading.

## What the checks caught

**Run-away takes.** The duration check flags a line that took far longer to
speak than its text warrants — sound the engine added, which no transcript
comparison would notice. In the first run a twelve-character line came out at
13.5 seconds and was retaken by hand to 2.2. Since then the retry is automatic:
across the runs behind this recording six lines were re-rolled with a fresh
seed before anyone heard them (five narrator lines under an earlier narrator
voice, one shopkeeper line). One duration flag stands in the published audio,
on line 86: 孔乙己's stammer “跌断，跌，跌……”, four units in 3.0 seconds — slow
because it should be.

**Two characters the engine cannot read.** The 1938 edition spells 偷 as 偸 and 傻 as
儍. The voice produced a different syllable for 偸 on every occurrence — the
recogniser heard 塞, 知, 贼, 气 — which is not the recogniser's fault. Eight lines
were given a replacement reading with the modern characters; the script keeps the
original spelling, and `script.txt` shows both.

## The transcribe-back check on a century-old text

64 of 94 lines clean, one more confirmed by the author's ear, 29 flagged.
What the check tolerated, and shows:

| Basis | Count | Example |
|---|---|---|
| Same pinyin and tone | 111 | `他`/`她` |
| A known character's name heard as common homophones | 33 | `孔乙己`/`空一季` |
| A 1919 particle written the modern way | 10 | `么`/`吗`, `罢`/`吧` |
| 的 / 地 / 得 | 7 | |

The name row is new with this sample. A recogniser cannot know 孔乙己; the project
does, because he is a character in it. A difference inside a known name that reads
the same without tones is reported as a tolerance. Tones are ignored because 乙 (yǐ)
comes back as 一 (yī) every time; 己 heard as 姐 would be a different syllable and
would still report. Under the first narrator voice that happened seven times; under
说书人 it does not happen once, and the name row grew from 23 to 33 tolerated hits
instead.

By part: narrator 35 clean / 23 flagged, 孔乙己 12 / 3, shopkeeper 8 / 2, drinkers
9 / 1. The same text under the previous voices (0.6B, an English preset reading the
narration) scored 56 / 37, with the dialogue parts worse and the narration about
the same; a narrator on Dylan scored 23 / 35 for the narration alone. What the
recogniser flags moved with the voice, which is the point of keeping the check
beside the audio rather than trusting either.

The lines are 94: the slicer no longer leaves an eight-character tail on its own
(93), and the author split “这……” from 孔乙己's last excuse to give it a beat (94).

What remains flagged is mostly single characters in narration heard one tone off —
`粉`/`坟` four times, `倘`/`糖`, `煮`/`竹`, `曲`/`取` — on vocabulary a recogniser
trained on modern speech meets rarely. Whether any of them is the voice misreading rather than the recogniser
mishearing is for a native ear; see below for what has been listened to.

## Measurements

| | |
|---|---|
| Attribution, 68 units | **25 s** |
| Synthesis, first full run on 0.6B, 92 lines → 682.8 s | **253 s** (real-time factor 0.37) |
| Synthesis of this recording: 83 lines through the cloning path → 529 s | **285 s** (RTF 0.54); 11 preset lines on 1.7B → 30 s in 24 s; peak memory 17.7 GB with four models resident |
| Transcribe-back check, 93 lines, an earlier take of this project | **120 s**, of which whisper 82 s |
| Human corrections | **43** labels, 8 replacement readings, 1 hand retake, 1 split, and the voice changes above |

## What has been listened to

- The author listened to a voice card per part (the same line in each candidate
  voice), rejected Dylan as narrator, designed 说书人 and judged the narrator
  "good"; line 46, the boy's one spoken line, is marked confirmed by listening.
- The recording has **not** been listened to line by line. The 29 flagged lines —
  recogniser or reading — and the designed voices' consistency across ten minutes
  are still for the ear.
- The self-written sample was listened to line by line; this one has been heard
  in parts.

---

Generated by [VoxStage](../../README.md). Synthetic speech throughout; no human
recording was used or imitated — the designed voices come from written descriptions.
