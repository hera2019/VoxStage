# Small Chinese and English speaker-attribution evaluation

*[中文](README.zh-CN.md). English translation of Astra's notes of 2026-09-09; the Chinese text is the original. The September 2026 round on eleven reviewed texts is written up in [docs/public/evaluation.md](../../docs/public/evaluation.md).*

Sixteen self-written scenes, eight in each language; per language two for development and six frozen as held-out. Astra wrote the texts and the reference answers before any model output was seen; they have not been independently reviewed by the author, so this is not a doubly human-labelled standard dataset. A quote inside a quote belongs to the outer speaker; unspoken thoughts and written signs are narration; UNKNOWN where the evidence is insufficient.

The aim is to compare the Qwen3-4B-Instruct-2507 Q8_0 already on this machine with a newly downloaded Qwen2.5-1.5B-Instruct Q4_K_M. They are one family at different sizes and quantisations, so the contributions of each factor cannot be separated. Official model pages: [Qwen3](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507), [Qwen2.5 GGUF](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF). Runs use a local llama.cpp build with Metal; the build commit, file SHA-256 and parameters are recorded.

prompt.txt and corpus.sha256 are fixed first. Every output is kept; a failure to preserve the structure or the text counts every unit of that scene as wrong in the strict measures, and failures are never dropped from the denominator. Reported per language and per development / held-out split: text preserved verbatim, narration/dialogue judged over whole units, speaker accuracy over whole dialogue units, ambiguous UNKNOWN, consistency across a character's lines, and time. Speaker names are normalised only by a pre-written alias table. Changing reference answers or selectively re-running after seeing results is forbidden.

A sample this small only picks candidates for the next step; it gives no overall product pass. Long chapters, building the cast automatically, comparisons across model families, Japanese, stability over repeated runs and real review time are measured separately.

Original: Astra, 2026-09-09


Interface correction: the first round used the schema shorthand from the llama.cpp README, but this machine's build requires response_format.json_schema.schema. The first round's outputs are kept as a technical failure and are not scored as schema-constrained model results; after correcting the request structure everything was re-run under a new label. Corpus, answers and task prompt are unchanged; the prompt was not tuned to the samples. The held-out set was processed in the technical first round, so it is not claimed that its outputs were never seen.

Original: Astra, 2026-09-09


## Source-bound comparison and reproduction

The baseline showed the model rewriting the source text, so source_units.py and prompt-anchored.txt were added: the cut uses only the quotation marks of the source itself and never touches the reference answers; the model labels only id / kind / speaker and the program restores the text. The new pipeline was tested on the original sixteen scenes and on four new probes frozen in advance in fresh-holdout.json, which were not a tuning set built from old outputs. Full results: results/speaker-attribution-summary.md/json.

To run evaluate.py give --server (the local llama-server), --model (the GGUF), --label (a new run name) and --build-commit (the build's real commit); add --anchored for the source-bound pipeline, otherwise the free-output baseline runs. It starts a separate evaluation process listening on this machine only and stops it at the end; an existing summary of the same name is never overwritten. Model versions are in model-manifest.json.

Under the new pipeline all twenty scenes kept the source text. The 4B's raw strict speaker score on dialogue is 34/40; counting differences of letter case only (LEO / Leo) as a secondary diagnostic gives 37/40, which does not replace the raw score. Whole scenes correct: 8/20 — not enough for use without review. The scoring and the source-protection tests are part of the full regression (121 checks at the time). One string-escaping error in a new test was caught by the syntax check and fixed before the tests passed.

Original: Astra, 2026-09-09 · English translation: Claude Hera, 2026-09-23
