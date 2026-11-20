# Corrections (en) - правила владельца для английских текстов

Append-only, как `vendor/humanizer-ru/knowledge/corrections.md`, только для английского режима и в нашем слое: vendor не правим. Скилл читает этот файл в фазе 1 вместе с выдержками из `vendor/humanizer-en/SKILL.md`; правила отсюда сильнее дефолтов справочника. Правило с пометкой «Линтер» проверяет `jev_humanizer/owner_rules.py` как ERROR.

Формат записи:

```
## YYYY-MM-DD - <тема>

Фидбек: <что не понравилось, чьи слова>

Правило: <конкретное действие для редактора>

Линтер: <что ловится, если ловится>

Область: <тип текстов; «все» по умолчанию>
```

## Записи

## 2026-11-20 - шаблонное открытие письма

Фидбек: Санжар, 20.11.2026: «I hope this message finds you well — ненавижу эту фразу, её нужно добавить как антипаттерн в скилл».

Правило: не открывать письмо или сообщение пожеланием адресату: `I hope this message finds you well`, `I hope this email finds you well`, `I hope you are doing well`, `I hope you're well`, `Hope you're having a great week` и близкие варианты. После обращения сразу дело: ответ, решение, вопрос. Сокращение «нормы делового письма» на эту фразу не распространяется, хотя её пишут и люди.

Линтер: ERROR «шаблонное открытие письма (правило владельца): начни сразу с дела», номер паттерна 22 для `--sections`. Ловятся `I hope / I trust this (message|email|note|letter) finds you well`, `I hope you are / you're (doing) well`, `I hope you and your team are well`, `I hope all is well`, `Hope you're having a great week / day / start to the week`, `Hope your week is going well`, `I hope you had a lovely weekend`; регистр и апострофы любые. Русский аналог («Надеюсь, это письмо застанет вас в добром здравии», «Надеюсь, у вас всё хорошо», «Надеюсь, вы в порядке») ловится тем же правилом в русском режиме, номер 18: линтер humanizer-ru его не видит.

Область: письма и сообщения; фраза в бэктиках не считается, так её цитируют.
