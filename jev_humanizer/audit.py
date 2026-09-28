"""CLI аудита; JSON сохраняет все оценки, порог влияет только на показ.

python3 -m jev_humanizer.audit текст.md --json audit.json --sections
Клиент подменяется через audit_text(..., client=callable(state, questions)).
Абзацы нумеруются с 1; paragraph=null обозначает документную находку.
Цена — оценка по входным токенам; тариф выходных токенов не задан.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import http.client
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

from .patterns import (
    DOCUMENT_PATTERNS, LINT_PATTERN_NUMBERS, PARAGRAPH_PATTERNS, questions,
)

VENDOR = Path(__file__).resolve().parents[1] / "vendor" / "humanizer-ru"
PATTERNS_PATH = VENDOR / "references" / "patterns.md"
API_URL = "https://api.typesafe.ai/v1/systemone"
INPUT_USD_PER_MILLION = 0.042


@lru_cache(maxsize=1)
def vendor_lint():
    """Загружаем эталон без изменения sys.path и копирования правил."""
    spec = importlib.util.spec_from_file_location("humanizer_ru_lint", VENDOR / "scripts" / "lint.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.lint


def split_paragraphs(text):
    """Пустые, в том числе пробельные строки — границы; сохраняем номера строк."""
    paragraphs = []
    lines = []
    start = 0
    for number, line in enumerate(text.splitlines(), 1):
        if line.strip():
            if not lines:
                start = number
            lines.append(line)
        elif lines:
            paragraphs.append({"number": len(paragraphs) + 1, "start_line": start,
                               "end_line": number - 1, "text": "\n".join(lines).strip()})
            lines = []
    if lines:
        paragraphs.append({"number": len(paragraphs) + 1, "start_line": start,
                           "end_line": start + len(lines) - 1, "text": "\n".join(lines).strip()})
    return paragraphs


def load_api_key():
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if key:
        return key
    path = Path.home() / ".config" / "typesafe.env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^\s*TYPESAFE_API_KEY\s*=\s*(.*?)\s*$", line)
            if match:
                key = match[1].strip("\"'").strip()
                if key:
                    return key
    raise ValueError("Нет TYPESAFE_API_KEY в окружении или ~/.config/typesafe.env; доступен --no-jev.")


def call_jev(state, questions, *, api_key):
    """Три попытки суммарно: сеть, HTTP 408/429/5xx; прочие ошибки сразу наружу."""
    body = json.dumps({"model": "jev-latest", "state": state, "questions": questions},
                      ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(API_URL, data=body, method="POST", headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
    })
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            if status not in (408, 429) and not 500 <= status < 600:
                raise RuntimeError(f"Jev: HTTP {status}.") from None
            error = f"HTTP {status}"
        except (urllib.error.URLError, OSError, http.client.HTTPException):
            error = "сетевая ошибка"
        if attempt < 2:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Jev: {error} после трёх попыток.")


def extract_sections(numbers, path=PATTERNS_PATH):
    """Только секции ### N.; не захватываем следующие ## и полный пример."""
    wanted = set(numbers)
    lines = path.read_text(encoding="utf-8").splitlines()
    sections, current = [], None
    for line in lines:
        if re.match(r"^#{1,3} ", line):
            if current is not None:
                sections.append("\n".join(current).rstrip().removesuffix("---").rstrip())
            match = re.match(r"^### (\d+)\. ", line)
            current = [line] if match and int(match[1]) in wanted else None
        elif current is not None:
            current.append(line)
    if current is not None:
        sections.append("\n".join(current).rstrip().removesuffix("---").rstrip())
    return "\n\n".join(sections)


def lint_findings(text, paragraphs):
    result = []
    for level, line, rule, excerpt in vendor_lint()(text):
        match = re.match(r"^(\d+)\b", rule)
        number = int(match[1]) if match else LINT_PATTERN_NUMBERS.get(rule)
        paragraph = next((p["number"] for p in paragraphs
                          if p["start_line"] <= line <= p["end_line"]), None)
        result.append({"paragraph": paragraph, "pattern": number, "name": rule,
                       "source": "lint", "probability": None, "level": level,
                       "line": line, "excerpt": excerpt})
    return result


def make_jobs(text, paragraphs):
    jobs = []
    for index, paragraph in enumerate(paragraphs):
        jobs.append({
            "paragraph": paragraph["number"], "patterns": PARAGRAPH_PATTERNS,
            "state": {"paragraph": paragraph["text"], "paragraph_number": paragraph["number"],
                      "paragraph_count": len(paragraphs),
                      "previous_paragraph": paragraphs[index - 1]["text"] if index else None},
            "excerpt": paragraph["text"][:120],
        })
    opening = [line.strip() for line in text.splitlines() if line.strip()][:2]
    if len(opening) == 2:
        jobs.append({"paragraph": None, "patterns": [DOCUMENT_PATTERNS[0]],
                     "state": {"opening": opening}, "excerpt": " / ".join(opening)[:120]})
    if len(paragraphs) >= 5:
        first_sentences = [re.split(r"(?<=[.!?…])\s+", p["text"], maxsplit=1)[0]
                           for p in paragraphs]
        jobs.append({"paragraph": None, "patterns": [DOCUMENT_PATTERNS[1]],
                     "state": {"first_sentences": first_sentences},
                     "excerpt": " / ".join(first_sentences)[:120]})
    return jobs


