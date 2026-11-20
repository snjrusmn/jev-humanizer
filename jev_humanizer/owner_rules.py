"""Правила владельца поверх vendor: они сильнее дефолтов справочников.

Источник и формулировки — knowledge/corrections-en.md. Цитаты в бэктиках
и код не проверяются: так фразу обсуждают, а не пишут.
"""
import re

# Санжар, 20.11.2026: «I hope this message finds you well — ненавижу эту фразу».
# Номер — ближайший паттерн справочника для --sections: §22 en, №18 ru.
STOCK_OPENERS = {
    "en": ("22 шаблонное открытие письма (правило владельца): начни сразу с дела", re.compile(
        r"\b(?:I\s+)?(?:hope|trust)\s+(?:this|my)(?:\s+\w+)?\s+finds\s+you\s+(?:well|in\s+good\s+health)|"
        r"\b(?:I\s+)?hope\s+(?:you|you\s+and\s+(?:your\s+)?\w+)\s*(?:are|'re)\s+(?:all\s+)?(?:doing\s+)?"
        r"(?:well|good|great|fine|ok|okay)\b|"
        r"\b(?:I\s+)?hope\s+(?:all\s+is|everything\s+is|all's)\s+well|"
        r"\b(?:I\s+)?hope\s+you\s*(?:are|'re)\s+having\s+an?\s+(?:\w+\s+){0,2}"
        r"(?:week|day|weekend|start|morning|afternoon|time)|"
        r"\b(?:I\s+)?hope\s+your\s+(?:week|day|weekend)\s+(?:is|has\s+been)\s+going\s+well|"
        r"\b(?:I\s+)?hope\s+you\s+(?:had|have\s+had)\s+an?\s+(?:\w+\s+)?(?:weekend|week|holiday|break)",
        re.I)),
    "ru": ("18 шаблонное открытие письма (правило владельца): начни сразу с дела", re.compile(
        r"надеюсь,?\s+(?:что\s+)?(?:это|моё|мое)?\s*(?:письмо|сообщение)\s+застанет\s+вас|"
        r"надеюсь,?\s+(?:что\s+)?у\s+(?:вас|тебя)\s+вс[её]\s+(?:хорошо|отлично|в\s+порядке|благополучно)|"
        r"надеюсь,?\s+(?:что\s+)?(?:вы|ты)\s+(?:в\s+порядке|в\s+добром\s+здравии|хорошо\s+себя\s+чувствуе)|"
        r"надеюсь,?\s+(?:что\s+)?(?:у\s+(?:вас|тебя)\s+)?(?:неделя|день)\s+(?:проходит|начинается)\s+хорошо",
        re.I)),
}


def lint(text, lang, base):
    """ERROR на каждое шаблонное открытие; base — модуль линтера humanizer-ru."""
    rule, pattern = STOCK_OPENERS[lang]
    clean = base.CODE_STRIP.sub(lambda m: "\n" * m.group(0).count("\n"), text.lstrip("﻿"))
    findings = []
    for number, line in enumerate(base.strip_frontmatter(clean.splitlines()), 1):
        for m in pattern.finditer(line.replace("’", "'")):
            findings.append(("ERROR", number, rule, line[max(0, m.start() - 25):m.end() + 25].strip()))
    return findings
