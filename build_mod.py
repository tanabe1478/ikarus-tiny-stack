from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any


MOD_ID = "Tiny_Stack"
MOD_NAME = "Tiny Stack"
MOD_VERSION = "1.3.0"

DEFAULT_GAME_DIR = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Icarus")
DATA_PAK = Path(
    os.environ.get(
        "ICARUS_DATA_PAK",
        DEFAULT_GAME_DIR / "Icarus" / "Content" / "Data" / "data.pak",
    )
)

PROJECT_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = PROJECT_DIR.parent
DEFAULT_UNREALPAK = (
    WORKSPACE_DIR / "tmp" / "icarus_mod_tooling" / "UnrealPak" / "UnrealPak"
    / "Engine" / "Binaries" / "Win64" / "UnrealPak.exe"
)
UNREALPAK = Path(os.environ.get("UNREALPAK_PATH", DEFAULT_UNREALPAK))
REPAK = Path(os.environ["REPAK_PATH"]) if os.environ.get("REPAK_PATH") else None
BUILD_DIR = PROJECT_DIR / "build"
DIST_DIR = PROJECT_DIR / "dist"
CONFIG_PATH = PROJECT_DIR / "stack-config.json"


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )


def use_repak() -> bool:
    return REPAK is not None and REPAK.is_file()


def repak_mount_point(pak_path: Path) -> str:
    assert REPAK is not None
    info = run([str(REPAK), "info", str(pak_path)]).stdout
    for line in info.splitlines():
        if line.startswith("mount point: "):
            return line.removeprefix("mount point: ").strip()
    raise RuntimeError(f"repak did not report a mount point for {pak_path}")


def load_current_itemable(extract_dir: Path) -> tuple[dict, Path]:
    if use_repak():
        assert REPAK is not None
        mount_point = repak_mount_point(DATA_PAK)
        run(
            [
                str(REPAK),
                "unpack",
                "--quiet",
                "--strip-prefix",
                mount_point,
                "--include",
                "Traits/D_Itemable.json",
                "--output",
                str(extract_dir),
                str(DATA_PAK),
            ]
        )
    else:
        run([str(UNREALPAK), str(DATA_PAK), "-Extract", str(extract_dir)])
    itemable_path = extract_dir / "Traits" / "D_Itemable.json"
    with itemable_path.open("r", encoding="utf-8-sig") as source:
        return json.load(source), itemable_path


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8-sig") as source:
        config = json.load(source)

    global_rule = config.get("global")
    if not isinstance(global_rule, dict):
        raise ValueError('stack-config.json: "global" must be an object')

    mode = global_rule.get("mode")
    if mode not in {"multiplier", "fixed"}:
        raise ValueError(
            'stack-config.json: "global.mode" must be "multiplier" or "fixed"'
        )

    value = global_rule.get("value")
    if not isinstance(value, int) or value < 1:
        raise ValueError('stack-config.json: "global.value" must be an integer >= 1')

    cap = global_rule.get("cap")
    if not isinstance(cap, int) or not 1 <= cap <= 9999:
        raise ValueError(
            'stack-config.json: "global.cap" must be an integer from 1 to 9999'
        )

    individual = config.get("individual")
    if not isinstance(individual, dict):
        raise ValueError('stack-config.json: "individual" must be an object')
    for item_name, stack_size in individual.items():
        if not isinstance(item_name, str) or not item_name:
            raise ValueError("stack-config.json: individual item names must be strings")
        if not isinstance(stack_size, int) or not 1 <= stack_size <= cap:
            raise ValueError(
                f"stack-config.json: individual.{item_name} must be an integer "
                f"from 1 to {cap}"
            )

    return config


def configured_stack(
    item_name: str, original: int, config: dict[str, Any]
) -> tuple[int, str]:
    global_rule = config["global"]
    if global_rule["mode"] == "multiplier":
        updated = original * global_rule["value"]
    else:
        updated = global_rule["value"]

    updated = min(updated, global_rule["cap"])
    source = "global"
    if item_name in config["individual"]:
        updated = config["individual"][item_name]
        source = "individual"

    return updated, source


