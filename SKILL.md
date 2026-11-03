---
name: reel-grammar
description: Use when someone shows you a reference video and asks for "one like this", "in this style" or "with this pacing". Measures the reference's editing grammar (shot lengths, cut rhythm across the runtime, how shots are joined, brightness, contrast, palette, motion) into a footage-free grammar card, rewrites it for the new length and format, checks each draft against it with ON/CLOSE/OFF verdicts and concrete fixes, and runs a copy check so the new piece borrows the rhythm and look but never the footage.
---

# Reel Grammar

**English** · [简体中文](SKILL.zh-CN.md)

## What this is

"Make it feel like this video" is one of the most common creative briefs, and one of the vaguest. People point at a
reference because they cannot name what they like about it. Agents then do one of two bad things: they guess at the
vibe and produce something with a completely different rhythm, or they copy the surface (the same shots, the same
colours in the same order, even the same frames) and hand back a near-copy.

Reel Grammar sits between the reference and whatever tool makes the video (Remotion, HyperFrames, After Effects,
CapCut, Premiere, ffmpeg, an AI video model). It does three jobs:

1. **Read** the reference and write down its grammar as numbers: how long shots last, how that changes across the
   runtime, how shots are joined, how bright, contrasty, saturated and warm it is, which colours dominate, and how much
   the picture moves. Nothing from the source (frames, characters, music, logos) is stored.
2. **Match** each draft against that grammar. Every measurement gets ON, CLOSE or OFF and a plain fix such as "cut
   shots to about 1.2 s on average (now 2.6 s)".
3. **Copy-check** the finished draft against the reference: reused frames, a cut list traced shot for shot, a palette
   cloned in order.

The result is a video that feels related to the reference for reasons you can point to, and is still its own piece.

## When to use it

- A user gives a video file, a screen recording or a downloaded clip and says "like this", "same energy", "same edit".
- A brand wants a series of videos to keep one rhythm and look, and you need a written standard to check new ones
  against.
- You are reviewing an edit and need to explain why it feels slower, flatter or busier than the target.
- You want to turn a style you admire into a reusable spec you can share with a team or another agent.

Not for: making the footage itself (use your normal production tools), lip-sync or face work, or recreating a specific
copyrighted video. If the user wants an exact remake of someone else's video, say so plainly and offer the grammar
instead.

## What you need

- `python3` with `numpy`, plus `ffmpeg` and `ffprobe` on the PATH. `Pillow` is only needed for the contact sheet.
- The reference as a local file. If the user only has a link, ask them to download it themselves or use a tool they
  are allowed to use for that site. Analysis only needs a low-resolution copy.
- The helper script: `scripts/reelgrammar.py` (no network access, nothing leaves the machine).

## Steps

### 1. Take the brief

Before measuring, ask (or infer from the conversation) four things and write them down:

- **What they love about it.** Push for one moment: "the drop at 0:12", "how calm the first half is". This is the part
  the new piece must land.
- **What must be different.** Subject, product, characters, language, music.
- **Target format.** Length in seconds and aspect ratio (16:9, 9:16, 1:1).
- **Who owns the reference.** If it is the user's own earlier video, copying more closely is fine. If it belongs to
  someone else, the borrow line below applies in full.

### 2. Read the reference

```bash
python3 scripts/reelgrammar.py read reference.mp4 --out ref
```

This writes `ref/grammar.json` (all numbers), `ref/grammar.md` (a readable card) and `ref/shots.csv` (one row per shot).
Then make a contact sheet and actually look at it:

```bash
python3 scripts/reelgrammar.py sheet reference.mp4 --out ref/sheet.png
```

Check the shot count against what you see. If the script merged two shots that are obviously different, run again with
a lower `--hard` (for example `0.22`). If it split one shot because of a flash or fast motion, raise it (for example
`0.40`). Animation with held drawings and very fast cutting usually needs a lower threshold.

### 3. Add what numbers cannot see

The script measures rhythm, joins, look and sideways camera motion. Look at the sheet and add short notes for the rest:

- **Medium**: live action, flat vector, painted, 3D, pixel, screen capture.
- **Shot sizes**: mostly wide, mostly close, or a pattern such as wide then two closes.
- **Pushes and zooms**: the script does not measure them, so note them by eye.
- **Type on screen**: none, captions, big kinetic words; position and case.
- **Sound relation**: cuts on the beat, cuts on words, or free.
- **The moment**: where the high point is (in percent of runtime) and how it is built (speeding cuts, a long hold, a
  dip to black before it).

Put these notes at the top of `ref/grammar.md` under a heading such as `## By eye`.

### 4. Rewrite the grammar for the new piece

Keep ratios, not seconds. A 15 second reference with 12 shots is a grammar of "about 48 cuts per minute, mean 1.25 s".
For a 45 second piece that means about 36 shots, not 12 longer ones. Write a short plan:

