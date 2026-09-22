# First run

This is a working development preview. All three samples under `examples/`
were made with the flow below. New material still needs listening to.

## From a passage of prose to a multi-voice recording

1. Double-click `Start VoxStage.command` in the project folder. After a
   self-check it opens the browser; keep the terminal window it started.
   If the browser does not open, go to http://127.0.0.1:8765.
   VoxStage listens on this machine only. To open it from a phone or an iPad
   on the same network, start it with `--lan`
   (`.venv/bin/python -m runtime.launcher --lan`): the terminal prints the
   network address and an access key; each device types the key once and the
   browser keeps it for 30 days. This Mac itself never needs the key; replace
   it with `.venv/bin/python -m runtime.app --lan --new-key`. A phone cannot
   record over plain HTTP, but it can supply a recording as a file under
   设置 → 音色库 (m4a, mp3 or WAV).
2. Click **＋ 新建工程** (new project) and paste the **unlabelled prose**.
   The button changes to 分角色并创建工程: the local model labels each unit
   narration or dialogue and names the speaker, then hands the result to you
   for review.
   - A script already written one line per `Speaker: line` imports directly
     ([format](script-format.md)).
   - **A whole book**: the 归属 (belongs to) selector in the same dialog
     offers *build a master book, one chapter per project* — the text is cut
     at its chapter headings, 第X章 or `Chapter 3` (a text without headings is
     one chapter), and every chapter becomes an unprocessed sub-project of the
     book. A text too long for one draft is filed this way by itself. The book
     opens from the 主工程 list on the left into one workspace: chapters,
     settings, structure (split, merge, reorder, attach, detach) and export.
     Voices, models, pauses, lexicon and cast are set once on the book and
     inherited by every chapter unless the chapter overrides them; a name
     renamed on the book is renamed in every chapter, and names confirmed in
     earlier chapters are known in later ones. A chapter is processed from
     继续处理 (continue): the draft is made in batches sized to the machine and
     the model, then reviewed and confirmed like any project. The next chapter
     of an existing book is added with ＋ 新章 in the book's workspace, or by
     choosing the book under 归属 when creating a project.
2a. **A TXT or Markdown file**: choose the file. An old file that is not
   UTF-8 — GB2312/GBK, Big5 (Hong Kong, Taiwan), Shift_JIS, UTF-16 — is
   detected and converted, with a note; if the guess is wrong, pick the
   encoding under 文件编码. Markdown loses its marks and keeps its headings as
   chapters.
2b. **A coloured Word manuscript** (.docx): give each character a colour in
   Pages or Word, export .docx, choose the file in the new-project dialog.
   The program lists every colour with counts and samples and asks, colour by
   colour: a character (type the name), the narrator, emphasis (not a speaker),
   or a note to leave out. When the colours settle every line the model is
   never asked; headings are kept but not read aloud by default; a paragraph
   with two people's colours becomes one line per person. Unanswered colours
   wait for the review page.

3. **Review the draft.** Matching speakers to lines is all that is needed
   here. Each line of dialogue comes in one of three states: plain when the
   model named the speaker; **yellow** when the program filled it — from the
   model's own inference, from how that character talked in earlier chapters,
   or from two people taking turns — which stands unless you change it;
   **orange** when you must choose. A speaker the story never names — 有的叫道,
   旁人问道, "one of the drinkers said" — is filled with a stand-in, 众人 (a
   group) or 某人甲 / 某人乙 (one person, lettered per exchange: this scene's
   stranger is not the next one's), in yellow; rename it once and every such
   line follows (Chinese narration only, so far). Yellow is a guess — glance at
   it before creating the project: the program relays only within one exchange
   and learns only from lines you settled. Above the lines is the **cast table** —
   name (editable: the character's lines follow), aliases, first line, source.
   Every decision is saved as you make it (the corner says 已保存); reload, or
   open the same chapter another day, and you can resume the review. The speaker is a list of the book's cast
   plus 新人名. Settle one name and the remaining yellow and orange lines are
   scored again; rename one line's 老板娘 to 陈小雪 and you are offered to carry
   the rest along, after which the book remembers the alias for later drafts.
   Splitting, merging, editing and silencing lines all wait in the editor.
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
- **Pinning a reading**: a Chinese character with several readings can be told
  which one — `干[gan4]` or `干[gàn]`, in a replacement reading or a lexicon
  entry (`干活→干[gan4]活`). The voice is given a common character that reads
  only that way (赣 here); the text and subtitles keep 干, and the panel shows
  what will actually be read.
- Everything is undoable, and generated audio is never lost by editing a
  different line.

## Shortcuts

- **Continuous listening**: ▶▶ 从这句连续听 in the footer plays line after
  line from the selected one, with the export's pauses between them.
- **Colours**: character names (or their words) are coloured in the script —
  automatically by the voice's sex (cool for male, warm for female, the
  narrator in the interface's text colour), or as you choose from the colour
  button beside each voice; two characters may share a colour.
- **Templates and inheritance**: 存为模板 under 角色音色 keeps voices, colours,
  lexicon, model, pause and speed under a name; 沿用设置 applies a template or
  another project; a chapter of a master book inherits the book's settings by
  itself, and its own changes are kept as overrides until 恢复继承 (inherit again).
- **Crowds**: an unnamed speaker such as 众人 can be a crowd — pick a pool of
  voices and 抽签分配 draws one per line, never the same voice twice running.
- **Tags** on every voice (老人、男性、威严…) in the settings dialog; the crowd
  pool filters by them.
- **Adding a character** after the project exists: ＋ 添加角色 under 角色音色, or
  ＋ 新角色… in a line's speaker list.
- **The role-draft model** can be switched between installed models on the
  last page of settings; it takes effect from the next draft.
- **Deleting a project**: archive it first; the archive notice offers deletion.
  The voice library, books and other projects are untouched.

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

Last updated: 2026-09-15 · Claude Hera (English edition of quickstart-zh.md)
