from app.shortcut_settings.defaults import default_entries
from app.shortcut_settings.models import ShortcutEntry, ShortcutPlanPayload


def test_default_shortcuts_cover_all_existing_prompt_guide_items() -> None:
    entries = default_entries()
    assert len(entries) == 24
    assert len({item["id"] for item in entries}) == 24
    assert {item["categoryKey"] for item in entries} == {"content", "external", "internal", "systems"}


def test_locked_shortcut_is_always_visible() -> None:
    item = ShortcutEntry(
        id="required", categoryKey="content", categoryLabel="Content",
        label="Required", locked=True, enabled=False,
    )
    assert item.enabled is True


def test_shortcut_plan_rejects_duplicate_ids() -> None:
    item = ShortcutEntry(id="same", categoryKey="content", categoryLabel="Content", label="One")
    try:
        ShortcutPlanPayload(entries=[item, item.model_copy(update={"label": "Two"})])
    except ValueError:
        return
    raise AssertionError("duplicate shortcut IDs were accepted")


def test_shortcut_plan_rejects_more_than_six_entries_in_one_group() -> None:
    entries = [
        ShortcutEntry(id=f"entry-{index}", categoryKey="content", categoryLabel="Content", label=f"Entry {index}")
        for index in range(7)
    ]
    try:
        ShortcutPlanPayload(entries=entries)
    except ValueError:
        return
    raise AssertionError("more than six entries were accepted in one group")


def test_shortcut_plan_accepts_persisted_custom_icons() -> None:
    payload = ShortcutPlanPayload(customIcons=[{"label": "Star", "value": "custom.star", "svg": "<svg viewBox='0 0 1 1'></svg>"}])
    assert payload.customIcons[0].value == "custom.star"
