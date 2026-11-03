#!/usr/bin/env python3
"""reelgrammar: measure the editing grammar of a reference video, check a draft against it,
and check that the draft borrowed the grammar and not the footage.

Commands
  read VIDEO --out DIR            measure shots, cuts, transitions, pacing, look and motion
  match DRAFT --grammar FILE      compare a draft video with a saved grammar (exit 1 if any row is OFF)
  copycheck DRAFT REFERENCE       look for reused frames and traced timing (exit 2 on ECHO)
  sheet VIDEO --out FILE.png      contact sheet: one frame from the middle of every shot

Needs: python3, numpy, ffmpeg and ffprobe on PATH. Pillow only for `sheet`.
"""
import argparse, csv, json, math, os, subprocess, sys

import numpy as np

VERSION = "1.0.0"
BUCKETS = [(0, 0.5, "<0.5s"), (0.5, 1, "0.5-1s"), (1, 2, "1-2s"), (2, 4, "2-4s"), (4, 8, "4-8s"), (8, 1e9, ">8s")]
TRANS_KINDS = ["hard", "soft", "dip_black", "flash_white"]
MOTION_KINDS = ["still", "gentle", "busy"]

DEFAULTS = dict(fps=10.0, hard=0.30, soft=0.30, blend=0.40, window=5, slug=1.5)


# ---------------------------------------------------------------- decoding
def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height:format=duration", "-of", "json", path],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"ffprobe could not read {path}: {out.stderr.strip()[:200]}")
    info = json.loads(out.stdout)
    st = (info.get("streams") or [{}])[0]
    w, h = int(st.get("width", 0)), int(st.get("height", 0))
    if not w or not h:
        raise SystemExit(f"no video stream in {path}")
    dur = float((info.get("format") or {}).get("duration") or 0)
    return w, h, dur


def decode(path, fps):
    """Return (frames uint8 [N,H,W,3], fps, (src_w, src_h), duration)."""
    w, h, dur = probe(path)
    if w >= h:
        tw, th = 128, max(2, int(round(128 * h / w / 2)) * 2)
    else:
        th, tw = 128, max(2, int(round(128 * w / h / 2)) * 2)
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-an", "-vf",
           f"fps={fps},scale={tw}:{th}:flags=area", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True)
    if raw.returncode != 0:
        raise SystemExit(f"ffmpeg could not decode {path}: {raw.stderr.decode(errors='ignore')[:200]}")
    n = len(raw.stdout) // (tw * th * 3)
    if n < 2:
        raise SystemExit(f"{path} is too short to measure (got {n} frames)")
    frames = np.frombuffer(raw.stdout[: n * tw * th * 3], np.uint8).reshape(n, th, tw, 3)
    if not dur:
        dur = n / fps
    return frames, fps, (w, h), dur


# ---------------------------------------------------------------- per-frame signals
def luma(fr):
    f = fr.astype(np.float32) / 255.0
    return 0.2126 * f[..., 0] + 0.7152 * f[..., 1] + 0.0722 * f[..., 2]


