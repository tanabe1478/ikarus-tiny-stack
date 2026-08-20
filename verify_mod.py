from __future__ import annotations

import json
import zipfile
from pathlib import Path

from build_mod import (
    BUILD_DIR,
    DIST_DIR,
    MOD_ID,
    configured_stack,
    load_config,
)


PROJECT_DIR = Path(__file__).resolve().parent
BASE_ITEMABLE = (
    PROJECT_DIR.parent
    / "tmp"
    / "icarus_mod_tooling"
    / "current_game_data"
    / "Traits"
    / "D_Itemable.json"
)
MODDED_ITEMABLE = BUILD_DIR / "staging" / "D_Itemable.json"
EXMODZ = DIST_DIR / f"{MOD_ID}.EXMODZ"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as source:
        return json.load(source)


def verify_itemable() -> int:
    base = load_json(BASE_ITEMABLE)
    modded = load_json(MODDED_ITEMABLE)
    config = load_config()

    assert base["RowStruct"] == modded["RowStruct"]
    assert base["Defaults"] == modded["Defaults"]
    assert len(base["Rows"]) == len(modded["Rows"])

    changed = 0
    for original, updated in zip(base["Rows"], modded["Rows"], strict=True):
        assert original["Name"] == updated["Name"]
        original_other = {k: v for k, v in original.items() if k != "MaxStack"}
        updated_other = {k: v for k, v in updated.items() if k != "MaxStack"}
        assert original_other == updated_other

        old_stack = original.get("MaxStack")
        new_stack = updated.get("MaxStack")
        if isinstance(old_stack, int) and old_stack > 1:
            expected, _ = configured_stack(original["Name"], old_stack, config)
            assert new_stack == expected
            if expected != old_stack:
                changed += 1
        else:
            assert new_stack == old_stack

    return changed


def verify_exmodz(expected_changes: int) -> None:
    with zipfile.ZipFile(EXMODZ) as archive:
        names = set(archive.namelist())
        assert names == {
            f"Extracted Mods/{MOD_ID}.EXMOD",
            f"{MOD_ID}/README.md",
            f"{MOD_ID}/Readme ({MOD_ID}_P.pak).txt",
        }
        exmod = json.loads(
            archive.read(f"Extracted Mods/{MOD_ID}.EXMOD").decode("utf-8")
        )

    assert len(exmod["Rows"]) == 1
    assert exmod["Rows"][0]["CurrentFile"] == "Traits-D_Itemable.json"
    changes = exmod["Rows"][0]["File_Items"]
    assert len(changes) == expected_changes
    assert all(set(change) == {"Name", "MaxStack"} for change in changes)


def main() -> None:
    changed = verify_itemable()
    verify_exmodz(changed)
    verify_configuration_modes()
    print(f"Verified {changed} MaxStack-only changes")
    print("Verified one EXMOD table: Traits-D_Itemable.json")
    print("Verified no inventory, chest, bag, or capacity tables")


def verify_configuration_modes() -> None:
    multiplier = {
        "global": {"mode": "multiplier", "value": 3, "cap": 9999},
        "individual": {"Item_Wood": 777},
    }
    assert configured_stack("Item_Stone", 100, multiplier) == (300, "global")
    assert configured_stack("Item_Wood", 100, multiplier) == (777, "individual")

    fixed = {
        "global": {"mode": "fixed", "value": 250, "cap": 9999},
        "individual": {"Item_Fiber": 1200},
    }
    assert configured_stack("Item_Stone", 100, fixed) == (250, "global")
    assert configured_stack("Item_Fiber", 200, fixed) == (1200, "individual")


if __name__ == "__main__":
    main()
