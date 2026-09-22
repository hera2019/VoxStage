# VoxStage first workflow architecture

Implementation assumptions under the user's authorization to lead and begin, 2026-09-09. These reversible choices are registered in the private decision log; model quality and delivery packaging remain open.

- React/TypeScript/Vite frontend, FastAPI local service, one serial generation queue. Production serves the built frontend; no production Vite server. Default bind is 127.0.0.1; no LAN sharing in this milestone.
- Project storage: a portable directory under user-data/projects, JSON manifest written atomically, immutable content-addressed WAV files. Stable random segment IDs; order is stored separately as list order. A project revision rejects stale edits. Editing history is persisted for undo/redo. Human edits are the only authority in this milestone.
- Source text is retained independently of optional spoken_as. Import format is one labelled utterance per line, not automatic novel segmentation. Limit input lengths defensively; do not silently truncate or pretend estimated duration is an exact generation limit.
- Engines: a deterministic tone fixture (clearly labelled, tests only) and Qwen3-TTS 0.6B CustomVoice through MLX. Preset voices only, no cloning, no unsupported emotion controls. Checkpoint path is operator configuration, never supplied by the browser. Offline loading requires a complete downloaded model.
- Hash includes actual spoken text including punctuation, language, voice, model/engine identity and fixed generation settings. An asset has synthetic_audio=true, model identity, seed and processing version. Existing files are reused only after validation. One browser job at a time; current project cannot be edited during generation.
- Audio: mono PCM at engine sample rate, consistent sample rate within export. Conservative peak normalization, not a claim of LUFS normalization. Find audible-region estimates using 10 ms RMS frames relative to peak plus a low absolute floor, keep short margins. Reject silence. Use final processed sample count for file boundaries; use separately stored speech estimates for subtitle cues. Keep raw output during the experiment; waveform estimates never imply semantic content correctness.
- Export refuses pending/failed/stale assets. Produce combined WAV, SRT and timeline.json with synthetic metadata. No ASR word timing is used as ground truth.
- Serial GPU work runs off the request event loop. Cancellation occurs between segments. On process restart, unfinished generation is treated as interrupted and can resume using cached assets. A model subprocess/hard cancellation can be added later if measurement warrants it.
- Security: exact loopback host allowlist, same-origin request validation including Sec-Fetch-Site, generated project IDs, server-controlled paths. No arbitrary file or URL fetch API. Sensitive data and results media remain ignored by Git.

## Deferred

Automatic attribution, ASR content verification integration, commercial installer, macOS signing, model downloader UI, adaptive language-specific splitting, final loudness targets, LAN device pairing and real user listening acceptance.

最后更新：2026-09-09 · Astra


## Sampling defaults after listening feedback

Chinese temperature is provisionally 0.6 following the user preference for the B narrator pair. English stays at 0.9. Generation and cache keys share the same parameter source; new audio metadata records actual parameters. Old Chinese assets remain on disk but become pending under the new defaults. This is not a general voice-quality acceptance.

最后更新：2026-09-09 · Astra


## Persisted fixed synthetic voices

Optional voice_profiles map characters to an immutable reference checksum, spoken transcript, source engine/fingerprint and explicit synthetic-reference consent. Legacy projects default to an empty map. The mode is part of edit history; changing preset voice clears that character’s mode. The reference WAV is copied into the project and verified before fixed generation. The Base model revision, actual parameters, reference SHA-256 and frozen transcript join the generation fingerprint. Preset and Base residency alternate; the Base reference cache is cleared before each call to bound memory and avoid trusting its weaker internal key across references. This prioritizes correctness over reference-encoding reuse. Old audio is retained; mode changes invalidate only the affected character. A missing or altered reference fails explicitly.

最后更新：2026-09-09 · Astra


## Local content checking

Whisper.cpp is invoked in a bounded local subprocess per ready sentence, after synthesis model residency is released. Input is resampled to 16 kHz PCM using scipy; no target-script prompt or previous-sentence context is provided. Pinned model SHA-256, CLI checksum, explicit decode settings and normalization version form the checker identity. A check binds to the audio generation fingerprint, content SHA-256, size/mtime and effective spoken text. Changed audio or generation/text/recognition settings invalidate the result and its manual confirmation. Existing results never mutate the source text or audio.

The serial queue tracks generation/checking job kinds, cancellation and isolated failures. Check output, local logs, differences, timestamps and explicit user review are saved in the project; edits and review changes use revision protection. Exports attach an explicit content-check report including unchecked/stale states. Exactness is a normalized text comparison, not an ASR confidence or sound-quality judgment. Chinese characters and English word-like units preserve negation, numbers, percent and negative signs; no automatic simplified/traditional conversion or number verbalization equivalence is assumed.

最后更新：2026-09-09 · Astra


## Local startup

