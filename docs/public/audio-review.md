# Listening review and in-line timing

*[中文](audio-review-zh.md). English translation of Astra's notes of 2026-09-09; the Chinese text is the original.*

Each check point should come from a problem actually heard, recorded with the sample and with what the current detection can and cannot do. An automatic mark is a lead for listening, not a substitute for the ear: no mark does not mean no problem.

| Check point | What happens now | Limits and next step |
| --- | --- | --- |
| Missing, extra or misread words | The take is transcribed on this machine and compared with the reading text; the transcript is kept as heard | The recogniser can be wrong itself; numbers and characters with several readings still need a listen |
| False alarms on Chinese homophones | Toned pinyin and a small set of particle rules are accepted as equivalent | Not a grammar; each accepted equivalence is kept visible |
| An unnatural pause inside a line | A low-energy stretch of at least 0.35 s in the take is marked orange and can be played around | Commas, breaths and expressive pauses may be marked too; nothing is removed automatically |
| Fast first half, slow second (or the reverse) | The recogniser's rough timing compares the text density of the two halves and marks a large enough difference | Missed on the real sample so far, so it still needs a listen; not word-level alignment |
| Odd endings, dragged syllables | A listening check point and an issue mark; one line can be redone | No reliable automatic detection yet |
| One character sounding like two people | A listening check point; a fixed synthetic reference voice is supported | No automatic voice-identity judgement yet |

When a new problem is found, keep the original take, the symptom, where it is, the language, the speed setting, the recogniser's output and whether it can be reproduced. Add it to the list of known problems first, then test any detection rule on examples that have the problem and on normal ones that do not. What cannot be detected reliably stays a listening task, never a fake "pass". Samples stay in an ignored folder on this machine; public reports may not contain private material.

## Changing the speed within one line

1. Select a generated line and open the timeline. Orange marks a suspect pause; blue marks a saved local speed range.
2. Drag over the original waveform, or type start and end seconds. Put the edges between words or inside a pause, not in the middle of a sound.
3. Set the range speed (0.5–2.0×) and apply it. Change a little at a time; extreme speeds distort.
4. Play the adjusted line to check the result, or the original to compare; a suspect-point button plays only the original around it.
5. A saved range can be adjusted, removed, all ranges cleared, or the change undone.

A local speed is absolute: with the work at 1.1× and the second half of a line at 1.35×, the second half plays at 1.35×, not 1.1 × 1.35. Parts without their own speed follow the work's. A range is at least 0.2 s, ranges cannot overlap, and a line holds at most 20; a range is always bound to the original take's timing and version.

Preview and export go through the same processing and keep the original file and any fixed reference voice. After a new take is generated the old ranges are switched off and the new audio needs its own; undo brings the matching settings back. Subtitles and the exported timeline are rebuilt from the real length of the result; the length shown while selecting is an estimate.

## Evidence from this round and known limits

2026-09-09: in the older take, the low-energy stretch at 5.79–6.19 s near 不少 was detected. The current take has several long pauses, but the waveform alone cannot tell which of them go against the sense of the sentence.

The author found 1.2× overall usable, with the first half still faster than the second. The estimated density ratio of the two halves is about 1.02, below the initial threshold of 1.5. This is a known miss: the estimate is not used to argue with what the author heard, and one example is no reason to lower the threshold to manufacture a detection. Endings and voice consistency stay with the ear.

A separate sample line was set to 1.1× for its first 5.88 s and 1.35× after, cut inside a low-energy stretch; the original is 12.0 s and the result about 9.893 s. It is a candidate for the author to compare, not yet accepted by ear.

Evidence: results/timeline-integration, timeline-english, timeline-browser, workflow-checks (each in Markdown and JSON).

Original: Astra, 2026-09-09


## Fine editing in its own view (2026-09-09)

"Open fine editing" enters a full-screen view; "back to the workspace" or Esc leaves it. Play/pause shows the position in the original; a red playhead follows the sound. Click the waveform to place it; with the waveform focused, Space plays or pauses and the arrow keys move by 0.05 s. With a speed change the playhead still refers to the original; across a cut it skips the removed part.

Drag the ends of a range to resize it, the middle to move it. The view zooms 1/2/4/8×, can zoom to the range and pan, and accepts typed start and end seconds. Zooming changes only the view; a speed change on a range needs to be applied.