def validate_response(response, job):
    """Не превращаем пропавший или испорченный ответ в вероятность ноль."""
    if not isinstance(response, dict) or not isinstance(response.get("answers"), dict):
        raise ValueError("Jev: отсутствует карта answers.")
    findings = []
    for pattern in job["patterns"]:
        qid = f"p{pattern['number']}"
        answer = response["answers"].get(qid)
        if not isinstance(answer, dict) or answer.get("type") != "noul":
            raise ValueError(f"Jev: отсутствует Noul-ответ {qid}.")
        probability = answer.get("noul")
        if (type(probability) not in (int, float) or not math.isfinite(probability)
                or not 0 <= probability <= 1):
            raise ValueError(f"Jev: некорректная вероятность {qid}.")
        findings.append({"paragraph": job["paragraph"], "pattern": pattern["number"],
                         "name": pattern["name"], "source": "jev", "probability": probability,
                         "level": None, "line": None, "excerpt": job["excerpt"]})
    usage = response.get("usage")
    if not isinstance(usage, dict) or any(
        type(usage.get(k)) is not int or usage[k] < 0 for k in ("input_tokens", "output_tokens")
    ):
        raise ValueError("Jev: отсутствует или некорректен учёт токенов usage.")
    return findings


def audit_text(text, *, threshold=0.5, no_jev=False, client=None):
    """Полный отчёт. Подменённый клиент должен допускать вызовы из четырёх потоков."""
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("Порог должен быть числом от 0 до 1.")
    text = text.lstrip("\ufeff")
    paragraphs = split_paragraphs(text)
    findings = lint_findings(text, paragraphs)
    requests = []
    usage = {"input_tokens": 0, "output_tokens": 0}
    jobs = make_jobs(text, paragraphs) if not no_jev else []
    if jobs:
        if client is None:
            api_key = load_api_key()

            def client(state, questions):
                return call_jev(state, questions, api_key=api_key)

        def run(job):
            response = client(job["state"], questions(job["patterns"]))
            return response, validate_response(response, job)

        with ThreadPoolExecutor(max_workers=4) as pool:
            for job, (response, scores) in zip(jobs, pool.map(run, jobs)):
                findings.extend(scores)
                for key in usage:
                    usage[key] += response["usage"][key]
                requests.append({"paragraph": job["paragraph"],
                                 "patterns": [p["number"] for p in job["patterns"]],
                                 "response": response})
    return {
        "schema_version": 1, "threshold": threshold, "jev_enabled": not no_jev,
        "paragraphs": paragraphs, "findings": findings, "requests": requests,
        "usage": usage, "cost_usd": usage["input_tokens"] * INPUT_USD_PER_MILLION / 1_000_000,
        "cost_basis": {"input_usd_per_million": INPUT_USD_PER_MILLION, "output_price_included": False},
    }


def visible_findings(report):
    return [f for f in report["findings"]
            if f["source"] == "lint" or f["probability"] >= report["threshold"]]


def _cell(value):
    # Таблицу читает модель в терминале: HTML-сущности вроде &gt; она примет за текст.
    return re.sub(r"\s+", " ", str(value)).replace("|", "\\|")


def render_markdown(report, *, sections=False):
    found = visible_findings(report)
    lines = ["| абзац № | паттерн | источник (jev/lint) | вероятность/уровень | начало абзаца или цитата линтера |",
             "| --- | --- | --- | --- | --- |"]
    for finding in found:
        label = finding["name"]
        if finding["pattern"] is not None and not re.match(r"^\d+\b", label):
            label = f"{finding['pattern']}. {label}"
        score = f"{finding['probability']:.3f}" if finding["source"] == "jev" else finding["level"]
        cells = (finding["paragraph"] or "документ", label, finding["source"], score, finding["excerpt"])
        lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    if not found:
        lines.extend(["", "Находок выше порога нет; линтер чист."])
    usage = report["usage"]
    lines.extend(["", f"Jev: входных токенов {usage['input_tokens']}, выходных {usage['output_tokens']}. "
                  f"Цена по входным токенам: ${report['cost_usd']:.8f} "
                  f"(${INPUT_USD_PER_MILLION} за миллион; тариф выхода не задан)."])
    if sections:
        extracted = extract_sections(f["pattern"] for f in found if f["pattern"] is not None)
        if extracted:
            lines.extend(["", extracted])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Аудит русского текста: humanizer-ru + Jev")
    parser.add_argument("file", help="Путь к тексту или - для stdin")
    parser.add_argument("--json", metavar="OUT", type=Path, help="Сохранить все оценки и usage")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--sections", action="store_true")
    parser.add_argument("--no-jev", action="store_true", help="Только локальный линтер")
    args = parser.parse_args(argv)
    if not math.isfinite(args.threshold) or not 0 <= args.threshold <= 1:
        parser.error("--threshold должен быть числом от 0 до 1")
    try:
        text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8-sig")
        report = audit_text(text, threshold=args.threshold, no_jev=args.no_jev)
        output = render_markdown(report, sections=args.sections)
        if args.json:
            args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                                 encoding="utf-8")
        print(output)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Ошибка аудита: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