The standard-library launcher checks the native Mac/Python environment, dependency imports, built page and local model settings without loading model weights or installing anything. Only core errors block editing; unavailable optional models produce feature-specific notices. Reports and process logs remain under ignored user-data.

The loopback-only health endpoint returns application identity, a hash of the checkout path and process ID, never the path itself. It shares the existing origin checks. The launcher reuses a matching running checkout; unknown/older services remain untouched. After spawning, readiness must match its own child PID. Startup failure, timeout and interruption clean up only that child. This is a convenience identity check, not an authentication mechanism. No LAN binding or update/install service is introduced.

最后更新：2026-09-09 · Astra


## Human listening and project organization

Optional segment listening_issue records contain a category, note, timestamp, source generation fingerprint, effective spoken text, PCM-file SHA-256 and size/mtime. Derived listening_status distinguishes a current issue, an old issue awaiting generation, and a new version needing listening. Transcription never creates or clears this human record. Export reports carry both dimensions independently.

Marked batch retakes advance each sentence's take only when its processing begins, so cancellation preserves untouched takes and issues. Replaced audio files remain available. Project name and the optional archived flag participate in edit history without entering audio fingerprints. Default project listings exclude archived items; include_archived exposes all. Legacy manifests and histories default to active. Archive is organization, not deletion or a write lock.

The model setup script supports pinned preset/Base selections and read-only verification. Weight hashes are explicit, optional shared links are never overwritten, and local installation registry files are separate from shared weights. These additions do not enable remote access or change reference-voice authorization.

最后更新：2026-09-09 · Astra


## Project tempo and phonetic review

Optional speech_rate participates in project edit history, not synthesis fingerprints. Playback requests pitch preservation via standard and legacy WebKit properties. Export uses bounded local FFmpeg atempo per original sentence, re-estimates speech bounds from final PCM, and leaves configured inter-sentence pause durations unchanged. Reports explicitly identify transcription as based on original generated audio. Human listening issue applicability includes speech_rate; changing it requires a fresh listen.

Chinese comparison uses pypinyin 0.55.0 tone-number readings and a versioned grammatical-de exception with common lexical protections. Alignment reports raw characters rather than replacing source text; equal phonetic keys with different characters are recorded as equivalences. The normalizer version changes the checker identity, invalidating earlier cached checks. This is phonetic inference, not acoustic validation or a general grammar correction system.

最后更新：2026-09-09 · Astra


## Local timing within one line and review leads

`segment.tempo_edit` holds `source_fingerprint`, `audio_sha256`, `audio_stat` and non-overlapping `regions` (start / end / speed) ordered by seconds of the original take. A local speed overrides the work's speed, 0.5–2.0, with no override by default. The setting enters the ordinary undo history but does not change the TTS fingerprint; a new take switches the old ranges off. The preview cache identity includes the source SHA, the generation fingerprint, the effective edit, the global speed and the processing version, so a new take with the same content never reuses an old speed-changed cache.

`prepare_segment` is the one entry for preview and export. After per-range `atempo`, a fade of about 3 ms is added at each seam to reduce discontinuities; no source samples are removed. The joined result's voiced edges are measured again, and the export records the real mapping from source to result. The mapping is used to place range previews approximately; it is not word-level alignment.

`rhythm_check` and `content_check` are stored separately; when recognition fails, a successful acoustic pause analysis is kept, and redoing a line or changing its reading text invalidates the old analysis. Long low-energy marks use 10 ms frames, a relative RMS threshold and a minimum of 0.35 s, excluding leading and trailing silence. The recogniser also returns rough text timing; the initial rule, for lines of at least 4 s with at least six text units in each half, flags a speed change when the density ratio of the halves is ≥ 1.5. It is uncalibrated, not a quality threshold, and it has already missed the real sample.

The export report carries the content and rhythm checks of the original take, the person's issue marks and the local speed state. `timeline.json` also carries low-energy detection on each line's final audio, in seconds of the result; speed changes still need a listen. Reading the waveform needs no extra model. All processing runs on this machine.

Original: Astra, 2026-09-09


## Non-destructive cuts and the editor's playhead

`tempo_edit` gains an optional `cuts` array (start / end in seconds of the original). An empty array is compatible with old projects; an older client that sends no `cuts` keeps the effective cuts. Cuts and speed overrides may overlap; one set of source boundaries divides the audio that is kept. Ranges at the same speed merge only when contiguous in the source, never across a cut. Before saving, the processing is actually run and verified; an edit that empties the line, leaves silence only or leaves a tiny splinter is refused and the version is not advanced. Processing version `local-editor-v3` enters the preview cache.

The playhead maps the audio's `currentTime` back to source coordinates; at a boundary the later segment wins, so the gap of a cut is skipped. Comparing with the original uses the original's time. The mapping function has front-end tests that actually execute. Preview and export share the processing function; subtitle timing is recomputed, subtitle text is never trimmed automatically, and the export report marks `edited_content_requires_review` so that a match against the original text is never taken as acceptance of the cut result.

