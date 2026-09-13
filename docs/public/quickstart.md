# First run

This is a working development preview. All three samples under `examples/`
were made with the flow below. New material still needs listening to.

## From a passage of prose to a multi-voice recording

1. Double-click `Start VoxStage.command` in the project folder. After a
   self-check it opens the browser; keep the terminal window it started.
   If the browser does not open, go to http://127.0.0.1:8765.
2. Click **＋ 新建工程** (new project) and paste the **unlabelled prose** —
   up to 3,000 characters. The button changes to 分角色并创建工程: the local
   model labels each unit narration or dialogue and names the speaker, then
   hands the result to you for review.
   - A script already written one line per `Speaker: line` imports directly
     ([format](script-format.md)).
   - **More than 3,000 characters** (a whole novel) is filed as a *book* and
     cut at its chapter headings — 第X章 or `Chapter 3` — or at paragraph
     breaks when there are none. A chapter with more dialogue than the draft
     can take at once (80 quoted units) is cut further at paragraph ends.
     Start from any chapter; names confirmed in earlier chapters are offered
     as candidates in later ones.
3. **Review the draft.** Matching speakers to lines is all that is needed
   here. Lines the model could not place are left blank; when two people are
   taking turns it suggests who speaks next, and a button adopts the
   suggestion. Splitting, merging, editing and silencing lines all wait in
   the editor.
4. Once the project exists, start with **角色音色** (voices): one voice per
   character. If the presets are not enough, open 音色试听 → 设计一个新声线,
   describe the voice in a sentence — age, sex, timbre, manner — and listen.
   Every click gives another voice for the same description (up to eight are
   kept to compare); pick the one you like, name it, keep it. Characters can
   then use it.
5. **生成与检查** (generate and check): generate the pending lines, then run
   the check. Every line is transcribed back and compared with its text;
   misreadings and dropped words are flagged, and a line that ran on past its
   text is flagged too — and has already been retried once with another seed.
6. The **句子** (line) tab adjusts one line: edit the text, split at the
   cursor, merge with the line before or after, delete, leave it out of the
   recording while keeping it in the script, regenerate, set the pause after it.
7. **导出作品** (export): the full audio, subtitles cut where the voice
   pauses and stripped of quotation marks and trailing full stops and commas
   (exclamation and question marks stay), the timeline, a portable delivery
   package (one WAV per line plus a table, movable as a folder), and an FCP7
   XML timeline for DaVinci Resolve or Premiere.

## Settings worth knowing

- **预设音色模型** (preset model, whole project): new projects use the 1.7B
  model, which reads more naturally; a 16 GB machine should pick 0.6B.
- **发音词典** (pronunciation lexicon, whole project): written form → read-as
  form, one per line, e.g. `偸→偷`. Changes only what is read, never the text
  or the subtitles; changing an entry invalidates only the lines that contain it.
- **朗读文本** (replacement reading, one line): what this line reads, with the
  text and subtitle unchanged.
- Everything is undoable, and generated audio is never lost by editing a
  different line.

Projects, books and voices live under `user-data/` inside the checkout — not
uploaded, not committed. Stop the service with Ctrl+C in the terminal it
started from.

## What only you can judge

Listening is not something the program can do for you: whether characters are
easy to tell apart, whether the manner sounds natural, whether subtitles appear
and vanish at the right moments, whether a merged line reads smoothly. The
program can prove that the right words were read and that nothing extra was
added. Producing a file is not the same as passing those.

## Boundaries

Fixed voices and the voice library accept only audio this software generated,
or a recording **you have the right to use and have explicitly confirmed**.
Everything generated is marked as synthetic speech and must not be passed off
as a real person. A phone cannot reach the Mac by opening its own localhost.

Last updated: 2026-09-13 · Claude Hera (English edition of quickstart-zh.md)