| Reference | New piece |
|---|---|
| mean 1.25 s, median 1.0 s | aim for 1.1 to 1.4 s mean |
| speeds up in the last third | put the product reveal after the fastest stretch |
| 85% hard cuts, 15% dips to black | one dip before the reveal, the rest hard |
| warm, low saturation (0.25), palette amber/olive/cream | grade warm, keep saturation low, swap olive for brand teal |
| 60% gentle motion, 30% still | mostly slow drift, a few locked shots for text |

If the reference is landscape and the target is portrait, keep the rhythm and look but plan new framing. Do not just
crop the reference's compositions.

### 5. Make the draft

Build it with whatever the user's pipeline is. Export a draft at any resolution. The analysis works on a small copy.

### 6. Match, fix, match again

```bash
python3 scripts/reelgrammar.py match draft.mp4 --grammar ref/grammar.json --out check
```

The table has one row per measurement: shot length, shot length mix, pacing shape, joins, brightness, contrast,
saturation, warmth, palette, motion mix and orientation. The exit code is 1 while any row is OFF.

- Fix OFF rows first, then CLOSE rows. The report lists the first three changes in order.
- Do not chase 100. A piece that is ON for rhythm and look and CLOSE on palette because the brand colour differs is a
  good result. Say which rows you left CLOSE on purpose.
- Stop after three rounds and show the user. More rounds usually means the plan in step 4 needs changing, not the edit.

### 7. Copy-check before delivery

```bash
python3 scripts/reelgrammar.py copycheck draft.mp4 reference.mp4
```

- `ECHO` (exit 2): a draft shot looks like a reference frame. Replace that material. Do not deliver.
- `LOOKALIKE`: close enough to check by eye. Often fine (two sunsets look alike), sometimes a lifted shot.
- `TIMING_TRACE`: six or more shots in a row copy the reference durations. Shift some cuts so you follow the rhythm
  without tracing the cut list.
- `PALETTE_CLONE`: the five main colours match in order. Fine for a homage, worth changing for an original piece.
- `CLEAR`: nothing found. Plain colour shots cannot be compared by picture and are counted in a note.

### 8. Hand over

Give the user the draft, the match table, the copy-check result, and two or three sentences on what was borrowed and
what was changed. Keep `ref/grammar.json` and `ref/grammar.md`: they are the house style for the next video.

## The borrow line

| Take freely | Adapt to your material | Do not take |
|---|---|---|
| shot length rhythm and its curve | the shot size pattern | frames, clips, footage |
| how shots are joined | the colour mood (shift the exact hues) | characters, mascots, faces, logos |
| overall brightness, contrast and saturation | the structure of the high point | the music track or voice |
| the proportion of still to moving shots | caption style | the exact cut list, shot for shot |
| aspect and format conventions | | distinctive signature moves that identify one creator |

## Grammar card template

```markdown
# Grammar card: <name>
Reference: <file>, <seconds> s, <aspect>
By eye: <medium>; <shot sizes>; <pushes/zooms>; <type on screen>; <sound relation>
The moment: <where, in % of runtime>, built by <how>
Rhythm: mean <s>, median <s>, <cuts/min> cuts/min, pacing <steady|speeds up|slows down>
Joins: <hard %>, <soft %>, <dip %>, <flash %>
Look: brightness <v>, contrast <v>, saturation <v>, warmth <v>, palette <hex list>
Motion: still <%>, gentle <%>, busy <%>; camera <counts>
Keep: <3 things the new piece must keep>
Change: <3 things the new piece must change>
```

## Examples

**A vertical teaser from a vertical reference.** The user sends a 15 s phone ad they like and wants a 30 s teaser for
their app. `read` finds 14 shots, mean 1.07 s, pacing that speeds up, all hard cuts, high saturation. By eye: big
centred words, cuts on the beat, the high point at 80%. The plan keeps about 28 shots, speeds up into a logo hold at
80%, and replaces the reference's neon pink with the app's orange. Round one of `match` says shot length OFF (mean
1.9 s). Round two is ON everywhere except palette CLOSE, which was the point. `copycheck` is CLEAR.

**A calm explainer from a documentary clip.** The reference is a 2 minute nature clip: 11 shots, mean 10.9 s, 70%
gentle motion, two dissolves, dark and warm. The new piece is a 90 s explainer made of screen recordings. Screen
recordings are mostly still, so `match` says motion mix OFF. The fix is slow pushes and drifts on the recordings, after
which motion is CLOSE and the piece finally feels like the reference.

**A house style check.** A team keeps `brand/grammar.json` from their best-performing video and runs `match` on every
new edit before review. Anything OFF goes back to the editor with the fix text attached.

## Tips

- Measure a clean copy of the reference: no watermark burned in, no app interface around it. Crop it first if needed.
- Very short references (under 8 s or under 4 cuts) give a weak pacing shape. The match skips that row on purpose.
- Fast flashes, light leaks and strobe effects can read as cuts. Check the sheet and adjust `--hard`.
- Two similar shots joined by a hard cut can be missed. That rarely changes the averages much, but the shot list will
  be off by one.
- Shot length is the measurement people feel most. If you can only fix one thing, fix that.
- Store the grammar, not the reference. The JSON is small and safe to share; the reference may not be yours to share.
