import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, HERE)
import reelgrammar as rg  # noqa: E402
import make_clips as mc  # noqa: E402

SCRIPT = os.path.join(HERE, "..", "scripts", "reelgrammar.py")
TMP = tempfile.mkdtemp(prefix="reelgrammar-")


def clip(name, plan):
    path = os.path.join(TMP, name + ".mp4")
    if not os.path.exists(path):
        mc.render(path, plan)
    return path


def run(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)


class Cuts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fast = clip("fast", mc.fast_plan())
        cls.g, _, _ = rg.grammar_from(cls.fast)

    def test_shot_count(self):
        self.assertEqual(self.g["shots"], 10)

    def test_cut_times(self):
        want, t = [], 0
        for s in mc.fast_plan()[:-1]:
            t += s["secs"]; want.append(t)
        got = [s["start"] for s in self.g["shot_list"][1:]]
        for w, x in zip(want, got):
            self.assertAlmostEqual(w, x, delta=0.12)

    def test_mean_and_median(self):
        self.assertAlmostEqual(self.g["shot_length"]["mean"], 0.95, delta=0.08)
        self.assertAlmostEqual(self.g["shot_length"]["median"], 0.95, delta=0.12)

    def test_cuts_per_minute(self):
        self.assertAlmostEqual(self.g["cuts_per_minute"], 9 / 9.5 * 60, delta=4)

    def test_mix_sums_to_one(self):
        self.assertAlmostEqual(sum(self.g["shot_length"]["mix"].values()), 1.0, delta=0.01)

    def test_all_hard(self):
        self.assertEqual(self.g["transitions"]["hard"], 1.0)

    def test_still_shots(self):
        self.assertEqual(self.g["motion"]["mix_by_time"]["busy"], 0.0)
        self.assertTrue(all(s["camera"] == "locked" for s in self.g["shot_list"]))

    def test_palette_present(self):
        self.assertTrue(1 <= len(self.g["look"]["palette"]) <= 5)
        self.assertTrue(all(c["hex"].startswith("#") and len(c["hex"]) == 7 for c in self.g["look"]["palette"]))

    def test_no_frames_stored(self):
        text = json.dumps(self.g)
        self.assertLess(len(text), 20000)
        self.assertNotIn("frames", self.g["shot_list"][0])


class Joins(unittest.TestCase):
    def test_dissolve(self):
        plan = [{"seed": 1, "tint": mc.TINTS[0], "secs": 3}, {"seed": 2, "tint": mc.TINTS[1], "secs": 3, "join": "dissolve", "join_secs": 1.2}]
        g, _, _ = rg.grammar_from(clip("dissolve", plan))
        self.assertEqual(g["shots"], 2)
        self.assertEqual(g["shot_list"][1]["in"], "soft")

    def test_dip_to_black(self):
        plan = [{"seed": 3, "tint": mc.TINTS[2], "secs": 3}, {"seed": 4, "tint": mc.TINTS[3], "secs": 3, "join": "dip", "join_secs": 1.0}]
        g, _, _ = rg.grammar_from(clip("dip", plan))
        self.assertEqual(g["shots"], 2)
        self.assertEqual(g["shot_list"][1]["in"], "dip_black")

    def test_black_slug_is_a_join(self):
        plan = [{"seed": 5, "tint": mc.TINTS[4], "secs": 2.5}, {"seed": 6, "tint": mc.TINTS[0], "secs": 0.6, "black": True}, {"seed": 7, "tint": mc.TINTS[5], "secs": 2.5}]
        g, _, _ = rg.grammar_from(clip("slug", plan))
        self.assertEqual(g["shots"], 2)
        self.assertEqual(g["shot_list"][1]["in"], "dip_black")

    def test_flash_white(self):
        plan = [{"seed": 11, "tint": mc.TINTS[1], "secs": 3}, {"seed": 12, "tint": mc.TINTS[2], "secs": 3}]
        path = os.path.join(TMP, "flash.mp4")
        if not os.path.exists(path):
            import numpy as np
            frames = []
            for i, sh in enumerate(plan):
                img = mc.scene(sh["seed"], sh["tint"])[:, :mc.W]
                frames += [img] * int(sh["secs"] * mc.FPS)
            n = int(3 * mc.FPS)
            for k in range(-12, 13):
                a = 1 - abs(k) / 13
                frames[n + k] = frames[n + k] * (1 - a) + a
            data = (np.clip(np.stack(frames), 0, 1) * 255).astype("uint8")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{mc.W}x{mc.H}", "-r", str(mc.FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", path], input=data.tobytes(), check=True)
        g, _, _ = rg.grammar_from(path)
        self.assertEqual(g["shots"], 2)
        self.assertEqual(g["shot_list"][1]["in"], "flash_white")


class Motion(unittest.TestCase):
    def test_pan_detected(self):
        plan = [{"seed": 9, "tint": mc.TINTS[6], "secs": 4, "pan": 2}]
        g, _, _ = rg.grammar_from(clip("pan", plan))
        self.assertEqual(g["shots"], 1)
        self.assertIn(g["shot_list"][0]["camera"], ("pan_left", "pan_right"))
        self.assertNotEqual(g["shot_list"][0]["motion"], "still")

    def test_pan_direction(self):
        plan = [{"seed": 9, "tint": mc.TINTS[6], "secs": 4, "pan": 2}]
        g, _, _ = rg.grammar_from(clip("pan", plan))
        # the window slides right over the image, so content moves left: camera pans right
        self.assertEqual(g["shot_list"][0]["camera"], "pan_right")

    def test_shift_estimate(self):
        import numpy as np
        rng = np.random.default_rng(0)
        a = rng.random((72, 128)).astype("float32")
        b = np.roll(a, 5, axis=1)
        dx, dy, _ = rg.shift(a, b)
        self.assertEqual((dx, dy), (5.0, 0.0))


