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

最后更新：2026-09-09 · Astra


## Same-speaker continuity follow-up

User listening found the two narrator lines insufficiently consistent in voice/environment. This quality item is not accepted. Repeat-role tests must separately assess perceived speaker identity, acoustic distance/space, level/prosody and word completeness. Fixing a preset ID and seed alone is not acceptance. Candidate sampling changes require listening comparison before adoption.

最后更新：2026-09-09 · Astra


## Clarified listening priority

The user identifies the opening and closing English narrator as inconsistent in perceived voice identity. Leo is sufficiently distinguishable in this listening session. English same-speaker continuity is not accepted, and no English A/B winner has been established. This is the current primary quality issue. Chinese approval applies only to the samples heard so far.

Subsequent evaluation should include multiple Chinese and English lines from the same narrator, heard consecutively and after a single-line retake. Judge identity, acoustic space/distance, prosody, naturalness and word completeness separately. Prosody may vary; the perceived speaker should remain the same. Parameter equality and waveform metrics alone do not satisfy this criterion.

最后更新：2026-09-09 · Astra


## Fixed-reference experiment listening result

The user accepted the demonstrated English narrator opening, closing, held-out new line and alternate-seed closing retake (feedback: “OK，no problem！”). This is a scoped listening acceptance for the fixed synthetic-reference experiment, not a general acceptance of the current application engine or all voices/languages. Evidence: results/fixed-reference-check.md and .json. Application integration remains separate.

最后更新：2026-09-09 · Astra


## Spoken-content check acceptance

- Compare effective spoken text, preserve raw recognized text, and retain negations/numbers/percent/negative signs. Show insert/delete/replace differences as suggestions, never verified speech errors.
- Save checks and explicit listening confirmations; invalidate them when spoken text, audio take, voice, audio-file contents or recognizer settings change. Undo and reload preserve the appropriate state.
- Generation and checking exclude each other; checks can be cancelled, failures are isolated and retryable, and source audio stays intact.
- Verify local Chinese/English transcription through app routes and report export, with no expected-text prompt. Log model/CLI identities, parameters, checksums and actual outcomes.
- Record all test failures. Initial percentage-normalization failure is retained under results/content-check-initial-failure; the corrected suite includes negative-sign regression cases.

These checks validate integration and comparison mechanics. False-positive/false-negative rates on representative speech and damaged audio remain unmeasured; review suggestions still need human listening.

最后更新：2026-09-09 · Astra


## 60 字以内样本获本人试听认可

本人反馈：“60字以内，试过了，效果不错。只有一个尾音不太正常，但软件自己检查不出来，我重新生成新的语音，结果没问题了。通过！”

结论：本轮已试听的 60 字以内样本获本人认可，单句重新生成成功解决了本人遇到的一次尾音异常。软件文字检查未提示该异常，作为已观察到的能力边界保留：识别文字一致不能证明尾音、音色或自然度正常。

本人未指定工程、句子、语言、音频版本或样本总数，不补填这些信息，不推算发生率，不将认可扩大到全部角色、语言或长篇。尾音异常的原因尚未确定；仍保留人工试听和单句重做。此次反馈不直接对应英文 the/a 疑点的单独判定，不批量更改工程内逐句确认记录。

最后更新：2026-09-09 · Astra


## 本地启动与环境检查

- 缺少运行依赖、网页或损坏配置时，明确说明原因与下一步；不修改稿件、不擅自安装工具或下载权重。
- 缺失可选模型时提示受影响的功能，编辑入口仍可启动。启动自检不等于模型推理或音质验收。
- 重复启动同一目录的工作台复用原服务；未知服务、其它目录或旧版服务占用端口时保持原进程不动。
- 新启动仅在自己的服务健康响应后打开页面；启动超时、退出、Ctrl+C 或关闭终端时清理自己创建的子进程。
- 实际执行环境检查、启动、重复打开与关闭；自动化覆盖失败分支和已有工作流。记录见 results/launcher-checks 与 launcher-integration 的 Markdown/JSON。

最后更新：2026-09-09 · Astra


## 人工听稿与工程整理验收

- 只允许给已生成声音标记问题，保留问题类型、备注与来源版本；自动文字检查结果保持独立。
- 编辑、换声线、重做或音频文件变化后旧标记不能冒充新版本结论；重做后的声音明确待试听。
- 批量重做只处理当前标记句，保留其它句音频；取消保留未处理句，失败保留问题并允许重试。
- 清除/撤销/重启恢复标记；导出保留自动检查及人工问题的独立状态。
- 工程改名、归档、恢复与撤销不改变音频指纹或检查结果；旧格式默认未归档。
- 窄屏可以切换已有工程，实际设备连接与网络访问另行验收。

最终统一自动化回归为 57 项通过（含 2 条已有依赖弃用警告），前端构建通过。独立英文副本完成真实固定声线的一句定向重做，以及浏览器改名、归档恢复、清除撤销、刷新与报告验证。证据见 results/workflow-checks、listening-integration 和 model-preparation。测试用人工问题明确标注为流程验证，没有代为确认音质。

最后更新：2026-09-09 · Astra


## 句内节奏调整与疑点复核（2026-09-09）

自动测试：88 项通过，包括真实 FFmpeg 0.5/2.0 倍时长与音高、局部绝对速度覆盖、预览/导出音频字节一致、保存撤销、旧 take 停用、源音不变、非法/重叠选区拒绝，以及 ASR 失败不抹掉停顿检测。规则测试使用合成信号，不能替代真实声音质量验收。

真实样本：旧停顿定位通过；中英文文字回读与时间输出运行通过；前快后慢检测漏检，尚未通过可靠性验收。局部调整候选仍待本人试听。证据见 results/timeline-integration、timeline-english、timeline-browser、workflow-checks。

最后更新：2026-09-09 · Astra
