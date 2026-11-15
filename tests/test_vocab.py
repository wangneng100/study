import os
import tempfile
import unittest

from app import create_app
from app.core import srs
from app.services.translation import Entry, LookupResult, TranslationError
from app.services.translation.google import GoogleTranslate
from app.services.translation.onemin import parse_json_array


def fake_lookup(words, _config):
    """Stands in for the real providers: knows every word except 'zzzz'; 'boom' is an outage."""
    if "boom" in words:
        raise TranslationError("连不上翻译服务。")
    return LookupResult([
        None if w == "zzzz" else Entry(
            word="receive" if w == "recieve" else ("Wednesday" if w == "Wedesday" else w),
            meaning="释义:" + w, lang="en", source="fake"
        )
        for w in words
    ])


class VocabApiTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        app = create_app({"DB_PATH": os.path.join(self.dir.name, "t.db"), "LOOKUP": fake_lookup, "TESTING": True})
        self.c = app.test_client()

    def tearDown(self):
        self.dir.cleanup()

    def add(self, text):
        return self.c.post("/vocab/api/words", json={"text": text})

    def test_home_and_page_render(self):
        self.assertIn("单词本", self.c.get("/").get_data(as_text=True))
        self.assertEqual(self.c.get("/vocab/").status_code, 200)

    def test_add_splits_dedupes_and_schedules(self):
        r = self.add("apple, Banana\napple；zzzz").get_json()
        self.assertEqual([w["word"] for w in r["added"]], ["apple", "Banana"])
        self.assertEqual(r["failed"], ["zzzz"])
        w = r["added"][0]
        self.assertEqual(w["stage"], 0)
        self.assertEqual(w["dueAt"] - w["addedAt"], 5 * srs.MIN)

        again = self.add("APPLE, cherry").get_json()
        self.assertEqual([w["word"] for w in again["existing"]], ["apple"])
        self.assertEqual([w["word"] for w in again["added"]], ["cherry"])
        self.assertEqual(len(self.c.get("/vocab/api/words").get_json()["words"]), 3)

    def test_corrected_spelling_is_not_stored_twice(self):
        self.add("receive")
        r = self.add("recieve").get_json()
        self.assertEqual(r["added"], [])
        self.assertEqual([w["word"] for w in r["existing"]], ["receive"])

    def test_spelling_suggestion_and_confirmation(self):
        # Adding a misspelled word returns a suggestion instead of saving immediately
        r = self.add("Wedesday").get_json()
        self.assertEqual(r["added"], [])
        self.assertEqual(len(r["suggestions"]), 1)
        s = r["suggestions"][0]
        self.assertEqual(s["original"], "Wedesday")
        self.assertEqual(s["suggested"], "Wednesday")

        # Confirming with the suggested entry saves it
        r2 = self.c.post("/vocab/api/words", json={"entry": s["entry"]}).get_json()
        self.assertEqual(len(r2["added"]), 1)
        self.assertEqual(r2["added"][0]["word"], "Wednesday")

        # Force saving the original misspelling saves Wedesday
        r3 = self.c.post("/vocab/api/words", json={"text": "Wedesday", "force": True}).get_json()
        self.assertEqual(len(r3["added"]), 1)
        self.assertEqual(r3["added"][0]["word"], "Wedesday")

    def test_outage_offers_manual_entry(self):
        r = self.add("boom")
        self.assertEqual(r.status_code, 502)
        self.assertTrue(r.get_json()["manual"])
        r = self.c.post("/vocab/api/words", json={"word": "boom", "meaning": "轰"}).get_json()
        self.assertEqual(r["added"][0]["source"], "manual")

    def test_review_reset_refresh_delete(self):
        wid = self.add("apple").get_json()["added"][0]["id"]
        url = f"/vocab/api/words/{wid}"
        w = self.c.post(url + "/review", json={"grade": "got"}).get_json()["word"]
        self.assertEqual((w["stage"], w["reviews"], w["lapses"]), (1, 1, 0))
        w = self.c.post(url + "/review", json={"grade": "forgot"}).get_json()["word"]
        self.assertEqual((w["stage"], w["reviews"], w["lapses"]), (0, 2, 1))
        self.assertEqual(self.c.post(url + "/review", json={"grade": "nope"}).status_code, 400)
        for _ in range(srs.MASTERED):
            w = self.c.post(url + "/review", json={"grade": "got"}).get_json()["word"]
        self.assertEqual((w["stage"], w["dueAt"]), (srs.MASTERED, None))
        self.assertEqual(self.c.post(url + "/review", json={"grade": "got"}).status_code, 400)
        self.assertEqual(self.c.post(url + "/reset").get_json()["word"]["stage"], 0)
        self.assertEqual(self.c.post(url + "/refresh").get_json()["word"]["source"], "fake")
        self.assertEqual(self.c.delete(url).status_code, 200)
        self.assertEqual(self.c.post(url + "/reset").status_code, 404)

    def test_study_session(self):
        self.assertEqual(self.c.get("/vocab/study?n=5").status_code, 200)
        ids = [w["id"] for w in self.add("apple, banana, cherry").get_json()["added"]]
        self.assertEqual(len(self.c.get("/vocab/api/study?n=2").get_json()["items"]), 2)
        items = self.c.get("/vocab/api/study?n=99").get_json()["items"]
        self.assertEqual(len(items), 3)
        for item in items:
            for q in item["questions"]:
                if q["type"] == "choose_meaning":
                    self.assertEqual(q["options"][q["answer"]], item["word"]["meaning"])
                    self.assertEqual(len(set(q["options"])), 3)
                elif q["type"] == "choose_word":
                    self.assertEqual(q["options"][q["answer"]], item["word"]["word"])
                else:
                    self.assertIn(item["word"]["word"], q["accept"])

        # Studied before it is due: remembering it leaves the schedule alone ...
        url = f"/vocab/api/words/{ids[0]}/review"
        r = self.c.post(url, json={"grade": "got", "study": True}).get_json()
        self.assertFalse(r["scheduleChanged"])
        self.assertEqual((r["word"]["stage"], r["word"]["reviews"]), (0, 0))
        # ... but forgetting it restarts the word.
        self.c.post(url, json={"grade": "got"})
        r = self.c.post(url, json={"grade": "forgot", "study": True}).get_json()
        self.assertTrue(r["scheduleChanged"])
        self.assertEqual((r["word"]["stage"], r["word"]["lapses"]), (0, 1))

        # A mastered word can be studied too, and only "forgot" brings it back.
        url = f"/vocab/api/words/{ids[1]}/review"
        for _ in range(srs.MASTERED):
            self.c.post(url, json={"grade": "got"})
        r = self.c.post(url, json={"grade": "fuzzy", "study": True}).get_json()
        self.assertEqual((r["scheduleChanged"], r["word"]["stage"]), (False, srs.MASTERED))
        self.assertEqual(self.c.get("/vocab/api/study?n=3").get_json()["items"][-1]["word"]["id"], ids[1])
        r = self.c.post(url, json={"grade": "forgot", "study": True}).get_json()
        self.assertEqual((r["word"]["stage"], r["word"]["dueAt"] is not None), (0, True))

    def test_requests_from_other_sites_are_refused(self):
        r = self.c.post("/vocab/api/words", json={"text": "apple"}, headers={"Origin": "https://example.com"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.c.get("/vocab/api/words", headers={"Host": "evil.example"}).status_code, 403)
        r = self.c.post("/vocab/api/words", data="text=apple", content_type="application/x-www-form-urlencoded")
        self.assertEqual(r.status_code, 415)


class QuizTest(unittest.TestCase):
    def word(self, i, word, meaning, example=""):
        return {"id": i, "word": word, "meaning": meaning, "example": example}

    def test_question_variants(self):
        import random
        from app.tools.vocab import quiz
        run = self.word(1, "run", "跑", "She runs every morning.")
        pool = [run, self.word(2, "walk", "走"), self.word(3, "stroll", "走"), self.word(4, "sit", "坐")]
        by_type = {q["type"]: q for q in quiz.build(run, pool, random.Random(1))}
        self.assertEqual(set(by_type), {"choose_meaning", "choose_word", "cloze", "spell", "listen"})
        self.assertEqual(sorted(by_type["choose_meaning"]["options"]), sorted(["跑", "走", "坐"]))  # no duplicate meanings
        self.assertEqual(by_type["cloze"]["sentence"], "She _____ every morning.")
        self.assertEqual(by_type["cloze"]["accept"], ["run", "runs"])

        # A notebook with a single word still gets typed questions, but no multiple choice.
        alone = {q["type"] for q in quiz.build(run, [run], random.Random(1))}
        self.assertEqual(alone, {"cloze", "spell", "listen"})


class ProviderParsingTest(unittest.TestCase):
    def test_onemin_reply_parsing(self):
        self.assertEqual(parse_json_array('[{"word":"a"}]'), [{"word": "a"}])
        self.assertEqual(parse_json_array('好的：\n```json\n[{"word":"a"}]\n```'), [{"word": "a"}])
        with self.assertRaises(TranslationError):
            parse_json_array("sorry")

    def test_google_reply_parsing(self):
        reply = [
            [["跑步", "run", None, None, 10], [None, None, "Pǎobù", "rən"]],
            [["verb", ["运行", "执行", "跑"], []], ["noun", ["运行", "跑步"], []]],
            "en", None, None, None, 1, None, None, None, None, None,
            [["verb", [["move fast.", "id", "the dog ran across the road"]]]],
            [[["a production <b>run</b> of only 150 cars"]]],
        ]
        provider = GoogleTranslate()
        provider._call = lambda text, target, parts: reply if "bd" in parts else [[["狗跑过马路", text]]]
        e = provider.lookup(["run"])[0]
        self.assertEqual(e.meaning, "跑步；运行；执行")
        self.assertEqual((e.pos, e.lang, e.phonetic), ("v.", "en", "/rən/"))
        self.assertEqual((e.example, e.example_zh), ("The dog ran across the road", "狗跑过马路"))

        provider._call = lambda text, target, parts: [[["qwzx", "qwzx"]], None, "en"]
        self.assertIsNone(provider.lookup(["qwzx"])[0])


if __name__ == "__main__":
    unittest.main()
