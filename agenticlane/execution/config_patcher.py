"""Runtime config patching for hierarchical flows.

Injects hardened sub-module LEF/GDS as MACROS entries into the parent
design's LibreLane configuration file.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class HardenedModule:
    """Artifacts from a hardened sub-module."""

    module_name: str
    lef_path: Path
    gds_path: Path
    nl_path: Optional[Path] = None


class HierarchicalConfigPatcher:
    """Patches parent LibreLane config with hardened module macros."""

    @staticmethod
    def patch_config(
        parent_config_path: Path,
        hardened_modules: list[HardenedModule],
        output_path: Path,
    ) -> Path:
        """Load parent config, inject MACROS, write patched config.

        Parameters
        ----------
        parent_config_path:
            Path to the parent LibreLane config (JSON or YAML).
        hardened_modules:
            List of hardened module artifacts to inject.
        output_path:
            Path to write the patched config.

        Returns
        -------
        Path
            The output_path where the patched config was written.
        """
        config = _load_config(parent_config_path)

        # Resolve ``dir::`` paths to absolute so the config works
        # even when written to a different directory than the original.
        source_dir = parent_config_path.resolve().parent
        _resolve_dir_paths(config, source_dir)

        # Build MACROS dict
        macros = config.get("MACROS", {})
        for module in hardened_modules:
            macros[module.module_name] = _build_macros_entry(module)

        config["MACROS"] = macros

        if hardened_modules:
            # Remove hardened module Verilog sources from VERILOG_FILES.
            _remove_hardened_verilog(config, hardened_modules)

            # Strip Verilog parameter overrides on hardened module
            # instances from the remaining design files.
            #
            # When picosoc.v instantiates a hardened macro like:
            #   picorv32 #(.ENABLE_IRQ(1)) cpu (...)
            # Yosys generates ``defparam`` statements in the netlist
            # using ``32'sb`` (signed binary) notation that OpenROAD
            # cannot parse.  Since the parameters are already baked
            # into the hardened module, removing the ``#(...)`` block
            # avoids the issue entirely.
            patched_src_dir = output_path.parent / "patched_src"
            _strip_param_overrides(config, hardened_modules, patched_src_dir)

            # Populate MACROS instances with hierarchical paths and
            # placement coordinates.  Must run after param stripping
            # so the simple instantiation regex works on clean source.
            _populate_macro_instances(config, hardened_modules)

            # Disable lint errors for the parent flow.  Verilator may
            # still warn about blackbox port mismatches.
            config["ERROR_ON_LINTER_ERRORS"] = False

            # Hardened macros may have intentionally unconnected pins
            # (e.g. unused IRQ, debug ports).  Tell LibreLane to
            # ignore disconnected-pin checks on macro instances.
            config["IGNORE_DISCONNECTED_MODULES"] = [
                m.module_name for m in hardened_modules
            ]

        # Write patched config as JSON
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(config, indent=2, default=str) + "\n")
        logger.info(
            "Wrote patched parent config with %d macros to %s",
            len(hardened_modules),
            output_path,
        )
        return output_path


def _resolve_dir_paths(obj: Any, source_dir: Path) -> Any:
    """Recursively resolve ``dir::`` prefixed paths to absolute paths.

    LibreLane uses ``dir::relative/path`` to mean "relative to the config
    file's directory".  When the config is copied to a different location
    the ``dir::`` references break, so we resolve them to absolute paths.
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            obj[key] = _resolve_dir_paths(value, source_dir)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            obj[i] = _resolve_dir_paths(item, source_dir)
    elif isinstance(obj, str) and obj.startswith("dir::"):
        relative = obj[5:]  # strip "dir::" prefix
        resolved = (source_dir / relative).resolve()
        return str(resolved)
    return obj


def _load_config(path: Path) -> dict[str, Any]:
    """Load a LibreLane config file (JSON or YAML)."""
    text = path.read_text()

    # Try JSON first
    try:
        return json.loads(text)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        pass

    # Fall back to YAML
    try:
        import yaml

        data = yaml.safe_load(text)
        if isinstance(data, dict):
            return data
    except ImportError:
        pass
    except Exception:
        pass

    # Last resort: treat as empty config
    logger.warning("Could not parse config at %s, using empty config", path)
    return {}


