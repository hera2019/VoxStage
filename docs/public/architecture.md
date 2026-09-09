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


## 单句局部节奏与复核线索

新增 segment.tempo_edit：source_fingerprint、audio_sha256、audio_stat、按原音秒数排序的不重叠 regions(start/end/speed)。局部速度覆盖作品速度，范围 0.5–2.0，默认无覆盖。设置进入既有撤销历史但不改变 TTS 指纹；换生成版本后旧选区停用。试听缓存身份包含源 SHA、生成指纹、有效编辑、全局速度及处理版本，避免同内容新 take 误用旧变速缓存。

prepare_segment 是预览和导出的共同入口；分段 atempo 后，接缝添加约 3 ms 渐变减少不连续，不删除原音样本。合并结果再次计算发声边界，导出记录实际源音→成品映射。映射用于选区试听位置近似定位，不构成逐字对齐。

rhythm_check 与 content_check 独立保存；识别失败仍保留成功的声学停顿分析，重做/改朗读文本后旧分析失效。较长低能量标记使用 10 ms 帧、相对 RMS 阈值及 0.35 s 最短时长；排除首尾留白。ASR 额外返回粗略文本时间，初始规则在至少 4 s、两半各至少 6 个文字单位时，按两半文字密度比≥1.5 提示语速变化。未校准，不可作为质量阈值；当前真实样本已漏检。

导出报告带原音文字/节奏检查、人工问题及局部变速状态。timeline.json 另带最终各句音频的低能量检测，时间为该句成品秒数；语速变化仍须试听。波形读取无需额外模型。所有处理本机执行。

最后更新：2026-09-09 · Astra


## 非破坏性剪切与编辑器播放线

沿用 tempo_edit，新增可选 cuts 数组（原音 start/end 秒数）。空数组兼容旧工程；旧客户端未提供 cuts 时保留当前有效剪切。剪切与速度覆盖允许交叉，由统一源边界划分保留音频。相同速率只合并源上连续的范围，不能跨剪切合并。保存前实际验证处理输出，拒绝剪空、只剩无声和极短碎片，失败不推进版本。处理版本 local-editor-v3 进入试听缓存。

播放线将音频 currentTime 反向映射到原音坐标，分段边界采用后段优先以跳过剪切空洞；原音对照使用原音时间。映射函数有实际执行的前端测试。预览/导出共用处理函数；字幕时间重算，字幕正文不自动删字。导出报告标明 edited_content_requires_review，避免把原音文字匹配当作剪后成品验收。

精细剪辑为同一网页中的独立全屏视图，复用工程版本和播放器；避免多窗口状态冲突。源波形增加至最多 3200 个峰值，SVG 路径缓存，播放线单独随帧更新。

最后更新：2026-09-09 · Astra


## 有序区块与成品时间轴（替代旧选区交互）

新增 tempo_edit.clips（有序数组）：id、source_start、source_end、speed（null 继承作品速度）。仍以原音 SHA、指纹和文件状态绑定；旧 cuts/regions 只读转换为区块，首次编辑才写入 clips。可撤销回到旧格式。新区块接口与旧 tempo 接口分开，已有 clips 时拒绝旧选区写入，避免破坏顺序。

数组顺序决定成品顺序，不按原音坐标排序。源范围不能重复，保留 1–40 块，每块原音至少 0.02 秒，整句源内容至少 0.2 秒。独立速率为 0.5–2.0 倍，保存前校验和真实处理，失败不提交版本。render_clips 与既有 prepare_segment 相接，预览和导出保持一致。缓存版本 ordered-clips-v4，映射增加 clip_id。

编辑器坐标改为成品时间：移动对应重排，边缘伸缩按原音长度/目标时长计算速度并限制范围。拖动坐标锁定按下时的视图比例，避免实时宽度变化反馈导致失控。拖动中的波形按现有成品形状近似拉伸；保存后加载真实处理后波形和时长。播放线直接使用成品 currentTime，不再借源顺序反查；原音对照单独标注。

主界面只放入口。剪辑打开后读取方案与预览，显示正在准备/正在保存/已保存/失败状态。新版保留成品停顿线索。当前单轨磁性排列，无任意空隙、重叠混音或视频。

最后更新：2026-09-09 · Astra
