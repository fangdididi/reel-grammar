# Reel Grammar

**English** · [简体中文](README.zh-CN.md)

**Borrow a video's rhythm and look, not its footage.**

Reel Grammar is an agent skill for the brief "make one like this video". It measures a reference video's editing
grammar, turns it into a small grammar card made of numbers, checks every draft against that card with clear verdicts
and fixes, and runs a copy check before delivery so the new piece never reuses the reference's frames or traces its cut
list.

It works with Claude Code, Codex, Cursor and any agent that can read a `SKILL.md` and run a Python script. It does not
make video itself: it guides and checks whatever tool you already use.

## Why

A reference video is a feeling the user cannot name. Without measurements an agent either misses the rhythm entirely
or copies the surface. Reel Grammar gives the feeling numbers you can aim at and talk about:

- "Your shots average 2.6 s, the reference averages 1.2 s."
- "The reference speeds up in its last third; yours stays steady."
- "The reference is 85% hard cuts with one dip to black; yours dissolves everywhere."

## Features

- **Shot and join detection.** Hard cuts, dissolves, dips to black, white flashes, and short black slugs folded into
  the join instead of counted as shots.
- **Rhythm.** Mean, median, 10th and 90th percentile shot length, a six-bucket length mix, cuts per minute, and a
  ten-slice pacing curve labelled steady, speeds up or slows down.
- **Look.** Brightness, contrast, saturation, warmth, share of near-black picture and a five-colour palette, overall
  and per shot.
- **Motion.** Still, gentle or busy per shot, plus sideways camera moves (pan, tilt, handheld) from phase correlation.
- **Match report.** Eleven checks with ON, CLOSE or OFF, a score out of 100, and the first three changes to make.
  Exit code 1 while anything is OFF, so it can gate a pipeline.
- **Copy check.** Perceptual hashes of three frames per shot find reused frames (ECHO) and near matches (LOOKALIKE);
  a sequence check finds traced cut lists (TIMING_TRACE); identical palettes are flagged (PALETTE_CLONE).
- **Contact sheet.** One labelled frame from the middle of every shot, for the parts only eyes can judge.
- **Footage-free output.** The grammar JSON holds numbers and colour codes only, so it is safe to keep and share.
- **Local only.** No network calls, no uploads.

## Requirements

- Python 3.9 or newer with `numpy`
- `ffmpeg` and `ffprobe` on the PATH
- `Pillow` (optional, only for `sheet`)

## Installation

Clone the repository into your agent's skills folder.

**Claude Code**

```bash
git clone https://github.com/fangdididi/reel-grammar ~/.claude/skills/reel-grammar
```

**Codex**

```bash
git clone https://github.com/fangdididi/reel-grammar ~/.codex/skills/reel-grammar
```

**Cursor** (project rules or skills folder)

```bash
git clone https://github.com/fangdididi/reel-grammar .cursor/skills/reel-grammar
```

**Any other agent**: put the folder where the agent can read it and point the agent at `SKILL.md`.

Install the Python dependencies if needed:

```bash
pip install numpy pillow
```

## Usage

Ask your agent something like "Here's a reference, make our launch video feel like this" and it will follow
`SKILL.md`. You can also run the script yourself:

```bash
# 1. measure the reference
python3 scripts/reelgrammar.py read reference.mp4 --out ref
python3 scripts/reelgrammar.py sheet reference.mp4 --out ref/sheet.png

# 2. compare a draft with the saved grammar
python3 scripts/reelgrammar.py match draft.mp4 --grammar ref/grammar.json --out check

# 3. make sure nothing was lifted
python3 scripts/reelgrammar.py copycheck draft.mp4 reference.mp4
```

Tuning: `--hard` (default 0.30) is the hard-cut threshold, lower finds more cuts; `--soft` (default 0.30) is for
dissolves and fades; `--fps` (default 10) is the analysis frame rate.

## Example output

```text
# Match: draft.mp4 against reference.mp4

Score 68/100. ON 6, CLOSE 3, OFF 2.

| check | reference | draft | verdict | what to change |
|---|---|---|---|---|
| shot length (mean) | 1.07 s | 1.9 s | OFF | cut shots to about 1.1 s on average (now 1.9 s) |
| pacing shape | speeds_up | steady (r=0.12) | OFF | the reference speeds up; yours steady. Move cuts so the busy slices line up |
| saturation | 0.61 | 0.52 | CLOSE | raise saturation toward 0.61 (now 0.52) |
| ... | | | | |

## First three changes

1. cut shots to about 1.1 s on average (now 1.9 s)
2. the reference speeds up; yours steady. Move cuts so the busy slices line up
3. raise saturation toward 0.61 (now 0.52)
```

## File structure

```text
reel-grammar/
├── SKILL.md               # the skill, English
├── SKILL.zh-CN.md         # the skill, Chinese
├── README.md              # this file
├── README.zh-CN.md        # Chinese README
├── LICENSE
├── scripts/
│   └── reelgrammar.py     # read, match, copycheck, sheet
└── tests/
    ├── make_clips.py      # builds synthetic clips with known cuts
    └── test_reelgrammar.py
```

## Tests

```bash
python3 -m unittest discover -s tests
```

The tests render synthetic clips with known cut times, dissolves, dips, flashes and pans, then check the measurements,
the match verdicts, the copy check and the command-line exit codes.

## Limits

- Pushes and zooms are not measured; note them by eye from the contact sheet.
- Fast flashes and strobe effects can read as cuts, and two very similar shots joined by a hard cut can be missed.
  Adjust `--hard` and check the sheet.
- The copy check compares pictures and timing. It is a safety net, not a legal opinion.

## License

MIT. See [LICENSE](LICENSE).
