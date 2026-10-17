"""The consoles the editor exports for (wx-free): one entry per fully supported console, the one table the editor and
the build follow (docs/CONSOLES.md says what full support means).

File ▸ Export lists the entries and one dialog serves them all (ui/console_export_dialog.py: the folder, the mappings
and, where the export bakes for one of the console's setups, the setups); the remembered choices go under the entry's
key; Check Project counts video memory with the entry's tile check; the smoke test exports with every entry; the three
editor specs bundle every exporter; the Windows kit carries every exporter with its demo and the part of its SDK the
demo builds with.

An entry holds what differs in substance: the SDK, the runtime files a game folder needs, what the dialog says, the
remembered choices' key, whether the export has setups, and what the Windows kit takes of the SDK. Everything else is
named after the console's key in consoles.py (docs/CONSOLES.md, Names), and tests/test_console_exports.py checks it
is there:

- the exporter, ``examples/<key>/tools/export_<key>.py``: ``export_project(project, folder, mapping_selector)`` (with
  ``setup_key=`` when the export has setups), ``report_line(summary)`` (the editor's report), ``main()`` (the
  command line, through ``console_bake.export_arguments``) and ``bake_context(project, mappings, setup_key)`` (its
  bake without writing, whose ``_stored_part`` tells export_modes what a part is in hardware sprites and tiles);
- its spec, ``build_<key>_exporter.spec`` (the command-line download);
- the demo, ``examples/<key>/<key>_demo`` (with the runtime), and ``examples/<key>/README.md``;
- the checks ``project_check.<key>_tile_issue(tiles)`` and ``project_check.<key>_palette_issue(entries)``, and for a
  console that streams (``modes``) ``project_check.<key>_stream_issues(slot_tiles, scene_slot_tiles)``;
- the Windows kit's ``packaging/windows_kit/export_to_<key>.bat`` and ``build_<key>_demo.bat``.

Only the standard library and consoles.py are imported at the top: the build specs import this module.
"""

from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import consoles

REPO = Path(__file__).resolve().parent


@dataclass(frozen=True)
class ConsoleExport:
    console: consoles.Console
    sdk: str  # what the export is for, as menus and dialogs name it with the console: "Mega Drive (SGDK)"
    runtime: Tuple[str, ...]  # the files a game folder needs (the demo has them), relative to it, with "/"
    intro: str  # the export dialog's text: what goes into the game's folder; {runtime} names the runtime's files
    preference: str  # remembered per project: "<preference>/<project>" the folder, then its "Mapping" and "Setup"
    old_preference: str = ""  # an earlier name of ``preference``, read where it has nothing
    setups: str = ""  # the export bakes for one of the console's setups: the dialog's row for them ("": none)
    tiles_about: bool = False  # the sprite tiles a game has depend on its video memory layout: "~1424"
    sdk_folder: str = ""  # where the demo's build finds the SDK, in the demo's folder
    sdk_in_git: bool = False  # the SDK is in the repository; else the Windows kit is given it unpacked (--sdk KEY=DIR)
    sdk_keep: Tuple[str, ...] = ()  # what the Windows kit takes of the SDK: its paths that start so
    sdk_needs: Tuple[str, ...] = ()  # what the SDK must have for the demo to build (the kit checks)
    modes: Tuple[str, ...] = ("parts",)  # the ways its exporter and runtime store the sprites (export_modes' keys)

    @property
    def key(self) -> str:
        return self.console.key

    @property
    def name(self) -> str:
        return self.console.name

    @property
    def title(self) -> str:
        """"Mega Drive (SGDK)": File ▸ Export and the dialog."""
        return f"{self.name} ({self.sdk})"

    @property
    def tools(self) -> str:
        return f"examples/{self.key}/tools"

    @property
    def module(self) -> str:
        return f"export_{self.key}"

    @property
    def script(self) -> str:
        return f"{self.tools}/{self.module}.py"

    @property
    def spec(self) -> str:
        return f"build_{self.key}_exporter.spec"

    @property
    def demo(self) -> str:
        return f"examples/{self.key}/{self.key}_demo"

    @property
    def readme(self) -> str:
        return f"examples/{self.key}/README.md"

    @property
    def sdk_path(self) -> str:
        """Where the SDK is in the repository's layout: "examples/snes/snes_demo/third_party/pvsneslib/"."""
        return f"{self.demo}/{self.sdk_folder}/"

    @property
    def kit_scripts(self) -> Tuple[str, str]:
        """The Windows kit's scripts (packaging/windows_kit): export a project and build the demo, build the demo."""
        return f"export_to_{self.key}.bat", f"build_{self.key}_demo.bat"

    def runtime_names(self) -> str:
        """"src/modsprite.c and inc/modsprite.h"."""
        files = list(self.runtime)
        return files[0] if len(files) == 1 else ", ".join(files[:-1]) + " and " + files[-1]

    def intro_text(self) -> str:
        return self.intro.format(runtime=self.runtime_names())

    def has_runtime(self, folder: str) -> bool:
        """Whether the folder holds the runtime the exported data is for (a game's folder, or the demo)."""
        return all(os.path.exists(os.path.join(folder, *path.split("/"))) for path in self.runtime)

    def load(self) -> Any:
        """The exporter's module: from examples/<key>/tools in the source tree, bundled in the built editor (the
        editor specs' hiddenimports)."""
        tools = str(REPO / self.tools)
        if os.path.isdir(tools) and tools not in sys.path:
            sys.path.insert(0, tools)
        return importlib.import_module(self.module)

    def export(self, project: Any, folder: str, mapping_selector: str = "all", setup_key: str = "",
               mode: str = "parts") -> Any:
        """Bake the project into a game's folder: the exporter's result (summary, issues, files). ``setup_key`` (one of
        the console's setups) goes to an export with setups, ``mode`` (one of ``modes``) to one with several ways to
        store the sprites; the exporter raises what it cannot export."""
        options: Dict[str, Any] = {"setup_key": setup_key} if self.setups else {}
        if len(self.modes) > 1:
            options["mode"] = mode
        return self.load().export_project(project, Path(folder), mapping_selector, **options)

    def bake_context(self, project: Any, mappings: List[Any], setup_key: str = "") -> Any:
        """The exporter's bake (a console_bake.ConsoleBake) for measuring, with the same cut and tiles as its export:
        ``bake_context(project, mappings, setup_key)`` in the exporter (export_modes)."""
        return self.load().bake_context(project, mappings, setup_key)

    def report_line(self, summary: Dict[str, Any]) -> str:
        """The export report's line about the console: video memory, the data (the exporter's ``report_line``)."""
        return self.load().report_line(summary)

    def tile_issue(self, tiles: int) -> Any:
        """How the export's sprite tiles fit the console: ``project_check.<key>_tile_issue``, an Issue."""
        import project_check

        return getattr(project_check, f"{self.key}_tile_issue")(tiles)

    def stream_issues(self, slot_tiles: int, scene_slot_tiles: int, largest_upload: int = 0) -> List[Any]:
        """A streamed export's slots on the console: ``project_check.<key>_stream_issues`` (consoles whose runtime
        streams, ``modes`` beyond "parts"); ``largest_upload``: what filling a slot costs at most in vertical blank, in
        bytes of DMA (0: its tiles' bytes)."""
        import project_check

        return getattr(project_check, f"{self.key}_stream_issues")(slot_tiles, scene_slot_tiles, largest_upload)

    def palette_issue(self, entries: int) -> Any:
        """How the export's palette entries fit the console: ``project_check.<key>_palette_issue``, an Issue or None."""
        import project_check

        return getattr(project_check, f"{self.key}_palette_issue")(entries)