def _remove_hardened_verilog(
    config: dict[str, Any],
    hardened_modules: list[HardenedModule],
) -> dict[str, str]:
    """Remove hardened module Verilog sources from VERILOG_FILES.

    When a sub-module is hardened into a macro, its original RTL source
    must be removed from ``VERILOG_FILES`` to avoid duplicate module
    definitions during synthesis.  The removed paths are returned so
    they can be re-added as Verilog header (``vh``) entries in the
    MACROS dict — this gives yosys the parameter declarations it needs
    while keeping the module as a blackbox.

    We match filenames heuristically: a Verilog file whose stem matches
    a hardened module name (e.g. ``picorv32.v`` → module ``picorv32``)
    is removed.

    Returns
    -------
    dict[str, str]
        Mapping of module_name → removed file path.
    """
    verilog_files: list[str] = config.get("VERILOG_FILES", [])
    if not verilog_files:
        return {}

    module_names = {m.module_name.lower(): m.module_name for m in hardened_modules}
    kept: list[str] = []
    removed: dict[str, str] = {}
    for vf in verilog_files:
        stem = Path(vf).stem.lower()
        if stem in module_names:
            logger.info("Removing hardened module source from VERILOG_FILES: %s", vf)
            removed[module_names[stem]] = vf
        else:
            kept.append(vf)
    config["VERILOG_FILES"] = kept
    return removed


def _strip_param_overrides(
    config: dict[str, Any],
    hardened_modules: list[HardenedModule],
    output_dir: Path,
) -> None:
    """Strip ``#(...)`` parameter overrides on hardened module instances.

    When a sub-module is hardened, its parameters are baked into the
    LEF/GDS.  The parent Verilog source may still pass parameter
    overrides (e.g. ``picorv32 #(.ENABLE_IRQ(1)) cpu (...)``).
    Yosys synthesizes these as ``defparam`` statements using signed
    binary notation (``32'sb...``) that OpenROAD cannot parse.

    This function copies any VERILOG_FILE that instantiates a hardened
    module with parameter overrides, removes the ``#(...)`` block, and
    updates the config to point to the modified copy.
    """
    module_names = {m.module_name for m in hardened_modules}
    verilog_files: list[str] = config.get("VERILOG_FILES", [])
    updated: list[str] = []

    for vf in verilog_files:
        try:
            text = Path(vf).read_text()
        except OSError:
            updated.append(vf)
            continue

        modified = text
        for name in module_names:
            modified = _remove_instance_params(modified, name)

        if modified != text:
            output_dir.mkdir(parents=True, exist_ok=True)
            out_path = output_dir / Path(vf).name
            out_path.write_text(modified)
            logger.info(
                "Stripped parameter overrides for hardened modules in %s → %s",
                vf,
                out_path,
            )
            updated.append(str(out_path))
        else:
            updated.append(vf)

    config["VERILOG_FILES"] = updated


def _remove_instance_params(text: str, module_name: str) -> str:
    """Remove ``#(...)`` parameter blocks from instances of *module_name*.

    Transforms ``module_name #(...) inst_name (`` into
    ``module_name inst_name (``.
    """
    pattern = re.compile(rf"\b{re.escape(module_name)}\s*#\s*\(")
    result: list[str] = []
    pos = 0

    for match in pattern.finditer(text):
        # Find where '#' starts (skip whitespace between module name and #)
        hash_idx = text.index("#", match.start() + len(module_name))
        result.append(text[pos:hash_idx])

        # Track parens to find matching close of #(...)
        depth = 1
        i = match.end()  # just after the opening '('
        while i < len(text) and depth > 0:
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
            i += 1

        # Skip any whitespace after the closing ')'
        while i < len(text) and text[i] in " \t\n\r":
            i += 1

        pos = i

    if not result:
        return text

    result.append(text[pos:])
    return "".join(result)


