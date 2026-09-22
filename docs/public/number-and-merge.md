# Number forms and merging lines

*[中文](number-and-merge-zh.md). English translation of Astra's note of 2026-09-11; the Chinese text is the original.*

The Chinese content check compares integers it can parse by their value, so 三百二 and 320, or 一千零八十 and 1080 — both in the Chinese hard-case sample — are treated as the same. The equivalence keeps both forms and is labelled "number form"; neither the script nor the recogniser's text is rewritten. Different values are still shown as a difference.

**The same value is not the same reading.** 一千八十 and 一千零八十 both compare as 1080, so a dropped 零 can be hidden. The equivalence is no substitute for listening.

It covers parsable integers from zero to 九千九百九十九; ordinals (第三), magnitudes with 万 or 亿, mixed forms, strings that cannot be resolved and decimals are compared as before. English does not convert numbers. Spaces the recogniser inserts between chunks are ignored as before, so a 3 / 20 split across lines still compares as 320.

After the check rules change, an existing content check may show "needs re-checking"; this does not mark the audio for regeneration and does not confirm its quality.

When a speaker draft is imported, or an edited script is re-cut after confirmation, adjacent lines with the same character and the same kind are merged, up to 60 Chinese or 240 English characters. The source text and its positions are kept; lines of different characters or kinds are never merged.

An existing project is not re-cut when it is opened. When the person confirms a re-cut, lines whose text the merge changed need generating again; unchanged lines keep their audio, and old audio files are kept. The re-cut view shows how many lines are kept and how many need regenerating.

Original: Astra, 2026-09-11 · English translation: Claude Hera, 2026-09-23
