# jev-humanizer

Антислоп скилл для AI-агентов. Русский текст проверяют линтер humanizer-ru и классификатор Jev (TypeSafe AI), английский - свой линтер `jev_humanizer/lint_en.py` и Jev по паттернам blader/humanizer. Проверка идёт по абзацам, модель-хозяин правит места из таблицы находок. Для людей проект описывает README.md.

## Правила для работы в репозитории
1. `vendor/` не правим. `vendor/humanizer-ru` - копия smixs/humanizer-ru v1.7, `vendor/humanizer-en` - blader/humanizer, коммит a32f244 (обе MIT). Правила владельца поверх них живут в `knowledge/` и `jev_humanizer/owner_rules.py`.
2. Ключ Jev в репозиторий не кладём. Он живёт в `TYPESAFE_API_KEY` или `~/.config/typesafe.env`.
3. Любая правка `jev_humanizer/` проходит `python3 -m unittest discover -s tests`.
4. После правки `skill/SKILL.md` сравниваем тексты вслепую со старой версией и только потом пишем об улучшении в README.
5. Тексты для людей (README, описания) пишем по самому скиллу и прогоняем через `python3 -m jev_humanizer.audit`.
