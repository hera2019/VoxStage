# Labelled script format

UTF-8 TXT, one utterance per line:

    Narrator: Rain tapped against the window.
    Mira: Did you hear that?
    Leo: Just the wind.

Chinese full-width colon is also accepted. Split at the first colon only; remaining colons are part of the utterance. Empty lines are ignored. Every non-empty line must have a speaker label and non-empty text. Narrator/旁白 is an ordinary speaker with its own voice. Import does not infer speakers or rewrite punctuation.

Short, single-sentence utterances are recommended. Initial defensive maximum: 60 characters per Chinese utterance, 240 per English utterance, 500 utterances per project. These are provisional input limits, not claims that TTS quality is safe up to those limits; UI warns to split longer material. Language is explicitly Chinese or English per project for this milestone.

The authoritative format is the versioned project JSON. The richer .voice.md format remains a future import/export adapter, so this milestone does not silently promise a complete Markdown parser. Stable IDs survive text edits; voices are mapped to speaker names in the project. User data is stored outside source-controlled files.

最后更新：2026-09-09 · Astra