def apply_stack_config(
    itemable: dict, config: dict[str, Any]
) -> tuple[list[dict[str, int | str]], list[dict[str, int | str]]]:
    changes: list[dict[str, int | str]] = []
    catalog: list[dict[str, int | str]] = []
    rows_by_name = {row["Name"]: row for row in itemable["Rows"]}

    unknown = sorted(set(config["individual"]) - set(rows_by_name))
    if unknown:
        raise ValueError(
            "stack-config.json contains unknown item IDs: " + ", ".join(unknown)
        )

    non_stackable = sorted(
        name
        for name in config["individual"]
        if not isinstance(rows_by_name[name].get("MaxStack"), int)
        or rows_by_name[name]["MaxStack"] <= 1
    )
    if non_stackable:
        raise ValueError(
            "Individual overrides are limited to already-stackable items: "
            + ", ".join(non_stackable)
        )

    for row in itemable["Rows"]:
        original = row.get("MaxStack")
        if not isinstance(original, int) or original <= 1:
            continue

        updated, source = configured_stack(row["Name"], original, config)
        row["MaxStack"] = updated
        if updated != original:
            changes.append({"Name": row["Name"], "MaxStack": updated})
        catalog.append(
            {
                "Name": row["Name"],
                "DisplayName": row.get("DisplayName", ""),
                "OriginalMaxStack": original,
                "ConfiguredMaxStack": updated,
                "Rule": source,
            }
        )

    return changes, catalog


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")


def config_summary(config: dict[str, Any]) -> str:
    global_rule = config["global"]
    if global_rule["mode"] == "multiplier":
        base = f'base stack x{global_rule["value"]}'
    else:
        base = f'fixed stack {global_rule["value"]}'
    return (
        f'{base}, cap {global_rule["cap"]}, '
        f'{len(config["individual"])} individual override(s)'
    )


def create_exmod(
    changes: list[dict[str, int | str]], config: dict[str, Any]
) -> dict:
    return {
        "name": MOD_NAME,
        "author": "tanab",
        "version": MOD_VERSION,
        "description": (
            "Config-generated stack mod built independently from the installed "
            f"ICARUS data ({config_summary(config)}). Does not change inventories, "
            "chests, bags, tanks, batteries, or any other capacity/slot table."
        ),
        "fileName": MOD_ID,
        "week": "All",
        "Level2": "True",
        "Rows": [
            {
                "CurrentFile": "Traits-D_Itemable.json",
                "File_Items": changes,
            }
        ],
    }


