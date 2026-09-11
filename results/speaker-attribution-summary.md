# Speaker attribution, bilingual: first round

Recommendation: use the local Qwen3 4B for an **AI draft that a person then
corrects**. The program, not the model, must preserve the prose; the model
returns labels for spans only. Unattended generation without review is not
supported.

## Sample and scope

20 short scenes, ten Chinese and ten English. Sixteen had already been processed
in the free-output baseline; the source-bound run added four probes frozen in
advance. **Reference answers were drafted by the assistant before each model ran
and have not been reviewed by the owner or by an independent annotator.** These
are therefore engineering figures for a selection decision, not a score on an
independent benchmark.

| | Qwen3 4B Q8 | Qwen2.5 1.5B Q4 |
|---|---:|---:|
| Source text preserved (guaranteed by the program) | 20/20 | 20/20 |
| Span type correct | 94/104 | 65/104 |
| Explicit dialogue attributed correctly, strict | 34/40 | 15/40 |
| Explicit dialogue attributed correctly, ignoring name case | 37/40 | 15/40 |
| Ambiguous lines correctly marked UNKNOWN | 4/4 | 1/4 |
| A repeated character correct on every line | 6/8 | 1/8 |
| **Entire scene fully correct** | **8/20** | 1/20 |

Ignoring name case, the 4B scored 17/20 in Chinese and 20/20 in English; the
1.5B, 9/20 and 6/20. That relaxed reading was added after seeing LEO against Leo
in the output; **the strict figure stands and is not replaced by it.**

Twenty requests took 34.41 s and 25.75 s in total, median 1.54 s and 1.18 s.
Neither figure includes model preparation or human review, and neither
represents performance on a long chapter.

## The errors worth fixing first

- The 4B attaches a trailing "他说", "赵远说" or "he replied" to the character and
  treats it as speech. The boundary between narration and dialogue still needs
  review.
- After a nested quotation, "那我们明天再试。" belongs to 小林; the 4B gave it to 阿宁.
- Written text — a sign reading 今天休息, a note reading 不要开门 — can be taken for
  someone speaking.
- Some plainly attributed lines come back UNKNOWN, so abstaining is not always
  well judged.
- The lighter model is markedly worse at both dialogue and ambiguity, and is not
  the candidate.

## Why free-form output is not used

Even after correcting the structured-output parameters, the 4B preserved the
source exactly 0/16 times and the lighter model 2/16: quotation marks were
substituted, whitespace was lost, attribution and formatting went wrong, and two
4B cases hit the output limit. **That failure rate belongs to this strict
pipeline and does not mean the model cannot recognise characters.**

The source-bound run splits spans by a general quotation rule that never reads a
reference answer. The model returns only id, kind and speaker; a missing,
duplicated or unknown id is rejected outright, and the prose is sliced back out
of the original. **The 20/20 preservation is that program rule working, not the
model copying faithfully.**

## Next

Adopt the 4B for source → attributed draft → human confirmation. Keep the prose
intact, show each span's speaker plainly, and surface UNKNOWN, narration/dialogue
switches and inconsistent character names first. Build the reviewable workflow
before extending the evaluation with independent annotation, longer chapters,
more characters and a different model family.

No further prompt tuning against these twenty. Automatic chapter splitting,
cross-chapter character lists, Japanese, human review time and run-to-run
stability remain unverified.

## Reproducing, and provenance

Corpus, prompts, scoring and the binding program are in
`evals/speaker_attribution`; per-case inputs, raw outputs and scores in
`results/speaker-attribution`. The summary JSON keeps file hashes, quantisation,
build commit, prompt hash, per-language and per-split scores, and every error.
Results from the initial run with the wrong schema parameter are kept as a
technical record and must not be mixed with the corrected ones.

Models: [Qwen3 4B](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507),
[Qwen2.5 1.5B GGUF](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF).
Inference used the already-installed llama.cpp with Metal. No shared model or
inference binary was updated, no cloud inference was used, and no user project
was modified.

Full regression at the time: 121 passed, with two pre-existing dependency
deprecation warnings. One string-escape error in a new span-protection test was
found and fixed.

Last updated: 2026-09-09 · Astra (Chinese original) / 2026-09-11 · Claude Hera (English)
