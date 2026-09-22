# Default voice pack

Fourteen voices that VoxStage installs into a new library the first time it
starts: two narrators, young / gentle / gruff / sharp / cold adults of each
sex, an old man, an old woman, a boy and a girl. A Chinese project gives new
characters one of the adult voices by sex, and its narrator a narrator voice;
the old and child voices are for the person to choose.

Every voice was **designed from a written description** with the Qwen3-TTS
1.7B VoiceDesign model and then re-read on a standard demo line with the 1.7B
Base model, so each reference is 7–11 seconds of varied speech. **No human
recording is in this pack**; every entry is marked `synthetic_audio: true`, and
the installer refuses one that is not. The models are Apache-2.0.

`manifest.json` lists each voice: its file, SHA-256, name, the English name it
takes in the English release, the line it reads, its tags and what it is for.
Rebuild the pack from a library with `scripts/voice_pack.py export`; a deleted
default voice comes back from 设置 → 已保存的音色 → 装回默认音色.