MEGA_DRIVE = ConsoleExport(
    consoles.MEGA_DRIVE, "SGDK",
    runtime=("src/modsprite.c", "inc/modsprite.h"),
    intro=("The data goes into the game's SGDK project folder: res/gen/modsprite_blob.bin, inc/modsprite_data.h, "
           "src/modsprite_data.c and one line in res/resources.res (the game's other resources stay). The folder needs "
           "the runtime, {runtime}; the SGDK demo in the source code has it."),
    preference="MegaDriveExport", old_preference="SGDKExport",  # "SGDKExport" up to 0.10.2
    tiles_about=True,  # 1424 tiles are free in SGDK's default layout
    sdk_folder="third_party/sgdk", sdk_in_git=True,
    # What building the demo needs (Windows tools, headers, prebuilt libraries, boot code) and SGDK's license; its
    # samples, docs and tool sources stay out.
    sdk_keep=("bin/", "inc/", "lib/", "src/", "res/", "common.mk", "makefile.gen", "makelib.gen", "md.ld",
              "license.txt", "COPYING.RUNTIME", "readme.md", "changelog.txt"),
    sdk_needs=("lib/",),  # the prebuilt libraries
    modes=("parts", "parts_streamed", "frames_streamed"),  # export_megadrive.MODES, MS_STREAMED in its runtime
)

SNES = ConsoleExport(
    consoles.SNES, "PVSnesLib",
    runtime=("src/modsprite.c", "src/modsprite_draw.asm", "inc/modsprite.h"),
    intro=("The data goes into the game's PVSnesLib project folder: res/ms_chunk_NN.bin (a ROM bank each), "
           "modsprite_chunks.asm, inc/modsprite_data.h, src/modsprite_data.c and modsprite_rom.mk (the ROM size, for "
           "the Makefile). The folder needs the runtime, {runtime}; the SNES demo in the source code has it. Stored as "
           "parts kept in video memory, every sprite tile must fit: the sizes show what each pair needs with every "
           "mapping."),
    preference="SNESExport",
    setups="Sprite sizes",  # the six pairs (OBSEL), each with the tiles the project needs with it
    sdk_folder="third_party/pvsneslib",  # PVSnesLib's Windows release, unpacked (not in git)
    # What building the demo needs from it (tools, headers, libraries) and its license; its documentation, examples
    # and editor template stay out.
    sdk_keep=("devkitsnes/", "pvsneslib/include/", "pvsneslib/lib/", "pvsneslib/pvsneslib_license.txt",
              "pvsneslib/pvsneslib_snesmod.txt", "pvsneslib/pvsneslib_version.txt"),
    sdk_needs=("devkitsnes/bin/816-tcc.exe", "devkitsnes/bin/wla-65816.exe", "devkitsnes/bin/wlalink.exe",
               "devkitsnes/tools/816-opt.exe", "devkitsnes/include/hdr.asm.in", "pvsneslib/lib/LoROM_FastROM"),
    modes=("parts", "parts_streamed", "frames_streamed"),  # export_snes.MODES, MS_STREAMED in its runtime
)

EXPORTS: Tuple[ConsoleExport, ...] = (MEGA_DRIVE, SNES)  # File ▸ Export's order


def for_console(key: Optional[str]) -> Optional[ConsoleExport]:
    """The export for the console with this key (the default console's for an unknown one, as
    ``consoles.console_by_key``); None for a console without an export."""
    console = consoles.console_by_key(key)
    return next((export for export in EXPORTS if export.console is console), None)


def tools_folders() -> List[str]:
    """Every exporter's folder: the editor specs' pathex."""
    return [export.tools for export in EXPORTS]


def modules() -> List[str]:
    """Every exporter's module: the editor specs' hiddenimports (the editor runs the exporters itself)."""
    return [export.module for export in EXPORTS]
