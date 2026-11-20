import contextlib
import io
import re
import unittest
from unittest.mock import patch

from jev_humanizer import audit, lint_en, owner_rules, patterns, patterns_en
from jev_humanizer.patterns import questions
from tests.test_audit import fake_client

# Норма делового письма в ответ на RFQ: здесь не должно быть ни одной находки линтера.
BUSINESS_LETTER = """Dear Anna,

Thank you for the RFQ. Our team is available for rehearsals on 26 January, both event days on 27–28 January and the AV check from 9:00 – 17:00.

Unless you advise otherwise, we will base the quote on the following:
- Workshop 40 pax and Gala Dinner 80 pax, F&B with the hotel;
- the 4 performers stay in a 3★/4★ hotel, 3★ – 4★ if rooms are short;
- the stage is 5 × 3 m, the run-of-show follows the client's “final” brief.

A few points would help us finalise the numbers:

1. Is the venue confirmed?

2. Should the quote include VAT and the MC?

## Visit to InterContinental Lisbon

Happy to have a short call on Monday, or let me know if email is easier.

Best regards,
Alex Morgan
Project Lead | Example Events
"""

EN_OPENERS = [
    "I hope this message finds you well.",
    "I hope this email finds you well.",
    "Hope this note finds you well!",
    "I trust this letter finds you well.",
    "I hope this finds you well.",
    "I hope you are doing well.",
    "I hope you’re well.",
    "hope you're doing well",
    "I HOPE YOU ARE WELL.",
    "I hope you and your team are well.",
    "I hope all is well.",
    "Hope you're having a great week.",
    "I hope you are having a wonderful start to the week.",
    "Hope your week is going well.",
    "I hope you had a lovely weekend.",
]
EN_NOT_OPENERS = [
    "I hope to send the quote by Friday.",
    "We hope the venue is confirmed this week.",
    "The dancers are doing well in rehearsals.",
    "Quote the phrase `I hope this email finds you well` only in backticks.",
]
RU_OPENERS = [
    "Надеюсь, это письмо застанет вас в добром здравии.",
    "Надеюсь, письмо застанет вас в хорошем настроении.",
    "Надеюсь, у вас всё хорошо.",
    "Надеюсь, у Вас все хорошо!",
    "надеюсь, что у вас всё в порядке",
    "Надеюсь, вы в добром здравии.",
    "Надеюсь, неделя проходит хорошо.",
]
RU_NOT_OPENERS = [
    "Надеюсь, смета подойдёт.",
    "Надеюсь, это поможет закрыть вопрос с площадкой.",
    "У вас всё хорошо с площадкой?",
]


def lint(text):
    return lint_en.lint(text, audit.vendor_module())


def rules(findings, level=None):
    return [f[2] for f in findings if level is None or f[0] == level]