class Pacing(unittest.TestCase):
    def test_speeds_up(self):
        durs = [3, 2.5, 2, 1.5, 1, 0.8, 0.6, 0.5, 0.5, 0.4, 0.4, 0.4]
        shots, t = [], 0
        for d in durs:
            shots.append({"start": t}); t += d
        curve, trend = rg.pacing_curve(shots, t)
        self.assertEqual(trend, "speeds_up")
        self.assertEqual(len(curve), 10)

    def test_steady(self):
        shots = [{"start": i * 1.0} for i in range(20)]
        _, trend = rg.pacing_curve(shots, 20)
        self.assertEqual(trend, "steady")

    def test_too_few(self):
        _, trend = rg.pacing_curve([{"start": 0}, {"start": 5}], 10)
        self.assertEqual(trend, "too_few_cuts")

    def test_buckets(self):
        m = rg.bucket_shares([0.3, 0.7, 1.5, 3, 5, 9])
        self.assertTrue(all(abs(v - 1 / 6) < 0.01 for v in m.values()))


class Match(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fast = clip("fast", mc.fast_plan())
        cls.slow = clip("slow", mc.slow_plan())
        cls.gf, _, _ = rg.grammar_from(cls.fast)
        cls.gs, _, _ = rg.grammar_from(cls.slow)

    def test_self_match_all_on(self):
        rows = rg.compare(self.gf, self.gf)
        self.assertTrue(all(r[3] in ("ON", "SKIP") for r in rows), rows)

    def test_slow_vs_fast_is_off(self):
        rows = {r[0]: r for r in rg.compare(self.gf, self.gs)}
        self.assertEqual(rows["shot length (mean)"][3], "OFF")
        self.assertIn("cut shots", rows["shot length (mean)"][4])

    def test_fix_direction_longer(self):
        rows = {r[0]: r for r in rg.compare(self.gs, self.gf)}
        self.assertIn("longer", rows["shot length (mean)"][4])

    def test_render_has_score(self):
        text, score = rg.render_match(rg.compare(self.gf, self.gs), self.gf, self.gs)
        self.assertIn("Score", text)
        self.assertLess(score, 100)
        self.assertIn("First three changes", text)

    def test_orientation_row(self):
        g2 = json.loads(json.dumps(self.gf)); g2["source"]["orientation"] = "portrait"
        rows = {r[0]: r for r in rg.compare(self.gf, g2)}
        self.assertEqual(rows["orientation"][3], "OFF")

    def test_cli_exit_codes(self):
        out = os.path.join(TMP, "readfast")
        r = run("read", self.fast, "--out", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        for f in ("grammar.json", "grammar.md", "shots.csv"):
            self.assertTrue(os.path.exists(os.path.join(out, f)))
        self.assertEqual(run("match", self.fast, "--grammar", os.path.join(out, "grammar.json")).returncode, 0)
        r = run("match", self.slow, "--grammar", os.path.join(out, "grammar.json"), "--out", os.path.join(TMP, "m"))
        self.assertEqual(r.returncode, 1)
        self.assertTrue(os.path.exists(os.path.join(TMP, "m", "match.json")))

    def test_markdown(self):
        md = rg.grammar_md(self.gf)
        self.assertIn("## Rhythm", md)
        self.assertIn("| 10 |", md)


class Copy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fast = clip("fast", mc.fast_plan())
        other = [{"seed": 200 + i, "tint": mc.TINTS[(i + 5) % 8], "secs": d} for i, d in enumerate([1.3, 0.7, 1.1, 0.9, 1.2, 0.6, 1.0, 0.8])]
        cls.other = clip("other", other)

    def test_same_video_echo(self):
        flags, _, _ = rg.copycheck(self.fast, self.fast, {})
        kinds = [k for k, _ in flags]
        self.assertIn("ECHO", kinds)
        self.assertIn("TIMING_TRACE", kinds)

    def test_different_video_clear(self):
        flags, _, _ = rg.copycheck(self.other, self.fast, {})
        self.assertNotIn("ECHO", [k for k, _ in flags])
        self.assertNotIn("TIMING_TRACE", [k for k, _ in flags])

    def test_cli_copy_exit(self):
        self.assertEqual(run("copycheck", self.fast, self.fast).returncode, 2)

    def test_trace(self):
        n, at = rg.longest_trace([1, 2, 3, 4, 5, 6, 7], [9, 2, 3, 4, 5, 6, 7.05])
        self.assertEqual(n, 6)
        self.assertEqual(at, (2, 2))

    def test_dhash_flat_skipped(self):
        import numpy as np
        self.assertFalse(rg.textured(np.full((72, 128), 0.5)))


class Sheet(unittest.TestCase):
    def test_sheet(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow missing")
        out = os.path.join(TMP, "sheet.png")
        r = run("sheet", clip("fast", mc.fast_plan()), "--out", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.getsize(out) > 1000)


if __name__ == "__main__":
    unittest.main()