def histograms(frames):
    q = (frames // 64).astype(np.int32)  # 4 levels per channel
    idx = q[..., 0] * 16 + q[..., 1] * 4 + q[..., 2]
    n = frames.shape[0]
    hist = np.zeros((n, 64), np.float32)
    flat = idx.reshape(n, -1)
    for i in range(n):
        hist[i] = np.bincount(flat[i], minlength=64)
    hist /= flat.shape[1]
    return hist


def change(hist, gray, a, b):
    """0..1 change score between frame indices a and b."""
    hd = 0.5 * float(np.abs(hist[a] - hist[b]).sum())
    pd = float(np.abs(gray[a] - gray[b]).mean())
    return 0.6 * hd + 0.4 * min(1.0, pd * 2.0)


def shift(g1, g2):
    """Phase correlation: (dx, dy) in pixels that moves g1's content onto g2."""
    h, w = g1.shape
    win = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    a = np.fft.fft2((g1 - g1.mean()) * win)
    b = np.fft.fft2((g2 - g2.mean()) * win)
    r = b * np.conj(a)
    r /= np.abs(r) + 1e-9
    c = np.abs(np.fft.ifft2(r))
    dy, dx = np.unravel_index(int(np.argmax(c)), c.shape)
    if dy > h // 2:
        dy -= h
    if dx > w // 2:
        dx -= w
    return float(dx), float(dy), float(c.max())


# ---------------------------------------------------------------- segmentation
def find_boundaries(frames, fps, p):
    n = len(frames)
    gray = np.stack([luma(f) for f in frames])
    hist = histograms(frames)
    step = np.zeros(n, np.float32)
    for t in range(1, n):
        step[t] = change(hist, gray, t - 1, t)
    hard = []
    for t in range(1, n):
        lo, hi = max(1, t - 3), min(n, t + 4)
        win = step[lo:hi]
        if step[t] < p["hard"] or step[t] < win.max():
            continue
        others = np.delete(win, t - lo)
        second = float(others.max()) if len(others) else 0.0
        if step[t] >= 2.0 * second:
            hard.append(t)
    K = int(p["window"])
    soft = []
    run = []
    for t in range(K, n - K):
        if any(abs(t - c) <= K + 1 for c in hard):
            if run:
                soft.append(run); run = []
            continue
        span = change(hist, gray, t - K, t + K)
        local = step[t - K + 1:t + K + 1]
        a, b, m = gray[t - K], gray[t + K], gray[t]
        dark = float(m.mean()) < 0.06 and float(a.mean()) > 0.1 and float(b.mean()) > 0.1
        bright = float(m.mean()) > 0.94 and float(a.mean()) < 0.85 and float(b.mean()) < 0.85
        if (span >= p["soft"] and local.max() < p["hard"]) or dark or bright:
            spread = float(np.abs(a - b).mean()) + 1e-6
            err = float(np.abs(m - 0.5 * (a + b)).mean())
            if err / spread < p["blend"] or dark or bright:
                run.append(t)
                continue
        if run:
            soft.append(run); run = []
    if run:
        soft.append(run)
    bounds = [(t, "hard", 0.0) for t in hard]
    for r in soft:
        mid = r[len(r) // 2]
        seg = gray[max(0, r[0] - K):min(n, r[-1] + K + 1)].mean(axis=(1, 2))
        kind = "soft"
        if seg.min() < 0.06:
            kind = "dip_black"
        elif seg.max() > 0.94:
            kind = "flash_white"
        bounds.append((mid, kind, round((len(r) + K) / fps, 2)))
    bounds.sort()
    return bounds, gray, step


def build_shots(frames, fps, p, duration):
    bounds, gray, step = find_boundaries(frames, fps, p)
    n = len(frames)
    edges = [0] + [b[0] for b in bounds] + [n]
    kinds = [b[1] for b in bounds]
    shots = []
    for i in range(len(edges) - 1):
        a, b = edges[i], edges[i + 1]
        if b - a < 1:
            continue
        shots.append({"a": a, "b": b, "in": kinds[i - 1] if i > 0 else "start"})
    # a very short, nearly black shot between two cuts is a dip, not a shot
    merged = []
    for s in shots:
        seg = gray[s["a"]:s["b"]]
        dur = (s["b"] - s["a"]) / fps
        if merged and dur <= p["slug"] and float(seg.mean()) < 0.05 and s is not shots[-1]:
            merged[-1]["dip_after"] = True
            continue
        if merged and merged[-1].get("dip_after"):
            s["in"] = "dip_black"
            merged[-1].pop("dip_after")
        merged.append(s)
    for s in merged:
        s.pop("dip_after", None)
    scale = duration / (n / fps) if n else 1.0
    out = []
    t0 = 0.0
    for i, s in enumerate(merged):
        seg_frames = frames[s["a"]:s["b"]]
        seg_gray = gray[s["a"]:s["b"]]
        start = s["a"] / fps * scale
        end = s["b"] / fps * scale
        if i == len(merged) - 1:
            end = duration
        if i == 0:
            start = 0.0
        shot = {"n": i + 1, "start": round(start, 2), "end": round(end, 2),
                "dur": round(end - start, 2), "in": s["in"]}
        shot.update(shot_look(seg_frames, seg_gray))
        shot.update(shot_motion(seg_gray, fps))
        shot["frames"] = [s["a"], s["b"]]
        out.append(shot)
        t0 = end
    return out


# ---------------------------------------------------------------- look and motion
def palette(frames, k=5):
    q = (frames // 32).astype(np.int32)
    idx = (q[..., 0] * 64 + q[..., 1] * 8 + q[..., 2]).ravel()
    counts = np.bincount(idx, minlength=512)
    order = np.argsort(counts)[::-1]
    total = counts.sum()
    picked = []
    for b in order:
        if counts[b] == 0 or len(picked) >= k:
            break
        rgb = np.array([(b // 64) * 32 + 16, ((b // 8) % 8) * 32 + 16, (b % 8) * 32 + 16]) / 255.0
        if any(np.linalg.norm(rgb - np.array(c)) < 0.2 for c, _ in picked):
            continue
        picked.append((rgb.tolist(), counts[b] / total))
    return [{"hex": "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in c), "share": round(float(s), 3)}
            for c, s in picked]


def look_stats(frames, gray):
    f = frames.astype(np.float32) / 255.0
    mx, mn = f.max(axis=-1), f.min(axis=-1)
    sat = np.where(mx > 1e-3, (mx - mn) / np.maximum(mx, 1e-3), 0)
    return {"luma": round(float(gray.mean()), 3), "contrast": round(float(gray.std()), 3),
            "saturation": round(float(sat.mean()), 3),
            "warmth": round(float((f[..., 0] - f[..., 2]).mean()), 3),
            "black_share": round(float((gray < 0.08).mean()), 3)}


def shot_look(frames, gray):
    d = look_stats(frames, gray)
    d["palette"] = [c["hex"] for c in palette(frames, 3)]
    return d


def shot_motion(gray, fps):
    m = len(gray)
    if m < 3:
        return {"motion": "still", "energy": 0.0, "camera": "unknown"}
    inner = gray[1:-1] if m > 4 else gray
    diffs = np.abs(np.diff(inner, axis=0)).mean(axis=(1, 2))
    energy = float(np.median(diffs)) if len(diffs) else 0.0
    kind = "still" if energy < 0.008 else ("gentle" if energy < 0.03 else "busy")
    w = gray.shape[2]
    sx, sy = [], []
    for i in range(1, m):
        dx, dy, conf = shift(gray[i - 1], gray[i])
        if conf > 0.05:
            sx.append(dx); sy.append(dy)
    camera = "locked"
    if sx:
        secs = max(m / fps, 1e-6)
        net_x, net_y = sum(sx) / w / secs, sum(sy) / w / secs
        jitter = float(np.std(sx) + np.std(sy)) / w
        if abs(net_x) >= 0.05 and abs(net_x) >= abs(net_y):
            camera = "pan_left" if net_x > 0 else "pan_right"
        elif abs(net_y) >= 0.05:
            camera = "tilt_up" if net_y > 0 else "tilt_down"
        elif jitter > 0.012:
            camera = "handheld"
    return {"motion": kind, "energy": round(energy, 4), "camera": camera}


# ---------------------------------------------------------------- grammar
def bucket_shares(durs):
    if not durs:
        return {b[2]: 0.0 for b in BUCKETS}
    out = {}
    for lo, hi, name in BUCKETS:
        out[name] = round(sum(1 for d in durs if lo <= d < hi) / len(durs), 3)
    return out


def pacing_curve(shots, duration, parts=10):
    cuts = [s["start"] for s in shots[1:]]
    seg = duration / parts if duration else 1
    curve = []
    for i in range(parts):
        lo, hi = i * seg, (i + 1) * seg
        c = sum(1 for x in cuts if lo <= x < hi)
        curve.append(round(c / seg * 60, 1))
    third = max(1, parts // 3)
    first, last = sum(curve[:third]) / third, sum(curve[-third:]) / third
    if len(cuts) < 4:
        trend = "too_few_cuts"
    elif last > first * 1.3 + 1:
        trend = "speeds_up"
    elif first > last * 1.3 + 1:
        trend = "slows_down"
    else:
        trend = "steady"
    return curve, trend


def grammar_from(path, p=None):
    p = dict(DEFAULTS, **(p or {}))
    frames, fps, (w, h), duration = decode(path, p["fps"])
    shots = build_shots(frames, fps, p, duration)
    durs = [s["dur"] for s in shots]
    gray = np.stack([luma(f) for f in frames])
    look = look_stats(frames, gray)
    look["palette"] = palette(frames, 5)
    curve, trend = pacing_curve(shots, duration)
    trans = [s["in"] for s in shots[1:]]
    tmix = {k: round(trans.count(k) / len(trans), 3) if trans else 0.0 for k in TRANS_KINDS}
    mmix = {k: round(sum(s["dur"] for s in shots if s["motion"] == k) / max(duration, 1e-6), 3) for k in MOTION_KINDS}
    cams = {}
    for s in shots:
        cams[s["camera"]] = cams.get(s["camera"], 0) + 1
    arr = np.array(durs) if durs else np.array([0.0])
    g = {
        "tool": "reelgrammar", "version": VERSION,
        "source": {"file": os.path.basename(path), "width": w, "height": h,
                   "aspect": f"{w}:{h}", "orientation": "landscape" if w > h else ("portrait" if h > w else "square")},
        "params": p,
        "duration": round(duration, 2),
        "shots": len(shots),
        "cuts_per_minute": round((len(shots) - 1) / duration * 60, 1) if duration else 0,
        "shot_length": {"mean": round(float(arr.mean()), 2), "median": round(float(np.median(arr)), 2),
                        "p10": round(float(np.percentile(arr, 10)), 2), "p90": round(float(np.percentile(arr, 90)), 2),
                        "shortest": round(float(arr.min()), 2), "longest": round(float(arr.max()), 2),
                        "mix": bucket_shares(durs)},
        "pacing": {"curve_cpm": curve, "trend": trend},
        "transitions": tmix,
        "look": look,
        "motion": {"mix_by_time": mmix, "camera_counts": cams},
        "shot_list": [{k: v for k, v in s.items() if k != "frames"} for s in shots],
    }
    return g, frames, shots


def grammar_md(g):
    sl = g["shot_length"]
    L = []
    L.append(f"# Reel grammar: {g['source']['file']}\n")
    L.append("Numbers only. No frames, characters or audio from the source are stored here.\n")
    L.append("## Rhythm\n")
    L.append(f"- Runtime {g['duration']} s, {g['shots']} shots, {g['cuts_per_minute']} cuts per minute.")
    L.append(f"- Shot length: mean {sl['mean']} s, median {sl['median']} s, 10% of shots under {sl['p10']} s, 10% over {sl['p90']} s, longest {sl['longest']} s.")
    L.append("- Mix: " + ", ".join(f"{k} {round(v*100)}%" for k, v in sl["mix"].items() if v))
    L.append(f"- Pacing across the runtime (cuts per minute, ten slices): {g['pacing']['curve_cpm']} ({g['pacing']['trend'].replace('_', ' ')}).\n")
    L.append("## Joins\n")
    L.append("- " + ", ".join(f"{k.replace('_', ' ')} {round(v*100)}%" for k, v in g["transitions"].items()) + "\n")
    lk = g["look"]
    L.append("## Look\n")
    L.append(f"- Brightness {lk['luma']}, contrast {lk['contrast']}, saturation {lk['saturation']}, warmth {lk['warmth']} (red minus blue), near-black area {round(lk['black_share']*100)}%.")
    L.append("- Palette: " + ", ".join(f"{c['hex']} ({round(c['share']*100)}%)" for c in lk["palette"]) + "\n")
    L.append("## Motion\n")
    L.append("- Share of runtime: " + ", ".join(f"{k} {round(v*100)}%" for k, v in g["motion"]["mix_by_time"].items()))
    L.append("- Camera (per shot, sideways moves only; pushes and zooms are not measured): " + ", ".join(f"{k} {v}" for k, v in g["motion"]["camera_counts"].items()) + "\n")
    L.append("## Shots\n")
    L.append("| # | start | dur | joined by | motion | camera | palette |")
    L.append("|---|---|---|---|---|---|---|")
    for s in g["shot_list"]:
        L.append(f"| {s['n']} | {s['start']} | {s['dur']} | {s['in']} | {s['motion']} | {s['camera']} | {' '.join(s['palette'])} |")
    return "\n".join(L) + "\n"


def cmd_read(a):
    g, frames, shots = grammar_from(a.video, params_from(a))
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "grammar.json"), "w") as f:
        json.dump(g, f, indent=1)
    with open(os.path.join(a.out, "grammar.md"), "w") as f:
        f.write(grammar_md(g))
    with open(os.path.join(a.out, "shots.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["n", "start", "end", "dur", "in", "motion", "camera", "luma", "saturation", "palette"])
        for s in g["shot_list"]:
            wr.writerow([s["n"], s["start"], s["end"], s["dur"], s["in"], s["motion"], s["camera"], s["luma"], s["saturation"], " ".join(s["palette"])])
    print(f"{g['shots']} shots, mean {g['shot_length']['mean']} s, {g['cuts_per_minute']} cuts/min, pacing {g['pacing']['trend']}")
    print(f"wrote {a.out}/grammar.json, grammar.md, shots.csv")
    return 0


# ---------------------------------------------------------------- match
def hex_rgb(h):
    return np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)]) / 255.0


def mix_gap(a, b):
    keys = set(a) | set(b)
    return round(0.5 * sum(abs(a.get(k, 0) - b.get(k, 0)) for k in keys), 3)


def band(value, on, close, higher_is_better=False):
    if higher_is_better:
        return "ON" if value >= on else ("CLOSE" if value >= close else "OFF")
    return "ON" if value <= on else ("CLOSE" if value <= close else "OFF")


def compare(ref, dr):
    rows = []
    r_m, d_m = ref["shot_length"]["mean"], dr["shot_length"]["mean"]
    ratio = d_m / r_m if r_m else 1.0
    v = band(abs(ratio - 1), 0.15, 0.30)
    fix = "" if v == "ON" else (f"cut shots to about {round(r_m, 1)} s on average (now {d_m} s)" if ratio > 1 else f"let shots run longer, about {round(r_m, 1)} s on average (now {d_m} s)")
    rows.append(("shot length (mean)", f"{r_m} s", f"{d_m} s", v, fix))
    gap = mix_gap(ref["shot_length"]["mix"], dr["shot_length"]["mix"])
    v = band(gap, 0.15, 0.30)
    worst = max(ref["shot_length"]["mix"], key=lambda k: abs(ref["shot_length"]["mix"][k] - dr["shot_length"]["mix"].get(k, 0)))
    want, have = ref["shot_length"]["mix"][worst], dr["shot_length"]["mix"].get(worst, 0)
    fix = "" if v == "ON" else f"{'more' if want > have else 'fewer'} shots in the {worst} range ({round(want*100)}% in the reference, {round(have*100)}% here)"
    rows.append(("shot length mix", "", f"gap {gap}", v, fix))
    rc, dc = ref["pacing"]["curve_cpm"], dr["pacing"]["curve_cpm"]
    if ref["pacing"]["trend"] == "too_few_cuts" or dr["pacing"]["trend"] == "too_few_cuts":
        rows.append(("pacing shape", ref["pacing"]["trend"], dr["pacing"]["trend"], "SKIP", "too few cuts on one side to compare a shape"))
    else:
        a, b = np.array(rc, float), np.array(dc, float)
        corr = float(np.corrcoef(a, b)[0, 1]) if a.std() > 0 and b.std() > 0 else (1.0 if a.std() == b.std() == 0 else 0.0)
        v = band(corr, 0.6, 0.3, higher_is_better=True)
        if ref["pacing"]["trend"] != dr["pacing"]["trend"] and v == "ON":
            v = "CLOSE"
        fix = "" if v == "ON" else f"the reference {ref['pacing']['trend'].replace('_', ' ')}; yours {dr['pacing']['trend'].replace('_', ' ')}. Move cuts so the busy slices line up"
        rows.append(("pacing shape", ref["pacing"]["trend"], f"{dr['pacing']['trend']} (r={round(corr, 2)})", v, fix))
    if sum(ref["transitions"].values()) and sum(dr["transitions"].values()):
        gap = mix_gap(ref["transitions"], dr["transitions"])
        v = band(gap, 0.15, 0.30)
        k = max(TRANS_KINDS, key=lambda x: abs(ref["transitions"][x] - dr["transitions"].get(x, 0)))
        fix = "" if v == "ON" else f"{'more' if ref['transitions'][k] > dr['transitions'].get(k, 0) else 'fewer'} {k.replace('_', ' ')} joins ({round(ref['transitions'][k]*100)}% vs {round(dr['transitions'].get(k, 0)*100)}%)"
        rows.append(("joins", "", f"gap {gap}", v, fix))
    for key, label, on, close in (("luma", "brightness", 0.06, 0.12), ("contrast", "contrast", 0.04, 0.08),
                                  ("saturation", "saturation", 0.06, 0.12), ("warmth", "warmth", 0.04, 0.08)):
        r, d = ref["look"][key], dr["look"][key]
        v = band(abs(r - d), on, close)
        fix = "" if v == "ON" else f"{'raise' if r > d else 'lower'} {label} toward {r} (now {d})"
        rows.append((label, r, d, v, fix))
    rp = [hex_rgb(c["hex"]) for c in ref["look"]["palette"]]
    dp = [hex_rgb(c["hex"]) for c in dr["look"]["palette"]]
    if rp and dp:
        dist = float(np.mean([min(np.linalg.norm(x - y) for y in dp) for x in rp])) / math.sqrt(3)
        missing = [c["hex"] for c, x in zip(ref["look"]["palette"], rp) if min(np.linalg.norm(x - y) for y in dp) / math.sqrt(3) > 0.22]
        v = band(dist, 0.12, 0.22)
        fix = "" if v == "ON" else "bring in the reference colours " + ", ".join(missing[:3])
        rows.append(("palette", " ".join(c["hex"] for c in ref["look"]["palette"]), " ".join(c["hex"] for c in dr["look"]["palette"]), v, fix))
    gap = mix_gap(ref["motion"]["mix_by_time"], dr["motion"]["mix_by_time"])
    v = band(gap, 0.15, 0.30)
    k = max(MOTION_KINDS, key=lambda x: abs(ref["motion"]["mix_by_time"][x] - dr["motion"]["mix_by_time"].get(x, 0)))
    fix = "" if v == "ON" else f"{'more' if ref['motion']['mix_by_time'][k] > dr['motion']['mix_by_time'].get(k, 0) else 'less'} {k} screen time ({round(ref['motion']['mix_by_time'][k]*100)}% vs {round(dr['motion']['mix_by_time'].get(k, 0)*100)}%)"
    rows.append(("motion mix", "", f"gap {gap}", v, fix))
    ro, do = ref["source"]["orientation"], dr["source"]["orientation"]
    rows.append(("orientation", ro, do, "ON" if ro == do else "OFF", "" if ro == do else f"reframe to {ref['source']['aspect']}"))
    return rows


def render_match(rows, ref, dr):
    pts = {"ON": 2, "CLOSE": 1, "OFF": 0}
    scored = [r for r in rows if r[3] in pts]
    score = round(100 * sum(pts[r[3]] for r in scored) / (2 * len(scored))) if scored else 0
    L = [f"# Match: {dr['source']['file']} against {ref['source']['file']}\n",
         f"Score {score}/100. ON {sum(r[3]=='ON' for r in rows)}, CLOSE {sum(r[3]=='CLOSE' for r in rows)}, OFF {sum(r[3]=='OFF' for r in rows)}.\n",
         "| check | reference | draft | verdict | what to change |", "|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} |")
    fixes = [r for r in rows if r[3] == "OFF"] + [r for r in rows if r[3] == "CLOSE"]
    if fixes:
        L.append("\n## First three changes\n")
        for i, r in enumerate(fixes[:3], 1):
            L.append(f"{i}. {r[4]}")
    return "\n".join(L) + "\n", score


def load_grammar(path, p):
    if path.endswith(".json"):
        with open(path) as f:
            return json.load(f)
    return grammar_from(path, p)[0]


def cmd_match(a):
    p = params_from(a)
    ref = load_grammar(a.grammar, p)
    dr, _, _ = grammar_from(a.draft, dict(ref.get("params", {}), **{k: v for k, v in p.items() if k in ("fps",)}))
    rows = compare(ref, dr)
    text, score = render_match(rows, ref, dr)
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "match.md"), "w") as f:
            f.write(text)
        with open(os.path.join(a.out, "draft.grammar.json"), "w") as f:
            json.dump(dr, f, indent=1)
        with open(os.path.join(a.out, "match.json"), "w") as f:
            json.dump({"score": score, "rows": [dict(zip(["check", "reference", "draft", "verdict", "fix"], r)) for r in rows]}, f, indent=1)
    print(text)
    return 1 if any(r[3] == "OFF" for r in rows) else 0


# ---------------------------------------------------------------- copycheck
def dhash(gray):
    h, w = gray.shape
    ys = np.linspace(0, h, 9).astype(int)
    xs = np.linspace(0, w, 10).astype(int)
    small = np.array([[gray[ys[i]:ys[i + 1], xs[j]:xs[j + 1]].mean() for j in range(9)] for i in range(8)])
    bits = (small[:, 1:] > small[:, :-1]).ravel()
    return int("".join("1" if b else "0" for b in bits), 2)


def textured(gray):
    return float(gray.std()) >= 0.03


def sample_hashes(frames, shots):
    out = []
    for s in shots:
        a, b = s["frames"]
        for f in (0.25, 0.5, 0.75):
            i = min(b - 1, a + int((b - a) * f))
            g = luma(frames[i])
            if textured(g):
                out.append((s["n"], dhash(g)))
    return out


def longest_trace(rd, dd, tol=0.12):
    best, at = 0, None
    for i in range(len(dd)):
        for j in range(len(rd)):
            k = 0
            while i + k < len(dd) and j + k < len(rd) and abs(dd[i + k] - rd[j + k]) <= tol:
                k += 1
            if k > best:
                best, at = k, (i + 1, j + 1)
    return best, at


def copycheck(draft, ref, p):
    dg, dfr, dsh = grammar_from(draft, p)
    rg, rfr, rsh = grammar_from(ref, p)
    rh = sample_hashes(rfr, rsh)
    dh = sample_hashes(dfr, dsh)
    flags = []
    per = {}
    for n, h in dh:
        if not rh:
            break
        dist, rn = min((bin(h ^ x).count("1"), m) for m, x in rh)
        if n not in per or dist < per[n][0]:
            per[n] = (dist, rn)
    for n, (dist, rn) in sorted(per.items()):
        if dist <= 6:
            flags.append(("ECHO", f"draft shot {n} looks like a frame from reference shot {rn} (distance {dist}/64). Replace it with your own material."))
        elif dist <= 12:
            flags.append(("LOOKALIKE", f"draft shot {n} is close to reference shot {rn} (distance {dist}/64). Check it by eye."))
    run, at = longest_trace([s["dur"] for s in rsh], [s["dur"] for s in dsh])
    if run >= 6:
        flags.append(("TIMING_TRACE", f"{run} shots in a row from draft shot {at[0]} copy the reference durations from shot {at[1]} within 0.12 s. Borrow the rhythm, not the exact cut list."))
    rp = [c["hex"] for c in rg["look"]["palette"]]
    dp = [c["hex"] for c in dg["look"]["palette"]]
    if rp and rp == dp:
        flags.append(("PALETTE_CLONE", "the five main colours are identical in order. Fine for a homage; for an original piece, shift at least one."))
    untested = sum(1 for s in dsh) - len(per)
    return flags, untested, len(dsh)


def cmd_copycheck(a):
    flags, untested, total = copycheck(a.draft, a.reference, params_from(a))
    if not flags:
        print(f"CLEAR: no reused frames or traced timing found across {total} draft shots.")
    for k, msg in flags:
        print(f"{k}: {msg}")
    if untested:
        print(f"note: {untested} draft shots were too flat (plain colour) to compare by picture.")
    return 2 if any(k == "ECHO" for k, _ in flags) else (1 if flags else 0)


# ---------------------------------------------------------------- sheet
def cmd_sheet(a):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("sheet needs Pillow: pip install pillow", file=sys.stderr)
        return 3
    g, frames, shots = grammar_from(a.video, params_from(a))
    tiles = []
    for s in g["shot_list"]:
        t = (s["start"] + s["end"]) / 2
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", a.video, "-frames:v", "1", "-vf", "scale=240:-2",
                            "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
        from io import BytesIO
        try:
            im = Image.open(BytesIO(r.stdout)).convert("RGB")
        except Exception:
            im = Image.new("RGB", (240, 135), (40, 40, 40))
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, 150, 14], fill=(0, 0, 0))
        d.text((3, 1), f"{s['n']}  {s['dur']}s  {s['in']}", fill=(255, 255, 255))
        tiles.append(im)
    cols = min(a.cols, len(tiles)) or 1
    rows = math.ceil(len(tiles) / cols)
    tw, th = tiles[0].size
    sheet = Image.new("RGB", (cols * tw, rows * th), (20, 20, 20))
    for i, im in enumerate(tiles):
        sheet.paste(im.resize((tw, th)), ((i % cols) * tw, (i // cols) * th))
    sheet.save(a.out)
    print(f"wrote {a.out} with {len(tiles)} shots")
    return 0


# ---------------------------------------------------------------- cli
def params_from(a):
    p = {}
    for k in ("fps", "hard", "soft"):
        v = getattr(a, k, None)
        if v is not None:
            p[k] = v
    return p


def main(argv=None):
    ap = argparse.ArgumentParser(prog="reelgrammar", description="Measure, match and copy-check video editing grammar.")
    ap.add_argument("--version", action="version", version=VERSION)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def tuning(s):
        s.add_argument("--fps", type=float, help="analysis frames per second (default 10)")
        s.add_argument("--hard", type=float, help="hard-cut threshold 0..1 (default 0.30; lower finds more cuts)")
        s.add_argument("--soft", type=float, help="dissolve/fade threshold 0..1 (default 0.30)")

    s = sub.add_parser("read"); s.add_argument("video"); s.add_argument("--out", required=True); tuning(s); s.set_defaults(fn=cmd_read)
    s = sub.add_parser("match"); s.add_argument("draft"); s.add_argument("--grammar", required=True, help="grammar.json or a reference video"); s.add_argument("--out"); tuning(s); s.set_defaults(fn=cmd_match)
    s = sub.add_parser("copycheck"); s.add_argument("draft"); s.add_argument("reference"); tuning(s); s.set_defaults(fn=cmd_copycheck)
    s = sub.add_parser("sheet"); s.add_argument("video"); s.add_argument("--out", required=True); s.add_argument("--cols", type=int, default=4); tuning(s); s.set_defaults(fn=cmd_sheet)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
