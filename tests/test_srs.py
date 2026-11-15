import unittest

from app.core import srs


class GradeTest(unittest.TestCase):
    NOW = 1_000_000_000_000

    def test_new_item_is_due_after_five_minutes(self):
        self.assertEqual(srs.first_due(self.NOW), self.NOW + 5 * srs.MIN)

    def test_got_walks_the_whole_schedule(self):
        waits = []
        stage = 0
        while stage < srs.MASTERED:
            out = srs.grade(stage, "got", self.NOW)
            if out.due_at is not None:
                waits.append(out.due_at - self.NOW)
            stage = out.stage
        self.assertEqual(waits, [30 * srs.MIN, 12 * srs.HOUR, srs.DAY, 2 * srs.DAY, 4 * srs.DAY, 7 * srs.DAY, 15 * srs.DAY])
        self.assertEqual(stage, srs.MASTERED)

    def test_last_review_masters_the_item(self):
        out = srs.grade(srs.MASTERED - 1, "got", self.NOW)
        self.assertEqual((out.stage, out.due_at, out.lapsed), (srs.MASTERED, None, False))

    def test_fuzzy_repeats_the_same_interval(self):
        out = srs.grade(3, "fuzzy", self.NOW)
        self.assertEqual((out.stage, out.due_at, out.lapsed), (3, self.NOW + srs.DAY, False))

    def test_forgot_restarts(self):
        out = srs.grade(5, "forgot", self.NOW)
        self.assertEqual((out.stage, out.due_at, out.lapsed), (0, self.NOW + 5 * srs.MIN, True))

    def test_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            srs.grade(0, "maybe", self.NOW)
        with self.assertRaises(ValueError):
            srs.grade(srs.MASTERED, "got", self.NOW)


if __name__ == "__main__":
    unittest.main()
