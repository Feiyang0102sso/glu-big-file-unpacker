"""
Task chain of the release app.

Every stage is the same ``run_*`` function the command line calls, so the two
front ends cannot drift apart. Unpacking produces the directory that the
post-processing stages read, so a short pause is kept between the two halves
to let the file system settle.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import time

from big_tool.app.options import (
    KEY_BY_SECTION,
    KEY_CONVERT_MODELS,
    KEY_RENDER_MAPS,
    KEY_UNPACK,
    OptionSet,
)
from big_tool.cli import (
    failed_resource_count,
    run_map_render,
    run_model_convert,
    run_unpack,
)
from big_tool.config import get_output_dir
from big_tool.logger import logger

# Seconds to wait after unpacking before the post-processing stages start.
STAGE_PAUSE_SECONDS = 1.5


@dataclass
class PipelineRequest:
    """The task chain to run, as selected in the option pane."""

    input_dir: Path
    unpack: bool
    by_section: bool
    convert_models: bool
    render_maps: bool

    @property
    def has_post_processing(self) -> bool:
        """Return whether any stage runs after unpacking."""
        return self.convert_models or self.render_maps


def build_request(option_set: OptionSet, input_dir: Path) -> PipelineRequest:
    """Turn the option pane state into a pipeline request."""
    # is_active, not is_checked: a greyed out box keeps its tick, and running
    # what the window shows as unavailable would surprise everyone.
    return PipelineRequest(
        input_dir=input_dir,
        unpack=option_set.is_active(KEY_UNPACK),
        by_section=option_set.is_active(KEY_BY_SECTION),
        convert_models=option_set.is_active(KEY_CONVERT_MODELS),
        render_maps=option_set.is_active(KEY_RENDER_MAPS),
    )


def run_pipeline(
    request: PipelineRequest,
    confirm_cleanup: Callable[[list[Path]], bool],
) -> int:
    """Run the selected stages and return the number of failed resources."""
    failed_count = 0
    # Without an unpack stage the input directory is already an unpacked tree.
    post_processing_dir = request.input_dir

    if request.unpack:
        output_dir = get_output_dir(request.input_dir)
        logger.info(f"[Unpack] {request.input_dir} -> {output_dir}")
        results = run_unpack(
            request.input_dir,
            output_dir=output_dir,
            confirm=confirm_cleanup,
            by_section=request.by_section,
        )

        # No results means no archive was found, or the cleanup was turned
        # down: either way there is nothing for the later stages to read.
        if not results:
            logger.warning("[Pipeline] Nothing was unpacked, stopping here")
            return 0

        failed_count = failed_resource_count(results)
        post_processing_dir = output_dir
        logger.info(f"[Unpack] Done, {failed_count} resources failed")

        if request.has_post_processing:
            logger.info(f"[Pipeline] Post-processing starts in {STAGE_PAUSE_SECONDS}s")
            time.sleep(STAGE_PAUSE_SECONDS)

    if request.convert_models:
        logger.info(f"[Models] Converting under {post_processing_dir}")
        run_model_convert(post_processing_dir)

    if request.render_maps:
        logger.info(f"[Maps] Rendering under {post_processing_dir}")
        run_map_render(post_processing_dir, animated_background=True)

    logger.info("[Pipeline] All selected tasks finished")
    return failed_count