Fine editing is a separate full-screen view in the same page, reusing the project version and the player, so there is no state conflict between windows. The source waveform has up to 3200 peaks, the SVG path is cached, and the playhead updates on its own each frame.

Original: Astra, 2026-09-09


## Ordered blocks and a result timeline (replacing the earlier range interaction)

`tempo_edit.clips` is an ordered array: `id`, `source_start`, `source_end`, `speed` (null inherits the work's speed). It stays bound to the original's SHA, fingerprint and file state; old `cuts` / `regions` are converted to blocks read-only and `clips` is written only on the first edit, which can be undone back to the old format. The block interface is separate from the old tempo interface, which refuses writes once `clips` exists, so the order cannot be broken.

Array order is output order, not source order. Source ranges may not repeat; 1–40 blocks, each at least 0.02 s of source, the whole line at least 0.2 s of source. Each block's speed is 0.5–2.0, validated and actually processed before saving; a failure does not commit a version. `render_clips` joins the existing `prepare_segment`, so preview and export stay the same. Cache version `ordered-clips-v4`; the mapping gains `clip_id`.

Editor coordinates are seconds of the result: moving a block reorders, and stretching an edge sets the speed as source length over target duration, within limits. Drag coordinates lock the zoom at the moment of pressing, so a live width change cannot feed back into the drag. While dragging, the waveform is stretched approximately from the current result; after saving, the real processed waveform and duration load. The playhead uses the result's `currentTime` directly; comparing with the original is labelled separately.

The main view holds only the entry. Opened, the editor reads the plan and the preview and shows preparing / saving / saved / failed. The result's pause leads are kept. It is a single magnetic track: no free gaps, no overlapping mix, no video.

Original: Astra, 2026-09-09 · English translation: Claude Hera, 2026-09-23 · [中文原文](architecture-zh.md)


## Master books: one sub-project per chapter (2026-09-20 → 22)

A long text is a **master book** (`Book`, `master_schema: 1`): `members` in chapter order, one `Project` per chapter, and the book's own `settings` — preset and cloning models, pauses, speech rate, lexicon, colours, sexes, voices, cast and aliases. A chapter keeps only its **overrides**; every read resolves the effective view (`project_settings.effective`: project override → book → application default, with a `sources` map saying where each value came from), and persistence always writes the raw overrides, never the resolved view. Audio fingerprints are taken on the effective values, so a book-level change re-marks exactly the lines it touches.

A chapter starts `unprocessed` (its text whole in the project record) and is drafted in **batches** sized by `capacity.py` — the machine's memory tier and the model's registered ceilings both bind; the 30B mixture model is capped at 100 units a batch because its labels drift on longer lists. Completed batches survive a failure and a restart; the draft then goes through the ordinary review page and is confirmed **in place**, turning the same project `processed`.

Structure changes — split at a sentence, merge two neighbours, reorder, attach a loose project, detach, dissolve — are planned as pure functions (`book_structure.py`: members after, settings conflicts to resolve, same-name cast questions, assets to copy) and applied as a transaction (`book_transactions.py`) that keeps the replaced projects as recovery snapshots and copies audio by fingerprint rather than regenerating it. A cast rename or a setting unified across the book is the same shape: plan, then transaction. Export (`book_export.py`) concatenates chapters in book order with a chosen pause between them, numbers each batch, keeps the last successful one downloadable and marks it stale with reasons once the book changes. Legacy books (chapter text held on the book, projects linked by index) are read-only under the new code and can be adopted in place (`book_adopt.py`, with a backup first); nothing migrates by itself.

最后更新：2026-09-22 · Claude Hera


## Reaching it from another device on the same network (2026-09-22)

The service binds to loopback and refuses any request whose `Host` is not this machine — that is the default and it does not change. Started with `--lan` it binds every interface and admits other addresses on one condition: a key, generated once and kept in `user-data/lan-key.txt` (mode 600), typed on a small sign-in page and then held in an `HttpOnly`, `SameSite=Strict` cookie whose value is a hash of the key, not the key. Requests from 127.0.0.1 are never asked for it. Everything else stays as it was: the same-origin check, the `x-voxstage: 1` header on every write (a cookie says which device, the header is what keeps another page on that device from posting), the 30 MB body ceiling, the content-security policy. There is no account system: one person, one machine, one key, replaceable with `--lan --new-key`.

Recording from a phone would need a secure context, which plain HTTP on a home network is not; rather than install a self-signed certificate on every device, a phone supplies a recording as a file. The voice library's existing consent gate is unchanged, and a phone's m4a or an mp3 is converted with the machine's ffmpeg on the way in.

最后更新：2026-09-22 · Claude Hera