def _populate_macro_instances(
    config: dict[str, Any],
    hardened_modules: list[HardenedModule],
) -> None:
    """Populate MACROS ``instances`` with hierarchical paths and placement.

    LibreLane's ``ManualMacroPlacement`` step requires instance entries
    with location coordinates.  This function parses the remaining parent
    Verilog sources to discover hierarchical instance paths (e.g.
    ``soc.cpu`` for a picorv32 macro) and computes simple grid placement
    coordinates based on ``DIE_AREA``.
    """
    design_name = config.get("DESIGN_NAME", "")
    verilog_files: list[str] = config.get("VERILOG_FILES", [])
    macro_names = {m.module_name for m in hardened_modules}
    macros_dict: dict[str, Any] = config.get("MACROS", {})

    if not design_name or not verilog_files:
        return

    # --- Step 1: Parse Verilog to discover module bodies ---
    module_bodies: dict[str, str] = {}
    for vf in verilog_files:
        try:
            text = Path(vf).read_text()
        except OSError:
            continue
        for match in re.finditer(r"\bmodule\s+(\w+)", text):
            mod_name = match.group(1)
            end = text.find("endmodule", match.end())
            if end == -1:
                end = len(text)
            module_bodies[mod_name] = text[match.start() : end]

    # --- Step 2: Find instantiations within each module body ---
    # Strip ALL #(...) parameter blocks (which may have nested parens)
    # so the simple regex `module_name inst_name (` always works.
    known_modules = set(module_bodies.keys()) | macro_names
    # module_insts[parent_module] = [(child_module, instance_name), ...]
    module_insts: dict[str, list[tuple[str, str]]] = {}
    for mod_name, body in module_bodies.items():
        clean_body = _strip_all_param_blocks(body)
        insts: list[tuple[str, str]] = []
        for child_mod in known_modules:
            if child_mod == mod_name:
                continue
            pat = re.compile(
                rf"\b{re.escape(child_mod)}\s+(\w+)\s*\("
            )
            for m in pat.finditer(clean_body):
                insts.append((child_mod, m.group(1)))
        module_insts[mod_name] = insts

    # --- Step 3: Walk hierarchy from top module to find macro paths ---
    instance_paths: dict[str, list[str]] = {n: [] for n in macro_names}

    def _walk(current: str, prefix: str) -> None:
        for child_mod, inst_name in module_insts.get(current, []):
            path = f"{prefix}.{inst_name}" if prefix else inst_name
            if child_mod in macro_names:
                instance_paths[child_mod].append(path)
            else:
                _walk(child_mod, path)

    _walk(design_name, "")

    # --- Step 4: Compute non-overlapping placement coordinates ---
    all_instances: list[tuple[str, str]] = []
    for mod_name in macro_names:
        for path in instance_paths.get(mod_name, []):
            all_instances.append((mod_name, path))

    if not all_instances:
        logger.warning(
            "Could not find macro instances in Verilog for %s",
            [m.module_name for m in hardened_modules],
        )
        return

    # Read macro dimensions from LEF files for non-overlapping placement.
    macro_sizes: dict[str, tuple[float, float]] = {}
    for hmod in hardened_modules:
        w, h = _read_lef_size(hmod.lef_path)
        macro_sizes[hmod.module_name] = (w, h)

    die = config.get("DIE_AREA", [0, 0, 1000, 1000])
    x1, y1, x2, y2 = float(die[0]), float(die[1]), float(die[2]), float(die[3])
    margin = min(x2 - x1, y2 - y1) * 0.05
    halo = 10.0  # spacing between macros (um)

    # Place macros in a row along the bottom, left to right.
    cursor_x = x1 + margin
    for mod_name, inst_path in all_instances:
        mw, mh = macro_sizes.get(mod_name, (0, 0))
        x = round(cursor_x, 2)
        y = round(y1 + margin, 2)
        cursor_x += mw + halo

        if mod_name in macros_dict:
            macros_dict[mod_name].setdefault("instances", {})[inst_path] = {
                "location": [x, y],
                "orientation": "N",
            }
            logger.info(
                "Placed macro instance %s (%s) at [%.1f, %.1f] "
                "(size %.1f x %.1f)",
                inst_path,
                mod_name,
                x,
                y,
                mw,
                mh,
            )


def _read_lef_size(lef_path: Path) -> tuple[float, float]:
    """Extract macro SIZE from a LEF file.

    Returns ``(width, height)`` in microns, or ``(0, 0)`` if not found.
    """
    try:
        text = lef_path.read_text()
    except OSError:
        return (0.0, 0.0)
    match = re.search(r"SIZE\s+([\d.]+)\s+BY\s+([\d.]+)", text)
    if match:
        return float(match.group(1)), float(match.group(2))
    return (0.0, 0.0)


def _strip_all_param_blocks(text: str) -> str:
    """Remove all ``#(...)`` parameter blocks from Verilog text.

    Used to simplify instance extraction: after stripping, every
    instantiation becomes ``module_name instance_name (...)``.
    """
    pattern = re.compile(r"#\s*\(")
    result: list[str] = []
    pos = 0
    for match in pattern.finditer(text):
        result.append(text[pos : match.start()])
        depth = 1
        i = match.end()
        while i < len(text) and depth > 0:
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
            i += 1
        # Skip trailing whitespace
        while i < len(text) and text[i] in " \t\n\r":
            i += 1
        pos = i
    if not result:
        return text
    result.append(text[pos:])
    return "".join(result)


def _build_macros_entry(module: HardenedModule) -> dict[str, Any]:
    """Build a single MACROS entry for a hardened module."""
    entry: dict[str, Any] = {
        "instances": {},
        "lef": [str(module.lef_path)],
        "gds": [str(module.gds_path)],
    }
    if module.nl_path:
        entry["nl"] = [str(module.nl_path)]
    return entry
