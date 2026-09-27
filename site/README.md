# VoxStage website

The static site served at <https://houjun.dev/voxstage/>. English only. Plain
HTML and one stylesheet: no scripts, no third-party resources, no cookies.
`.htaccess` sets the security headers (a strict content security policy with
scripts off), caching, blocks internal files and serves `404.html`.

## Deploy

Same host and method as the Mind Craft Fish site: SFTP with an SSH key, the
details in its local, uncommitted deploy notes. Mirror this folder to the
`voxstage` directory beside `mcf` — dry run first, then for real:

```sh
rsync -avzn --delete-after --exclude '.DS_Store' --exclude 'README.md' \
  -e "ssh -i <key> -p <port>" site/ <user>@<host>:<path>/voxstage/
```

Check the listed changes, drop `-n`, run again, then open the site and each
page. `--delete-after` (never bare `--delete`) so no page points at a file
that is already gone mid-upload.

## Media

- `media/*.jpg`: screenshots of VoxStage in English, taken from a throwaway
  data folder holding only public-domain or self-written text.
- `media/*.mp3`: unedited synthetic output — *Pride and Prejudice*, chapter 1
  (public domain) and self-written Chinese hard cases — the same files as
  `examples/`.
- `media/og-card.jpg`: 1200×630 share image cut from the workspace screenshot.
When an image or audio file changes, change its name: they are cached for a
long time.
