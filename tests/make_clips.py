"""Synthetic clips with known cuts, used by the tests and handy for trying the script."""
import subprocess
import numpy as np

W, H, FPS = 160, 90, 25


def scene(seed, tint):
    rng = np.random.default_rng(seed)
    base = rng.random((H // 6 + 2, W // 6 + 2))
    big = np.kron(base, np.ones((6, 6)))[:H + 12, :W + 12]
    img = np.zeros((H, W * 3, 3))
    wide = np.tile(big, (1, 4))[:H, :W * 3]
    for c in range(3):
        img[..., c] = np.clip(0.15 + 0.7 * wide * tint[c], 0, 1)
    return img


def render(path, plan):
    """plan: list of dicts {seed, tint, secs, pan(px/frame), join: 'cut'|'dissolve'|'dip', join_secs}"""
    frames = []
    for i, sh in enumerate(plan):
        img = scene(sh["seed"], sh["tint"]) * (0 if sh.get("black") else 1)
        n = int(round(sh["secs"] * FPS))
        clip = []
        for k in range(n):
            off = int(round(sh.get("pan", 0) * k)) % (W * 2)
            clip.append(img[:, off:off + W])
        join = sh.get("join", "cut")
        js = int(round(sh.get("join_secs", 0.8) * FPS))
        if frames and join == "dissolve":
            tail = frames[-js:]
            del frames[-js:]
            for k in range(js):
                a = (k + 1) / (js + 1)
                frames.append(tail[k] * (1 - a) + clip[k] * a)
            clip = clip[js:]
        elif frames and join == "dip":
            half = js // 2
            for k in range(half):
                frames[-half + k] = frames[-half + k] * (1 - (k + 1) / half)
            for k in range(half):
                clip[k] = clip[k] * ((k + 1) / half)
        frames.extend(clip)
    data = (np.clip(np.stack(frames), 0, 1) * 255).astype(np.uint8)
    p = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                        "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", path], input=data.tobytes())
    assert p.returncode == 0
    return path


TINTS = [(1, 0.3, 0.2), (0.2, 0.5, 1), (0.3, 1, 0.4), (1, 0.9, 0.2), (0.8, 0.2, 1), (0.2, 1, 1), (1, 0.5, 0.7), (0.6, 0.6, 0.6)]


def fast_plan():
    durs = [1.2, 0.8, 1.0, 0.6, 1.4, 0.9, 0.7, 1.1, 0.8, 1.0]
    return [{"seed": i, "tint": TINTS[i % 8], "secs": d} for i, d in enumerate(durs)]


def slow_plan():
    durs = [3.5, 4.0, 3.0, 4.5]
    return [{"seed": 50 + i, "tint": TINTS[(i + 3) % 8], "secs": d} for i, d in enumerate(durs)]
