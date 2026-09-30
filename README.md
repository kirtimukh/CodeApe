# CodeApe

**Explore a codebase commit by commit. Learn by typing the changes.**

CodeApe turns a Git repository's history into interactive typing lessons. It
shows each commit's code changes in order and lets you type through additions
and deletions, so you can follow how a project was built while getting
familiar with its code.

The longer-term direction is to make lessons more focused than a repository's
commit history: **generate constructive, AI-created patches for a specific
existing feature**, then let learners type through those patches. A lesson could
explain part of the feature **as it exists today, OR** reconstruct how that feature
evolved **using its history**. Another possible path is to let learners enter a diff
in free text and have AI judge whether it correctly implements the change.

## Current features

- Work through the first-parent commit history of a repository, one commit at a
  time.
- Type added code and accept deleted code as you progress through each change.
- Navigate between files, hunks, and commits; skip a hunk or lesson and return
  to it later.
- Resume with per-line and per-hunk progress saved between sessions.
- Track typing speed, accuracy, and assisted characters.
- Choose dark or light colors, or detect the terminal background automatically.
- Keep the original repository untouched: CodeApe clones it into its own data
  directory and maintains a separate learning workspace.

## Install

Requires Python 3.11 or newer and Git.

```bash
python -m pip install .
```

For development, install the test dependency too:

```bash
python -m pip install '.[dev]'
```

## Get started

Register a local Git repository or a remote Git URL:

```bash
codeape init /path/to/repository
codeape init https://github.com/owner/project.git
```

Start learning:

```bash
codeape start
```

If you have registered multiple repositories, `start` opens a picker. You can
also select one directly by its ID, shown by `init` or `status`:

```bash
codeape start 1
```

Check progress at any time:

```bash
codeape status
codeape status 1
```

CodeApe stores cloned repositories, progress, and its registry under
`~/.codeape`. Set `CODEAPE_HOME` to use a different data directory.

## Typing controls

| Key | Action |
| --- | --- |
| Characters | Type the next expected character |
| `Enter` | Finish a completed line |
| `Backspace` | Undo typed progress or accept a deleted character |
| `Tab` | Advance to the next token |
| `Shift+Tab` | Finish the current added line |
| `Ctrl+D` | Accept the current deleted line |
| `Ctrl+S` | Skip the current hunk |
| `Ctrl+K` | Skip the current commit |
| `Ctrl+L` | Open the lesson picker |
| `Shift+Left` / `Shift+Right` | Switch files |
| `Up` / `Down` | Move between typable lines |
| `Ctrl+Q` | Quit and save progress |

Skipped lessons remain available to resume later. Completed lessons are
read-only when revisited.

## Theme

Select a theme when starting CodeApe:

```bash
codeape start --theme dark
codeape start --theme light
codeape start --theme auto
```

`auto` (the default) checks `COLORFGBG`, then queries the terminal background
when supported; it falls back to dark. The `CODEAPE_THEME` environment variable
can also be set to `dark`, `light`, or `auto`.

## Development

Run the test suite with:

```bash
pytest
```

## Project direction

CodeApe's current lessons follow repository commits. The next learning path is
feature-focused: create a constructive sequence of AI-generated diffs for a
specific existing feature and type along to understand how it works. These
patch lessons may be based on the latest version of a feature **or** on its
evolution through Git history.
