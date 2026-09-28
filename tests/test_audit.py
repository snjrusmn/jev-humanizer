import contextlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error

from jev_humanizer import audit
from jev_humanizer.patterns import (
    DOCUMENT_PATTERNS, LINT_PATTERN_NUMBERS, PARAGRAPH_PATTERNS, questions,
)


def fake_client(state, questions):
    return {
        "model": "jev-test",
        "answers": {qid: {"type": "noul", "noul": {"p1": 0.5, "p2": 0.49}.get(qid, 0.1)}
                    for qid in questions},
        "usage": {"input_tokens": 550, "output_tokens": 20},
    }


class AuditTests(unittest.TestCase):
    def setUp(self):
        # Любой случайный выход в сеть ломает тест.
        self.network = patch.object(audit.urllib.request, "urlopen", side_effect=AssertionError("Сеть запрещена"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def test_paragraphs_and_line_numbers(self):
        text = "\r\n  Первый\r\nпродолжение.\r\n \t\r\n\r\nВторой.\r\n\r\nТретий."
        self.assertEqual(audit.split_paragraphs(text), [
            {"number": 1, "start_line": 2, "end_line": 3, "text": "Первый\nпродолжение."},
            {"number": 2, "start_line": 6, "end_line": 6, "text": "Второй."},
            {"number": 3, "start_line": 8, "end_line": 8, "text": "Третий."},
        ])
        self.assertEqual(audit.split_paragraphs(" \n\t\n"), [])

    def test_questions_complete_and_cover_catalogue(self):
        patterns = PARAGRAPH_PATTERNS + DOCUMENT_PATTERNS
        numbers = [p["number"] for p in patterns]
        self.assertEqual(len(numbers), len(set(numbers)))
        self.assertEqual(set(numbers), set(range(1, 39)) - {23})
        for q in questions(patterns).values():
            self.assertEqual(q["type"], "noul")
            self.assertTrue(q["instructions"].strip())
            self.assertEqual(set(q["criteria"]), {"true", "false"})
            self.assertTrue(all(q["criteria"].values()))

    def test_sections_exact_boundaries_and_order(self):
        sections = audit.extract_sections([38, 13, 13, 23])
        self.assertIn("### 13.", sections)
        self.assertIn("### 23.", sections)
        self.assertIn("### 38.", sections)
        self.assertNotIn("### 14.", sections)
        self.assertNotIn("## AI-СЛОВАРЬ", sections)
        self.assertNotIn("## Артефакты", sections)
        self.assertNotIn("## ПОЛНЫЙ ПРИМЕР", sections)
        self.assertEqual(sections.count("### 13."), 1)
        self.assertLess(sections.index("### 13."), sections.index("### 38."))
        self.assertEqual(audit.extract_sections([]), "")
        self.assertNotIn("## ПРОЗАИЧЕСКИЙ ФЛОУ", audit.extract_sections([32]))

    def test_merge_threshold_and_usage(self):
        report = audit.audit_text("Простой текст.\n\nЭто — пример.", client=fake_client)
        lint = [f for f in report["findings"] if f["source"] == "lint"]
        self.assertTrue(any(f["pattern"] == 23 and f["paragraph"] == 2 for f in lint))
        scores = [f for f in report["findings"] if f["source"] == "jev"]
        self.assertEqual(len(scores), 2 * len(PARAGRAPH_PATTERNS) + 1)
        shown = audit.visible_findings(report)
        self.assertTrue(any(f["probability"] == 0.5 for f in shown))
        self.assertFalse(any(f["probability"] == 0.49 for f in shown))
        self.assertTrue(any(f["probability"] == 0.49 for f in scores))
        self.assertEqual(report["usage"], {"input_tokens": 1650, "output_tokens": 60})
        self.assertAlmostEqual(report["cost_usd"], 1650 * 0.042 / 1_000_000)
        self.assertTrue(all(r["response"]["model"] == "jev-test" for r in report["requests"]))
        markdown = audit.render_markdown(report, sections=True)
        self.assertIn("### 1.", markdown)
        self.assertIn("### 23.", markdown)
        self.assertNotIn("### 2.", markdown)

    def test_document_states_and_previous_context(self):
        calls = []

        def client(state, qs):
            calls.append((state, qs))
            return fake_client(state, qs)

        text = "# Заголовок\n\nТезис. Детали.\n\nПричина! Ещё.\n\nСледствие? Да.\n\nВывод."
        audit.audit_text(text, client=client)
        self.assertEqual(len(calls), 7)
        paragraph_calls = [s for s, q in calls if "p1" in q]
        self.assertEqual(len(paragraph_calls), 5)
        self.assertTrue(all(set(q) == set(questions(PARAGRAPH_PATTERNS))
                            for s, q in calls if "p1" in q))
        current = next(s for s in paragraph_calls if s["paragraph_number"] == 3)
        self.assertEqual(current["paragraph"], "Причина! Ещё.")
        self.assertEqual(current["previous_paragraph"], "Тезис. Детали.")
        self.assertEqual(next(s for s, q in calls if "p30" in q),
                         {"opening": ["# Заголовок", "Тезис. Детали."]})
        self.assertEqual(next(s for s, q in calls if "p38" in q),
                         {"first_sentences": ["# Заголовок", "Тезис.", "Причина!", "Следствие?", "Вывод."]})

    def test_short_document_skips_outline(self):
        report = audit.audit_text("Один.\n\nДва.", client=fake_client)
        self.assertFalse(any(38 in r["patterns"] for r in report["requests"]))

    def test_parallel_requests_limited_to_four(self):
        barrier = threading.Barrier(4, timeout=5)
        lock = threading.Lock()
        count = active = peak = 0

        def client(state, qs):
            nonlocal count, active, peak
            with lock:
                count += 1
                ordinal = count
                active += 1
                peak = max(peak, active)
            if ordinal <= 4:
                barrier.wait()
            with lock:
                active -= 1
            return fake_client(state, qs)

        report = audit.audit_text("\n\n".join(f"Абзац {n}." for n in range(8)), client=client)
        self.assertEqual(peak, 4)
        self.assertEqual(len(report["requests"]), 10)
        self.assertEqual([r["paragraph"] for r in report["requests"][:8]], list(range(1, 9)))

    def test_lint_warning_mapping_and_global_findings(self):
        report = audit.audit_text("Важно отметить, что по сути это работает. turn0search3", no_jev=True)
        self.assertTrue({11, 25}.issubset({f["pattern"] for f in report["findings"]}))
        self.assertTrue(any(f["name"].startswith("A ") and f["pattern"] is None for f in report["findings"]))
        sections = audit.render_markdown(report, sections=True)
        self.assertIn("### 11.", sections)
        self.assertIn("### 25.", sections)
        text = "\n\n".join(f"Абзац номер {i} содержит ровно столько слов для теста." for i in range(5))
        report = audit.audit_text(text, no_jev=True)
        self.assertTrue(any(f["pattern"] == 38 and f["paragraph"] is None for f in report["findings"]))
        self.assertTrue(set(audit.vendor_lint().__globals__["WARN_PHRASES"]).issubset(LINT_PATTERN_NUMBERS))

    def test_no_jev_and_empty_input_need_no_key(self):
        with patch.object(audit, "load_api_key", side_effect=AssertionError("Ключ не нужен")):
            report = audit.audit_text("Это — текст.", no_jev=True)
            self.assertEqual(report["usage"]["input_tokens"], 0)
            self.assertEqual(report["requests"], [])
            self.assertFalse(report["jev_enabled"])
            report = audit.audit_text("\n \n")
            self.assertEqual(report["requests"], [])

    def test_invalid_responses_are_not_silently_accepted(self):
        for value in (None, "0.8", True, -0.1, 1.1, float("nan")):
            with self.subTest(value=value):
                def client(state, qs):
                    result = fake_client(state, qs)
                    result["answers"]["p1"]["noul"] = value
                    return result
                with self.assertRaisesRegex(ValueError, "вероятность p1"):
                    audit.audit_text("Текст.", client=client)
        for field in ("answers", "usage"):
            with self.subTest(field=field):
                def client(state, qs):
                    result = fake_client(state, qs)
                    del result[field]
                    return result
                with self.assertRaises(ValueError):
                    audit.audit_text("Текст.", client=client)

    def test_cli_json_contains_scores_below_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.json"
            stdout = io.StringIO()
            with patch.object(audit, "load_api_key", return_value="test-key"), \
                    patch.object(audit, "call_jev", side_effect=lambda s, q, **kw: fake_client(s, q)), \
                    patch.object(audit.sys, "stdin", io.StringIO("Текст.")), \
                    contextlib.redirect_stdout(stdout):
                code = audit.main(["-", "--json", str(output), "--threshold", "0.5", "--sections"])
            self.assertEqual(code, 0)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(any(f["probability"] == 0.49 for f in report["findings"]))
            self.assertIn("### 1.", stdout.getvalue())
            self.assertNotIn("### 2.", stdout.getvalue())

    def test_cli_file_no_jev_and_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.md"
            path.write_text("\ufeffЭто — текст.", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(audit.main([str(path), "--no-jev"]), 0)
            self.assertIn("23 длинное тире", stdout.getvalue())
            self.assertNotIn("нулевой ширины", stdout.getvalue())

    def test_threshold_validation_and_bounds(self):
        for threshold in (-0.1, 1.1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                audit.audit_text("Текст", threshold=threshold, client=fake_client)
        report = audit.audit_text("Текст", threshold=0, client=fake_client)
        self.assertEqual(len(audit.visible_findings(report)), len(PARAGRAPH_PATTERNS))
        report = audit.audit_text("Текст — пример", threshold=1, client=fake_client)
        self.assertTrue(all(f["source"] == "lint" for f in audit.visible_findings(report)))

    def test_markdown_escapes_table_content(self):
        report = audit.audit_text("Текст | `слово` <b>.", client=fake_client)
        markdown = audit.render_markdown(report)
        # Только | экранируется для таблицы; текст остаётся буквальным, без HTML-сущностей.
        self.assertIn("Текст \\| `слово` <b>.", markdown)
        self.assertNotIn("&gt;", markdown)

    def test_http_contract_and_network_retry(self):
        expected = fake_client({}, {"p1": {}})
        response = io.BytesIO(json.dumps(expected).encode())
        with patch.object(audit.urllib.request, "urlopen", side_effect=[
            urllib.error.URLError("offline"), TimeoutError(), response,
        ]) as transport, patch.object(audit.time, "sleep") as sleep:
            result = audit.call_jev({"paragraph": "Текст"}, {"p1": {"type": "noul"}}, api_key="dummy")
        self.assertEqual(result, expected)
        self.assertEqual(transport.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        request = transport.call_args.args[0]
        self.assertEqual(request.full_url, audit.API_URL)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer dummy")
        self.assertEqual(json.loads(request.data), {
            "model": "jev-latest", "state": {"paragraph": "Текст"}, "questions": {"p1": {"type": "noul"}},
        })

    def test_retry_exhaustion_and_http_errors(self):
        for status, attempts in ((401, 1), (400, 1), (408, 3), (429, 3), (503, 3)):
            with self.subTest(status=status), \
                    patch.object(audit.urllib.request, "urlopen", side_effect=[
                        urllib.error.HTTPError(audit.API_URL, status, "test", {}, None)
                        for _ in range(attempts)
                    ]) as transport, patch.object(audit.time, "sleep"):
                with self.assertRaisesRegex(RuntimeError, f"HTTP {status}"):
                    audit.call_jev({}, {}, api_key="dummy")
                self.assertEqual(transport.call_count, attempts)

    def test_api_key_environment_and_file(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(audit.Path, "home", return_value=Path(tmp)):
            config = Path(tmp) / ".config"
            config.mkdir()
            (config / "typesafe.env").write_text('IGNORED=value\nTYPESAFE_API_KEY="file-key"\n', encoding="utf-8")
            with patch.dict(audit.os.environ, {"TYPESAFE_API_KEY": "env-key"}):
                self.assertEqual(audit.load_api_key(), "env-key")
            with patch.dict(audit.os.environ, {"TYPESAFE_API_KEY": ""}):
                self.assertEqual(audit.load_api_key(), "file-key")
                (config / "typesafe.env").unlink()
                with self.assertRaisesRegex(ValueError, "Нет TYPESAFE_API_KEY"):
                    audit.load_api_key()

    def test_all_editorial_evals_with_fake_jev(self):
        cases = json.loads((audit.VENDOR / "evals" / "evals.json").read_text(encoding="utf-8"))["evals"]
        cases = [case for case in cases if case["id"] not in (16, 19)]
        self.assertEqual(len(cases), 17)
        for case in cases:
            with self.subTest(case=case["id"]):
                report = audit.audit_text(case["prompt"], client=fake_client)
                self.assertEqual(sum(r["paragraph"] is not None for r in report["requests"]),
                                 len(report["paragraphs"]))
                self.assertIn("Jev: входных токенов", audit.render_markdown(report, sections=True))
                json.dumps(report, ensure_ascii=False, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
