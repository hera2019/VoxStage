# First usable workflow — acceptance plan

Written before implementation, 2026-09-09. Scope: local Mac, explicitly labelled Chinese and English scripts. Automatic speaker attribution, cloning, remote access and mobile pairing are outside this milestone.

## Automated acceptance

1. Import independently written Chinese and English samples; preserve every line of source text and explicit speaker assignment. Unknown/malformed syntax produces a useful error without changing an existing project.
2. Save and reload text, speaker-to-voice choices, segment identity, audio metadata and revision. A stale client cannot overwrite a newer revision. Undo/redo restores editing state.
3. Generate one asset per segment. Changing one segment changes only its generation fingerprint; unrelated audio bytes and modification times remain unchanged. Punctuation and effective spoken text belong in the fingerprint.
4. A failed segment records its failure and does not stop the batch. Retrying regenerates the failed/pending segment. Cancel stops before the next segment; current generation may finish. Interrupted work is recoverable after restart.
5. Audio processing uses the final PCM samples. Timeline records file start/end and estimated speech start/end separately. Test a deterministic waveform with known leading/trailing silence: detected speech boundaries within one analysis frame (10 ms); exported SRT matches those boundaries after millisecond rounding. This tests implementation, not perceptual alignment quality.
6. Final WAV sample count equals sum of processed segments and pauses. Missing, invalid or stale audio blocks a complete export rather than silently dropping a sentence.
7. Only loopback hosts and same-origin requests access the service. Invalid IDs, path traversal and invalid voice selections are rejected. Model/credential files are not served.
8. Frontend builds with TypeScript checks; browser exercise covers import, edit, save, restore, generation status, playback and export.

## Real-model acceptance

Run Chinese and English preset-voice samples with a fixed CustomVoice revision, record actual generation time, output duration, memory metric and output metadata. Do not reuse Base-cloning measurements. No human reference audio is needed.

Automated content checks and listening are separate. Human listening must confirm words, speaker distinction, naturalness and subtitle timing before declaring the product fully accepted. A generated file alone is not a quality pass. Energy-based speech bounds are estimates, may miss quiet speech, and are labelled accordingly; they are not forced alignment.

Every verification run records human-readable Markdown and machine-readable JSON under results/. Hardware performance is measured only by the real-model run. Test fixture timings are not model benchmarks.

Last updated: 2026-09-09 · Astra


## Same-speaker continuity follow-up

User listening found the two narrator lines insufficiently consistent in voice/environment. This quality item is not accepted. Repeat-role tests must separately assess perceived speaker identity, acoustic distance/space, level/prosody and word completeness. Fixing a preset ID and seed alone is not acceptance. Candidate sampling changes require listening comparison before adoption.

Last updated: 2026-09-09 · Astra


## Clarified listening priority

The user identifies the opening and closing English narrator as inconsistent in perceived voice identity. Leo is sufficiently distinguishable in this listening session. English same-speaker continuity is not accepted, and no English A/B winner has been established. This is the current primary quality issue. Chinese approval applies only to the samples heard so far.

Subsequent evaluation should include multiple Chinese and English lines from the same narrator, heard consecutively and after a single-line retake. Judge identity, acoustic space/distance, prosody, naturalness and word completeness separately. Prosody may vary; the perceived speaker should remain the same. Parameter equality and waveform metrics alone do not satisfy this criterion.

Last updated: 2026-09-09 · Astra


## Fixed-reference experiment listening result

The user accepted the demonstrated English narrator opening, closing, held-out new line and alternate-seed closing retake (feedback: “OK，no problem！”). This is a scoped listening acceptance for the fixed synthetic-reference experiment, not a general acceptance of the current application engine or all voices/languages. Evidence: results/fixed-reference-check.md and .json. Application integration remains separate.

Last updated: 2026-09-09 · Astra


## Spoken-content check acceptance

- Compare effective spoken text, preserve raw recognized text, and retain negations/numbers/percent/negative signs. Show insert/delete/replace differences as suggestions, never verified speech errors.
- Save checks and explicit listening confirmations; invalidate them when spoken text, audio take, voice, audio-file contents or recognizer settings change. Undo and reload preserve the appropriate state.
- Generation and checking exclude each other; checks can be cancelled, failures are isolated and retryable, and source audio stays intact.
- Verify local Chinese/English transcription through app routes and report export, with no expected-text prompt. Log model/CLI identities, parameters, checksums and actual outcomes.
- Record all test failures. Initial percentage-normalization failure is retained under results/content-check-initial-failure; the corrected suite includes negative-sign regression cases.

These checks validate integration and comparison mechanics. False-positive/false-negative rates on representative speech and damaged audio remain unmeasured; review suggestions still need human listening.

Last updated: 2026-09-09 · Astra


