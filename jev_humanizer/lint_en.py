"""Лёгкий английский линтер: только то, что измеряется без смысла.

lint(text, base) отдаёт те же кортежи (уровень, строка, правило, цитата),
что линтер humanizer-ru; base — его модуль. Из него берём артефакты
класса A и B, вырезание кода, URL и frontmatter, чтобы не дублировать.
Номер в начале правила — паттерн из vendor/humanizer-en/SKILL.md.

Нормы делового письма не ловим: короткое тире в диапазонах и маршрутах
(27–28, 9:00 – 17:00, Tashkent–Samarkand), × в размерах, ★ и ☆ у отелей,
фигурные кавычки (§21 слаб в одиночку, почтовики ставят их сами).
"""
import re

# §8: длинное тире и двойной дефис как тире — всегда; короткое — только с пробелом
# рядом и не между цифрами, иначе это диапазон или маршрут.
DASHES = [
    ("8 em dash", re.compile(r"—")),
    ("8 double hyphen as dash", re.compile(r"\s--\s|(?<=\w)--(?=\w)")),
]
EN_DASH = re.compile(r"(?<=(\S))(\s*)–(\s*)(?=(\S))")
RANGE_ENDS = re.compile(r"[\d★☆]")
# ★ (U+2605) и ☆ (U+2606) вырезаны из диапазона: это звёзды отеля, не эмодзи.
EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-☄☇-➿]")
ARROW = re.compile(r"[←→↔⇐⇒⇔]")
HEADING = re.compile(r"^\s*#{1,6}\s+(.+)$")
MINOR_WORDS = {"a", "an", "the", "and", "but", "or", "nor", "for", "so", "yet", "as", "at",
               "by", "in", "of", "on", "to", "up", "via", "with", "from", "into", "over", "per", "vs"}
BOLD_LABEL = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+\*\*[^*\n]+?(?::\*\*|\*\*\s*:)")
# §22 без «let me know» и «here is»: оригинал сам называет их нормой письма.
CHATBOT = re.compile(
    r"\b(?:I hope this helps|Great question|You're absolutely right|Would you like me to|"
    r"Should I continue\?)|(?:^|[.!?]\s+)(?:Certainly|Of course)!|(?:^|[.!?]\s+)Want me to\b",
    re.I)


def _excerpt(line, match):
    return line[max(0, match.start() - 25):match.end() + 25].strip()


def is_title_case(heading):
    """Хотя бы два слова с заглавной и ни одного строчного; бренды вроде InterContinental и iPhone не в счёт."""
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z']*", heading)[1:] if w.lower() not in MINOR_WORDS]
    capital = sum(bool(re.fullmatch(r"[A-Z][a-z']+", w)) for w in words)
    return capital >= 2 and not any(w.islower() for w in words)


def lint(text, base):
    text = text.lstrip("﻿")
    findings = [f for f in base.lint(text) if f[2][:2] in ("A ", "B ")]
    clean = base.STRIP.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    lines = base.strip_frontmatter(clean.splitlines())
    for number, line in enumerate(lines, 1):
        if base.HR_LINE.match(line):
            findings.append(("WARN", number, "20 horizontal rule", line.strip()[:40]))
            continue
        heading = HEADING.match(line)
        if heading and is_title_case(heading[1]):
            findings.append(("WARN", number, "20 Title Case heading", line.strip()[:70]))
        for rule, rx in DASHES:
            findings.extend(("ERROR", number, rule, _excerpt(line, m)) for m in rx.finditer(line))
        for m in EN_DASH.finditer(line):
            if (m[2] or m[3]) and not (RANGE_ENDS.match(m[1]) and m[4].isdigit()):
                findings.append(("ERROR", number, "8 spaced en dash", _excerpt(line, m)))
        if EMOJI.search(line):
            findings.append(("WARN", number, "20 emoji", line.strip()[:70]))
        if ARROW.search(line):
            findings.append(("WARN", number, "20 arrow", line.strip()[:70]))
        if BOLD_LABEL.match(line):
            findings.append(("WARN", number, "19 bold label", line.strip()[:70]))
        for m in CHATBOT.finditer(line.replace("’", "'")):
            findings.append(("WARN", number, "22 chatbot residue", _excerpt(line, m)))
    words = len(" ".join(lines).split())
    bold = len(base.BOLD_SPAN.findall(clean))
    if words >= 200 and bold > words / 200 + 1:
        findings.append(("WARN", 0, "19 bold overuse",
                         f"{bold} bold spans in {words} words (about {max(1, words // 200)} is normal)"))
    return findings