class LanguageTests(unittest.TestCase):
    def setUp(self):
        self.network = patch.object(audit.urllib.request, "urlopen", side_effect=AssertionError("Сеть запрещена"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def test_detect_language(self):
        self.assertEqual(audit.detect_language(BUSINESS_LETTER), "en")
        self.assertEqual(audit.detect_language("Простой текст про RFQ, AV и F&B для InterContinental."), "ru")
        code = "Запусти скрипт.\n\n```\npython3 -m jev_humanizer.audit text.md --json out.json\n```\n"
        self.assertEqual(audit.detect_language(code + "См. https://github.com/blader/humanizer"), "ru")
        self.assertEqual(audit.detect_language("Dear Anna, please greet Сардор for us."), "en")
        self.assertEqual(audit.detect_language("abcdef абв"), "ru")
        self.assertEqual(audit.detect_language("abcdefg абв"), "en")
        self.assertEqual(audit.detect_language("\n \n123"), "ru")

    def test_lang_flag_overrides_detection(self):
        report = audit.audit_text(BUSINESS_LETTER, client=fake_client)
        self.assertEqual(report["lang"], "en")
        report = audit.audit_text(BUSINESS_LETTER, client=fake_client, lang="ru")
        self.assertEqual(report["lang"], "ru")
        self.assertTrue(any(30 in r["patterns"] for r in report["requests"]))
        with self.assertRaisesRegex(ValueError, "не поддерживается"):
            audit.audit_text("Text.", lang="de", no_jev=True)
        with contextlib.redirect_stdout(io.StringIO()) as stdout, \
                patch.object(audit.sys, "stdin", io.StringIO("Это — текст.")):
            self.assertEqual(audit.main(["-", "--no-jev", "--lang", "en", "--sections"]), 0)
        self.assertIn("8 em dash", stdout.getvalue())
        self.assertIn("### 8. Dashes as the universal connector", stdout.getvalue())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            audit.main(["-", "--lang", "de"])

    def test_english_questions_cover_catalogue_and_genre_norms(self):
        patterns_all = patterns_en.PARAGRAPH_PATTERNS + patterns_en.DOCUMENT_PATTERNS
        numbers = [p["number"] for p in patterns_all]
        self.assertEqual(len(numbers), len(set(numbers)))
        # §8 проверяет линтер, §21 (фигурные кавычки) не проверяет никто.
        self.assertEqual(set(numbers), set(range(1, 27)) - {8, 21})
        headings = dict(re.findall(r"(?m)^### (\d+)\. (.+)$",
                                   (audit.VENDOR_EN / "SKILL.md").read_text(encoding="utf-8")))
        for p in patterns_all:
            self.assertEqual(p["name"], headings[str(p["number"])])
        for qid, q in questions(patterns_all).items():
            with self.subTest(question=qid):
                self.assertEqual(set(q), {"type", "instructions", "criteria"})
                text = q["instructions"] + " ".join(q["criteria"].values())
                self.assertIsNone(re.search(r"[а-яё]", text, re.I))
        for qid, q in questions(patterns_en.PARAGRAPH_PATTERNS + patterns_en.DOCUMENT_PATTERNS[1:]).items():
            with self.subTest(genre=qid):
                for norm in ("Dear", "Best regards", "numbered list of questions", "RFQ", "27–28",
                             "×", "3★/4★", "F&B", "pax", "run-of-show", "let me know"):
                    self.assertIn(norm, q["instructions"])
        self.assertIn("salutation", patterns_en.DOCUMENT_PATTERNS[0]["instructions"])

    def test_russian_questions_unchanged_by_scope_key(self):
        for q in questions(patterns.PARAGRAPH_PATTERNS + patterns.DOCUMENT_PATTERNS).values():
            self.assertEqual(set(q), {"type", "instructions", "criteria"})
        self.assertEqual([p["scope"] for p in patterns.DOCUMENT_PATTERNS], ["opening", "outline"])

    def test_english_jobs_and_sections(self):
        calls = []

        def client(state, qs):
            calls.append((state, qs))
            return fake_client(state, qs)

        report = audit.audit_text(BUSINESS_LETTER, client=client)
        paragraph_calls = [(s, q) for s, q in calls if "paragraph" in s]
        self.assertEqual(len(paragraph_calls), len(report["paragraphs"]))
        self.assertTrue(all(set(q) == set(questions(patterns_en.PARAGRAPH_PATTERNS))
                            for s, q in paragraph_calls))
        self.assertEqual(next(s for s, q in calls if "p24" in q), {"opening": ["Dear Anna,", report["paragraphs"][1]["text"]]})
        self.assertEqual(next(s for s, q in calls if "p26" in q), {"document": BUSINESS_LETTER.strip()})
        self.assertFalse(any("p30" in q or "p38" in q for s, q in calls))
        markdown = audit.render_markdown(report, sections=True)
        self.assertIn("### 1. Not X but Y", markdown)
        self.assertNotIn("### 2.", markdown)
        self.assertNotIn("## When not to act", markdown)
        sections = audit.extract_sections([22, 8, 8], audit.VENDOR_EN / "SKILL.md")
        self.assertEqual(sections.count("### 8."), 1)
        self.assertLess(sections.index("### 8."), sections.index("### 22."))
        self.assertNotIn("### 9.", sections)
        self.assertNotIn("## E.", sections)


class EnglishLintTests(unittest.TestCase):
    def test_business_letter_is_clean(self):
        self.assertEqual(lint(BUSINESS_LETTER), [])
        report = audit.audit_text(BUSINESS_LETTER, no_jev=True)
        self.assertEqual(report["findings"], [])

    def test_dashes(self):
        self.assertEqual(rules(lint("The policy — announced late — applies.")), ["8 em dash", "8 em dash"])
        self.assertEqual(rules(lint("The policy – announced late – applies.")), ["8 spaced en dash"] * 2)
        self.assertEqual(rules(lint("The changes -- long overdue -- apply.")), ["8 double hyphen as dash"] * 2)
        self.assertEqual(rules(lint("The changes--long overdue--apply.")), ["8 double hyphen as dash"] * 2)
        for ok in ("27–28 January", "9:00 – 17:00", "3★–4★", "3★ – 4★ hotel", "Tashkent–Samarkand transfer",
                   "– a bullet with an en dash", "Run `audit --json` here", "| --- | --- |", "pass --json here"):
            with self.subTest(ok=ok):
                self.assertEqual(lint(ok), [])

    def test_symbols_and_formatting(self):
        self.assertEqual(rules(lint("Launch today 🚀")), ["20 emoji"])
        self.assertEqual(rules(lint("Done ✅")), ["20 emoji"])
        self.assertEqual(rules(lint("Tashkent → Samarkand")), ["20 arrow"])
        for ok in ("A 3★/4★ hotel", "4☆ rooms", "6 × 12 m", "He said “yes” and ‘no’ and it’s fine."):
            with self.subTest(ok=ok):
                self.assertEqual(lint(ok), [])
        self.assertEqual(rules(lint("## Strategic Negotiations And Global Partnerships")),
                         ["20 Title Case heading"])
        for ok in ("## Strategic negotiations and partnerships", "## Visit to InterContinental Lisbon",
                   "## RFQ and AV", "## Room layouts"):
            with self.subTest(ok=ok):
                self.assertEqual(lint(ok), [])
        self.assertEqual(rules(lint("- **Performance:** improved")), ["19 bold label"])
        self.assertEqual(rules(lint("1. **Security**: stronger")), ["19 bold label"])
        bold = " ".join(f"**w{i}** word word word word word word word word word" for i in range(25))
        self.assertEqual(rules(lint(bold)), ["19 bold overuse"])
        self.assertEqual(rules(lint("Intro.\n\n---\n\nMore.")), ["20 horizontal rule"])

    def test_chatbot_residue_and_artifacts(self):
        for bad in ("I hope this helps!", "Certainly! Here it is.", "Of course! We can.", "Great question.",
                    "You’re absolutely right.", "Would you like me to expand?", "Should I continue?",
                    "Done. Want me to add more?"):
            with self.subTest(bad=bad):
                self.assertEqual(rules(lint(bad)), ["22 chatbot residue"])
        for ok in ("Certainly, the hotel can do it.", "Let me know if Monday works.",
                   "Here is a summary of the quote.", "Our staff want me to confirm the date."):
            with self.subTest(ok=ok):
                self.assertEqual(lint(ok), [])
        found = lint("Source turn0search3 and ```\nturn0search1\n```\nzero​width")
        self.assertEqual([f[0] for f in found if f[2].startswith("A ")], ["ERROR"])
        self.assertTrue(any(f[2].startswith("B ") for f in found))
        report = audit.audit_text("Source turn0search3 here.", no_jev=True, lang="en")
        self.assertTrue(any(f["name"].startswith("A ") and f["pattern"] is None for f in report["findings"]))

    def test_frontmatter_and_code_are_skipped(self):
        text = "---\ntitle: X — Y\n---\n\nPlain text.\n\n```\na — b 🚀\n```\n\nSee https://x.io/a--b"
        self.assertEqual(lint(text), [])


class OwnerRuleTests(unittest.TestCase):
    """Санжар, 20.11.2026: шаблонное открытие письма — ERROR в обоих языках."""

    def check(self, lang, bad, ok, number):
        base = audit.vendor_module()
        for text in bad:
            with self.subTest(lang=lang, bad=text):
                found = owner_rules.lint(text, lang, base)
                self.assertEqual([f[0] for f in found], ["ERROR"])
                self.assertIn("начни сразу с дела", found[0][2])
                report = audit.audit_text(text, no_jev=True, lang=lang)
                self.assertTrue(any(f["level"] == "ERROR" and f["pattern"] == number
                                    and "шаблонное открытие" in f["name"] for f in report["findings"]))
        for text in ok:
            with self.subTest(lang=lang, ok=text):
                self.assertEqual(owner_rules.lint(text, lang, base), [])

    def test_english_stock_openers(self):
        self.check("en", EN_OPENERS, EN_NOT_OPENERS, 22)
        report = audit.audit_text("Dear Anna,\n\nI hope this message finds you well.", no_jev=True)
        self.assertEqual(report["lang"], "en")
        self.assertEqual([(f["paragraph"], f["line"]) for f in report["findings"]], [(2, 3)])

    def test_russian_stock_openers(self):
        self.check("ru", RU_OPENERS, RU_NOT_OPENERS, 18)
        # Линтер humanizer-ru их не ловит, поэтому правило живёт в нашем слое.
        self.assertEqual([f for t in RU_OPENERS for f in audit.vendor_lint()(t) if f[0] == "ERROR"], [])

    def test_owner_rules_file_names_the_rule(self):
        notes = (audit.VENDOR.parents[1] / "knowledge" / "corrections-en.md").read_text(encoding="utf-8")
        self.assertIn("I hope this message finds you well", notes)
        self.assertIn("Санжар, 20.11.2026", notes)


if __name__ == "__main__":
    unittest.main()
