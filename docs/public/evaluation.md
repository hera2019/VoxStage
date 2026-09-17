# Evaluation record: speaker attribution and voice (16–17 September 2026)

This record gathers what VoxStage has measured on two fronts: **speaker attribution** (who says each line of dialogue in a novel) and **voice** (blind listening between cloning models and engines). Every number was produced on one Apple Silicon Mac with 32 GB of memory (measured); where something was not measured, it says so. The texts, the scoring and the limits come first, the conclusions after, so a reader can re-run the same procedure (`scripts/attribution_matrix.py`, `scripts/listening_pairs.py`).

## 1. Texts

| Name | Source | Dialogue lines | Notes |
|---|---|---:|---|
| The True Story of Ah Q, chapters 2, 4, 5, 6, 7 | Lu Xun, public domain | 13–33 | labels confirmed line by line by the author on the review page |
| Kong Yiji | Lu Xun, public domain | 35 | as above; the densest multi-party exchange |
| Storm in a Teacup (风波) | Lu Xun, public domain | 53 | as above |
| Pride and Prejudice (excerpt) | Jane Austen, public domain, English | 21 | as above |
| Web novel 1 | a web novel, not publishable for copyright reasons | 35 | see below |
| Web novel 2 | a web novel, not publishable for copyright reasons | 86 | see below; contains sensitive content |
| Blind chapter: Ah Q, chapter 9, first half | Lu Xun, public domain | 25 | labelled by the collaborating AI, spot-checked by the author; no rule was tuned on it before it was labelled |

**Web novels**: novels found online, used as test material on the testing machine only; for copyright reasons their text is never in the repository and never in any public material — only line counts and scores are reported. Web novel 2 contains sensitive content and exists in the set to check whether a model stops answering properly because of the content: a common way such tools fail on real manuscripts that public-domain texts cannot reveal.

## 2. Scoring

A text is cut into units (at quotation marks, or by line), the model labels each unit narration or dialogue with a speaker, and rules are laid over the answer (a tag in the narration, a character introducing themselves, turn-taking, and so on). The evaluation compares what the review page finally shows the reviewer with the author's confirmed labels:

- **Lines to fix** = what the reviewer must touch: wrong names + yellow (flagged as uncertain) but wrong + orange (left empty) + narration/dialogue confused. This is the only headline metric — it is the user's workload.
- A stand-in the program invented (众人, 某人甲) or a description the author never used (短衣帮) counts as right when one rename maps it to the author's name: a rename on the review page carries every line with it.
- Each model runs the whole pipeline alone; the evaluation forbids switching to another model midway (the product allows it).

## 3. Speaker attribution: models compared

Same prompt, same JSON constraint, same rules; only the model changes. Numbers are lines to fix — lower is better.

**Six models on six texts (16 Sept, before the rule changes)**

| Model | Lines to fix (of 215) | Time per text |
|---|---:|---|
| Qwen3-4B-Instruct-2507 Q8 (the default then) | 54 | 21–53 s |
| Qwen3-4B abliterated Q8 | 28 | 22–86 s |
| Qwen3.5-9B Q5_K_M | 57 (one blank draft) | 89–152 s |
| Qwen3.5-9B abliterated Q5_K_M | 47 (one blank draft) | 92–158 s |
| **Qwen3-14B Q4_K_M** | **16** | 50–121 s |
| Qwen3-14B abliterated v2 Q4_K_M | 30 | 50–122 s |

**Rules as validation (17 Sept)**: the 14B's raw answers on the frozen eleven texts were saved and only the rules re-run, so every rule could be measured on its own. The relation settled on: a tag in the narration, a self-introduction and the continuation of a multi-paragraph speech are strong evidence and may change the model's name; a pronoun's referent and "reads like a man's/woman's line" are weak evidence and may only flag; a line the model left empty is filled by turn-taking first. Result: **eleven texts, 38 → 13 lines to fix**; the blind chapter unchanged (2 → 2).

**14B against 30B-A3B on the eleven texts (17 Sept, new rules)**

| Text | Qwen3-14B | Qwen3-30B-A3B (Instruct-2507, Q4_K_M) | 30B-A3B abliterated |
|---|---:|---:|---:|
| Ah Q ch. 2 / 7 / 6 / 4 / 5 | 0 / 0 / 2 / 0 / 0 | 1 / 1 / 1 / 0 / 2 | 0 / 3 / 0 / 4 / 2 |
| Storm in a Teacup | 1 | **0** | 7 |
| Pride and Prejudice (excerpt) | 0 | 1 | 2 |
| Kong Yiji | 3 | **0** | 4 |
| Web novel 1 | 2 | 9 | 2 |
| Web novel 2 | 3 | **47** | 46 |
| Blind chapter | 2 | 1 | 2 |
| **Total** | **13** | 63 | 72 |
| Time per text | 39–124 s | **22–60 s** | 28–116 s |

Reading: the 30B-A3B (a mixture of experts, 3B active) is the best and the fastest on the public texts; on web novel 2 it collapses — 70 lines answered "not sure", and the abliterated version does the same, so this is not content filtering but the model being unsure of that long text. The 14B holds on the web novels.

**Product behaviour settled from this**: a machine starts on the first of 30B-A3B → 14B → 4B that fits its memory and is installed; when the chosen model hands in a blank draft (fewer than half the lines placed), the 14B and then the abliterated 4B are asked once more. The two 9B models and the two abliterated large models were deleted after the measurement (the author's decision).

## 4. Voice: blind listening

Method: the same line, the same voice, the same random seed, only the model or engine changes; the two versions are labelled 甲/乙 in random order, the key is held by the collaborating AI, and the author only says which one sounds better. The samples are small (one listener, 4–6 lines a round): enough to choose a direction, not to claim "better across the board".

**Cloning model 0.6B against 1.7B (Qwen3-TTS Base; six lines the author had marked as unsatisfying)**

| Voice type | 1.7B chosen |
|---|---|
| fixed / designed voices (cloned) | 3 of 3 (one only slightly) |
| preset voices | 2 of 3 |

Cloning time per line 5–9 s → 9–15 s. **Decision**: where the 1.7B cloning model is installed, new projects use it; existing projects keep what they were made with and can switch with one click.

**Cloning engines: Qwen 1.7B Base against Chatterbox Multilingual v3 and against IndexTTS 1.5 (four lines each)**

| Comparison | Qwen chosen | Notes |
|---|---|---|
| vs Chatterbox v3 (MIT, mlx-audio port) | 3 of 4 | 3–6 s a line |
| vs IndexTTS 1.5 (Apache-2.0, mlx-audio port) | 4 of 4 | dropped words; pinyin written into the text did not fix readings either |

**Decision**: cloning stays on Qwen; both engines and their weights were removed. Rare readings (a fourth-tone character the engine mispronounces) remain unsolved until an engine with reliable pinyin or phoneme control exists.

**The pause at an ellipsis**: neither cloning model pauses at "……". Rewriting the ellipsis as a comma, a full stop or a dash made little measurable difference; cutting the line at the ellipsis, reading the parts separately and joining them with silence did, and the author chose the half-second version. It is a project setting, on by default for new projects.

## 5. Limits

- Labels were confirmed by one person; the blind chapter was labelled by the AI and spot-checked by the author; readers disagree on "quoted or spoken" for short quotes inside narration and for trailing ellipses.
- One listener, 4–6 lines a round; the engine comparison used designed voices only, no preset voices.
- All times include model loading and depend on the machine; here, 32 GB of memory.
- The web novels are not published here, so their scores cannot be checked by others; the public-domain ones can.

Last updated: 2026-09-17 · Claude Hera