"Cut the range" removes it from the result only; the original is not changed, and cut ranges show in red. One cut or all of them can be restored, or undone and redone. A cut is at least 0.02 s; a line keeps at least 0.2 s and cannot be left as silence only, and no unprocessable splinter may be left. A new take switches old speed ranges and cuts off.

A cut can remove sounds of words; the subtitle text and the check against the original text are not rewritten, so check the result and its subtitles again. This is single-line editing, without multitrack mixing or clip reordering. Page and audio evidence: results/editor-integration.md/json.

Original: Astra, 2026-09-09


## Update: editing with blocks (2026-09-09)

The main view keeps only the whole-line speed and the entry to fine editing; the earlier in-place range editing is replaced by the blocks view. Old cuts and speed ranges open directly; the new block format is saved only on the first block edit, the original is unchanged and history can still be undone.

- **Drag the middle of a block** to reorder; neighbours close up automatically.
- **Drag a block's edge** to change its duration with all of its content kept: longer is slower, shorter is faster, and the rest of the timeline moves with it. 0.5–2.0×, processed and saved on release.
- **Split**: place the playhead by clicking or typing the result's seconds, then split there into two blocks.
- **Delete and restore**: delete a selected block; undo and redo restore it. To cut a short stretch out of a line, split at both ends and delete the middle block.
- **Saving**: releasing a drag, splitting, deleting and moving a block save automatically; wait for "saved on this machine". A failure says why and the previous version stays. Zooming, placing the playhead and selecting a block do not change the sound.

The timeline shows seconds of the result. Widths while dragging are estimates and are replaced by the real duration after saving; a split can shift the audio processing window slightly. The thin blue line is the visual edge; each block's hit area lies inside it and does not cover the neighbour. Playing the result and playing the original are kept apart; after an edit, preview plays the result.

This is a single-line, single-track editor with blocks that butt together: no free placement, no multitrack mixing, no video. Splitting, deleting, stretching and reordering were exercised on the page; extreme speed changes are still limited by the audio algorithm. A long pause in the result can be found and played from the result's review leads; endings and voice consistency still need a listen.

Evidence: results/blocks-integration.md/json. The author confirmed that the earlier cut worked; the exact earlier operation in which a speed change did not take effect was not reproduced, and no cause is assumed. The new version is verified by a real change in output duration.

Original: Astra, 2026-09-09


## Time ruler and old-edit compatibility fixes (2026-09-09)

The time scale moved above the waveform, with a native horizontal scrollbar below. A 5 ms splinter left where an old speed edge met a cut edge made the whole timeline fail to save; it is fixed — adjoining splinters join their neighbour and nothing uncut is lost. When a save completes the blocks and the new audio mapping update together, so nothing snaps back. A version conflict is recovered with "reload the saved version" and then retrying.

Dragging edges, splitting, deleting and scrolling were verified in Chrome and in the built-in browser; in Chrome the changes survive a reload. 112 automatic checks passed, and the exported PCM of the line matches the preview. Full evidence: results/browser-editor-fixes.md and the JSON beside it. An isolated piece shorter than 20 ms is still bound by the minimum block length and is never dropped silently.

Original: Astra, 2026-09-09


## Fine-editing workspace and shortcuts (2026-09-09)

Play, back to the start, compare with the original, undo and redo sit in one row under the waveform. The current line and its character are shown above, with zoom and scale beside the waveform; block actions and the collapsible notes on checks are below. On a narrow screen the toolbar scrolls sideways.

- A block list selects small blocks that are hard to click; "zoom to the selected block" helps fine adjustment.
- A block's speed can be typed (0.5–2.0×) and saved with "apply speed" or Enter, or set by dragging its edge.
- "Loop" repeats the current block until stopped; closing fine editing stops it too.
- Timeline shortcuts: Space play/pause, ← → move 0.1 s, Shift + arrows move 1 s, S split, Delete delete; ⌘Z undo, ⌘⇧Z redo (Ctrl on Windows). They do not fire while typing in a field.
- "Export this line as WAV" downloads the saved result; an old version cannot be downloaded while processing.
- "Copy project" in the main view keeps the script, voices, fixed voices and edits as an independent copy without generating anything again. The copy starts from the current state with an empty undo history; it is not an off-site backup.

The project used for verification was the fine-editing trial. 116 automatic regression checks passed and the actions were exercised in Chrome and the built-in browser; results in results/editor-workspace.md/json. Sound quality is still judged by the author's ear.

Original: Astra, 2026-09-09 · English translation: Claude Hera, 2026-09-23