def create_exmodz(exmod_path: Path, package_readme: Path) -> Path:
    exmodz_path = DIST_DIR / f"{MOD_ID}.EXMODZ"
    with zipfile.ZipFile(exmodz_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(exmod_path, f"Extracted Mods/{MOD_ID}.EXMOD")
        archive.write(package_readme, f"{MOD_ID}/README.md")
        archive.write(package_readme, f"{MOD_ID}/Readme ({MOD_ID}_P.pak).txt")
    return exmodz_path


def create_pak(itemable_path: Path) -> Path:
    pak_path = DIST_DIR / f"{MOD_ID}_P.pak"
    mounted_path = "../../../Icarus/Content/data/Traits/"

    if use_repak():
        assert REPAK is not None
        run(
            [
                str(REPAK),
                "pack",
                "--quiet",
                "--mount-point",
                mounted_path,
                "--version",
                "V11",
                "--path-hash-seed",
                "0",
                str(itemable_path.parent),
                str(pak_path),
            ]
        )
        return pak_path

    response_path = BUILD_DIR / "pak-response.txt"
    mounted_file = mounted_path + "D_Itemable.json"
    response_path.write_text(
        f'"{itemable_path}" "{mounted_file}"\n',
        encoding="utf-8",
        newline="\n",
    )
    run([str(UNREALPAK), str(pak_path), f"-Create={response_path}"])
    return pak_path


def verify_pak(pak_path: Path) -> None:
    expected_mount = "../../../Icarus/Content/data/Traits/"
    if use_repak():
        assert REPAK is not None
        actual_mount = repak_mount_point(pak_path)
        if actual_mount != expected_mount:
            raise RuntimeError(
                f"PAK verification failed: unexpected mount point {actual_mount}"
            )
        listing = run(
            [str(REPAK), "list", "--strip-prefix", actual_mount, str(pak_path)]
        ).stdout.splitlines()
        if listing != ["D_Itemable.json"]:
            raise RuntimeError(f"PAK verification failed: unexpected files {listing}")
        return

    listing = run([str(UNREALPAK), str(pak_path), "-List"]).stdout
    if "D_Itemable.json" not in listing:
        raise RuntimeError("PAK verification failed: D_Itemable.json is missing")
    if "../../../Icarus/Content/data/Traits/" not in listing:
        raise RuntimeError("PAK verification failed: unexpected mount point")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    if not DATA_PAK.is_file():
        raise FileNotFoundError(f"ICARUS data.pak was not found: {DATA_PAK}")
    if not use_repak() and not UNREALPAK.is_file():
        raise FileNotFoundError(
            "No PAK tool was found. Set REPAK_PATH or UNREALPAK_PATH, or install "
            f"UnrealPak.exe at: {UNREALPAK}"
        )
    if not CONFIG_PATH.is_file():
        raise FileNotFoundError(f"Stack configuration was not found: {CONFIG_PATH}")

    config = load_config()

    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    BUILD_DIR.mkdir(parents=True)
    DIST_DIR.mkdir(parents=True)

    with tempfile.TemporaryDirectory(prefix="TinyStack-") as temp_name:
        extract_dir = Path(temp_name) / "base-data"
        itemable, _ = load_current_itemable(extract_dir)
        write_json(BUILD_DIR / "base" / "D_Itemable.json", itemable)
        changes, catalog = apply_stack_config(itemable, config)

        if not changes:
            raise RuntimeError("The configuration does not change any ICARUS stack size")

        modded_itemable = BUILD_DIR / "staging" / "D_Itemable.json"
        write_json(modded_itemable, itemable)

    write_json(DIST_DIR / "item-catalog.json", catalog)

    exmod = create_exmod(changes, config)
    exmod_path = BUILD_DIR / f"{MOD_ID}.EXMOD"
    write_json(exmod_path, exmod)

    package_readme = BUILD_DIR / "README.md"
    package_readme.write_text(
        f"# {MOD_NAME} v{MOD_VERSION}\n\n"
        f"Build rule: {config_summary(config)}.\n\n"
        "- Unstackable equipment remains unstackable.\n"
        "- No chest, inventory, bag, liquid, fuel, or battery capacity changes.\n"
        "- Remove other stack-size mods before installing.\n",
        encoding="utf-8",
        newline="\n",
    )

    exmodz_path = create_exmodz(exmod_path, package_readme)
    pak_path = create_pak(modded_itemable)
    verify_pak(pak_path)

    manifest = {
        "mod": MOD_NAME,
        "version": MOD_VERSION,
        "source_data_pak": DATA_PAK.name,
        "source_data_sha256": sha256(DATA_PAK),
        "pak_tool": "repak" if use_repak() else "UnrealPak",
        "configuration": config,
        "changed_item_count": len(changes),
        "catalog_item_count": len(catalog),
        "individual_override_count": len(config["individual"]),
        "untouched_tables": "all except Traits/D_Itemable.json",
        "artifacts": [pak_path.name, exmodz_path.name, "item-catalog.json"],
    }
    write_json(DIST_DIR / "build-manifest.json", manifest)

    print(f"Built {MOD_NAME} v{MOD_VERSION}")
    print(f"Rule: {config_summary(config)}")
    print(f"Changed stack sizes: {len(changes)} items")
    print(f"PAK: {pak_path}")
    print(f"EXMODZ: {exmodz_path}")


if __name__ == "__main__":
    main()
