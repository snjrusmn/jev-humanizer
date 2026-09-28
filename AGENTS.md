# jev-humanizer

Антислоп скилл для AI-агентов. Справочник и линтер пока знают только русский. Линтер humanizer-ru и классификатор Jev (TypeSafe AI) проверяют текст по абзацам, модель-хозяин правит места из таблицы находок. Для людей проект описывает README.md.

## Правила для работы в репозитории
1. `vendor/humanizer-ru` не правим. Это копия smixs/humanizer-ru v1.7 (MIT).
2. Ключ Jev в репозиторий не кладём. Он живёт в `TYPESAFE_API_KEY` или `~/.config/typesafe.env`.
3. Любая правка `jev_humanizer/` проходит `python3 -m unittest discover -s tests`.
4. После правки `skill/SKILL.md` сравниваем тексты вслепую со старой версией и только потом пишем об улучшении в README.
5. Тексты для людей (README, описания) пишем по самому скиллу и прогоняем через `python3 -m jev_humanizer.audit`.