## Short samples accepted by listening

User feedback: "Under 60 characters, tried it, sounds good. One line had an odd
tail, which the software could not detect itself; I regenerated that line and it
was fine. Passed."

Accepted: the short samples heard in this round. A single-line retake resolved
the one tail artefact encountered. The text check did not flag it, which is kept
as an observed limit: matching words prove nothing about tails, timbre or
naturalness.

The project, line, language, audio version and sample count were not stated and
are not filled in here. No rate is inferred, and acceptance is not widened to all
characters, languages or long passages. The cause of the tail artefact is
undetermined; listening and single-line retakes remain. This does not settle the
separate English the/a question, and no per-line confirmations were changed in
bulk.

Last updated: 2026-09-09 · Astra


## Launcher and environment checks

- Missing dependencies, web files or a damaged configuration state the cause and
  the next step. Scripts are not modified, and nothing is installed or downloaded
  without being asked.
- A missing optional model names the features it affects; editing still starts.
  A passing self-check is neither inference nor an audio-quality verdict.
- Launching the same checkout again reuses the running service. A port held by an
  unknown service, another checkout or an older preview is left alone.
- A page opens only once the service answers as healthy. On timeout, exit, Ctrl+C
  or a closed terminal, the launcher cleans up the processes it started.
- Checks, launch, relaunch and shutdown were exercised for real; automated tests
  cover the failure branches. Records: results/launcher-checks and
  launcher-integration, as Markdown and JSON.

Last updated: 2026-09-09 · Astra


## Listening notes and project housekeeping

- Issues may be marked only on generated audio, keeping the kind, the note and
  the version they came from. Automated text checks stay separate.
- After an edit, a voice change, a retake or an altered file, an old mark cannot
  stand for the new version; a retaken line is explicitly awaiting listening.
- A batch retake touches only currently marked lines. Cancelling leaves the rest
  untouched; a failure keeps the issue and allows a retry.
- Marks survive clearing, undo and restart. Exports keep automated results and
  human issues as separate states.
- Renaming, archiving, restoring and undo change neither audio fingerprints nor
  check results. Projects saved before archiving existed default to not archived.
- A narrow screen can switch between existing projects. Real devices and network
  access are accepted separately.

Regression at the time: 57 passed, with two pre-existing dependency deprecation
warnings; the frontend built. A separate English copy exercised one targeted
retake with a real fixed voice, plus renaming, archive and restore, clearing and
undo, refresh and the export report in a browser. Evidence:
results/workflow-checks, listening-integration and model-preparation. Issues
raised during testing are labelled as process verification, not audio judgements.

Last updated: 2026-09-09 · Astra


## Within-line pacing and review cues (2026-09-09)

Automated: 88 passed, covering real FFmpeg at 0.5× and 2.0× for both duration and
pitch, local absolute speed overriding the project rate, preview and export
producing identical bytes, save and undo, old takes retiring, source audio
unchanged, invalid and overlapping selections refused, and a failed transcription
not erasing pause detection. Rule tests use synthetic signals and stand in for no
audio-quality verdict.

Real samples: pause location passed; transcribe-back and timing ran for both
languages; the faster-then-slower detector missed the case it was meant to catch
and is not accepted as reliable. Local adjustments still await listening.
Evidence: results/timeline-integration, timeline-english, timeline-browser,
workflow-checks.

Last updated: 2026-09-09 · Astra


## Same-speaker continuity: accepted on 2026-09-10, within a stated scope

This supersedes the "not accepted" records above, which stay as written.

The author listened to six consecutive narrator lines per language — Chinese
旁白 on Vivian, English Narrator on Ryan, about 32 seconds each — generated
once per line at a fixed seed (260909), peak-normalised only, no trimming, no
speed change, and **no selection among takes**: one attempt per line is what
makes the listening result meaningful. All four human judgements were passed:
same-speaker timbre, same acoustic space, pronunciation and completeness, and
overall listening acceptance. This lifted the feature freeze in force since
2026-09-09. The material is local (`user-data/`, not in the repository); the
generating script and its runtime hashes are recorded with the result.

What this pass does **not** cover, stated as scope rather than as a to-do list:
other presets than the two heard; continuity across a single-line retake; spans
longer than 32 seconds; a different seed; whether the two languages' fixed-voice
configurations are equivalent. Distinctness *between* characters was judged not
to need a separate test — different presets are different speaker embeddings
with no mechanism that would pull them together, and it has been heard in use.

The claim this supports is exactly: *the same character keeps its voice over
tens of seconds of consecutive reading, by human listening.* It is not "voice
quality has been accepted".

Last updated: 2026-09-13 · Claude Hera (public record of acceptance-log entry 001, judged by the author on 2026-09-10)
