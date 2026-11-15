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
        None if w == "zzzz" else Entry(word="receive" if w == "recieve" else w, meaning="释义:" + w, lang="en", source="fake")
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

    def test_requests_from_other_sites_are_refused(self):
        r = self.c.post("/vocab/api/words", json={"text": "apple"}, headers={"Origin": "https://example.com"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.c.get("/vocab/api/words", headers={"Host": "evil.example"}).status_code, 403)
        r = self.c.post("/vocab/api/words", data="text=apple", content_type="application/x-www-form-urlencoded")
        self.assertEqual(r.status_code, 415)


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
