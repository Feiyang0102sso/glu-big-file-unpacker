"""Command-line entry point for big-tool.

The command bodies live in ``run_*`` functions so that another front end can
run the same work without going through argparse.
"""

import argparse
from collections.abc import Callable
from pathlib import Path

from big_tool.analysis.search import SearchOptions, search_path
from big_tool.big_archive.big_extractor import ExtractionResult, unpack_directory
from big_tool.config import get_output_dir, init_app_env
from big_tool.logger import logger
from big_tool.maps.renderer import render_directory
from big_tool.models.converter import convert_directory
from big_tool.version import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(prog="big-tool", description="Glu asset analysis toolkit")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    unpack_parser = subparsers.add_parser(
        "unpack", help="Extract all .big files in a directory (string packs are exported to CSV)"
    )
    unpack_parser.add_argument("input", type=Path)
    unpack_parser.add_argument("--output", type=Path)
    unpack_parser.add_argument("--no-recursive", action="store_true")
    unpack_parser.add_argument("--no-clean", action="store_true")
    unpack_parser.add_argument("--yes", action="store_true", help="Skip cleanup confirmation")
    unpack_parser.add_argument(
        "--by-section",
        action="store_true",
        help="Fill the section column of each resource manifest from the pack keyset",
    )

    search_parser = subparsers.add_parser("search", help="Search binary content")
    search_parser.add_argument("input", type=Path)
    search_parser.add_argument("--value", required=True)
    search_parser.add_argument("--mode", choices=["exact", "fuzzy"], default="exact")
    search_parser.add_argument("--little-endian", action="store_true")
    search_parser.add_argument("--extension", default="*")
    search_parser.add_argument("--start-offset", type=_parse_int)
    search_parser.add_argument("--size-min", type=_parse_int)
    search_parser.add_argument("--size-max", type=_parse_int)

    model_parser = subparsers.add_parser(
        "model-convert",
        help="Convert the meshes of every MODEL section under a directory",
    )
    model_parser.add_argument("input", type=Path)
    model_parser.add_argument(
        "--output",
        type=Path,
        help="Root for the per-pack output folders "
             "(default: a _converted_models folder inside each pack)",
    )

    map_parser = subparsers.add_parser(
        "map-render",
        help="Render every TILELAYER map of each pack, tiles and props (needs --by-section)",
    )
    map_parser.add_argument("input", type=Path)
    map_parser.add_argument(
        "--output",
        type=Path,
        help="Root for the per-pack output folders "
             "(default: a _rendered_maps folder inside each pack)",
    )
    map_parser.add_argument("--no-props", action="store_true", help="Draw the tile layers only")
    map_parser.add_argument(
        "--ani_bak",
        action="store_true",
        help="Also write an MP4 and a GIF loop of the scrolling background layers "
             "(lava, starfield, water); needs ffmpeg on PATH for the MP4",
    )
    return parser


def _parse_int(value: str) -> int:
    return int(value, 0)


def _confirm_cleanup(target_dirs: list[Path]) -> bool:
    print("The following output directories will be cleared:")
    for target_dir in target_dirs:
        print(f"  {target_dir}")
    answer = input("Continue? (y/n): ").strip().lower()
    return answer in {"y", "yes"}


# ------------------------------------------------------------------
# Commands, shared with the windowed front end
# ------------------------------------------------------------------


def run_unpack(
    input_dir: Path,
    output_dir: Path | None = None,
    recursive: bool = True,
    clean: bool = True,
    assume_yes: bool = False,
    confirm: Callable[[list[Path]], bool] | None = None,
    by_section: bool = False,
) -> list[ExtractionResult]:
    """Extract every archive under a directory.

    An empty result means nothing was unpacked: either the directory holds no
    archive, or the user turned down the cleanup.
    """
    if output_dir is None:
        output_dir = get_output_dir(input_dir)

    return unpack_directory(
        input_dir,
        output_dir=output_dir,
        recursive=recursive,
        clean=clean,
        assume_yes=assume_yes,
        confirm=confirm,
        by_section=by_section,
    )


def failed_resource_count(results: list[ExtractionResult]) -> int:
    """Return how many resources failed across every archive."""
    failed_count = 0
    for result in results:
        failed_count += result.failed_count
    return failed_count


def run_model_convert(input_dir: Path, output_dir: Path | None = None) -> int:
    """Convert the meshes of every MODEL section under a directory."""
    count = convert_directory(input_dir, output_dir)
    logger.info(f"Converted {count} model files")
    return count


def run_map_render(
    input_dir: Path,
    output_dir: Path | None = None,
    with_props: bool = True,
    animated_background: bool = False,
) -> int:
    """Render every TILELAYER map under a directory."""
    count = render_directory(
        input_dir,
        output_dir,
        with_props=with_props,
        animated_background=animated_background,
    )
    logger.info(f"Rendered {count} maps")
    return count


def main(argv: list[str] | None = None) -> int:
    """Run the selected command."""
    init_app_env()
    args = build_parser().parse_args(argv)

    if args.command == "unpack":
        results = run_unpack(
            args.input,
            output_dir=args.output,
            recursive=not args.no_recursive,
            clean=not args.no_clean,
            assume_yes=args.yes,
            confirm=_confirm_cleanup,
            by_section=args.by_section,
        )
        if failed_resource_count(results):
            return 1
        return 0

    if args.command == "search":
        options = SearchOptions(
            target_value=args.value,
            big_endian=not args.little_endian,
            file_extension=args.extension,
            mode=args.mode,
            start_offset=args.start_offset,
            size_min=args.size_min,
            size_max=args.size_max,
        )
        results = search_path(args.input, options)
        for result in results:
            offsets = ", ".join(hex(offset) for offset in result.offsets)
            logger.info(f"{result.path} [{offsets}] score={result.score}")
        return 0

    if args.command == "model-convert":
        run_model_convert(args.input, args.output)
        return 0

    if args.command == "map-render":
        run_map_render(
            args.input,
            args.output,
            with_props=not args.no_props,
            animated_background=args.ani_bak,
        )
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
