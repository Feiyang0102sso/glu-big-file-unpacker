"""
Option tree of the release app.

The pane is a flat list of rows: a row is either a checkbox or a plain group
header. Nesting is expressed by ``indent`` and by ``parent_key``, which greys a
row out while its parent checkbox is off.
"""

from dataclasses import dataclass
from pathlib import Path

# Checkbox identifiers, used by the pipeline to read the user's choices.
KEY_UNPACK = "unpack"
KEY_BY_SECTION = "by_section"
KEY_CONVERT_MODELS = "convert_models"
KEY_RENDER_MAPS = "render_maps"

# A header row carries no identifier.
HEADER_KEY = ""

# These stages read the section folders that only the by-section pass creates.
POST_PROCESSING_KEYS = (KEY_CONVERT_MODELS, KEY_RENDER_MAPS)

# Rows of a group are indented by this many spaces per level.
INDENT_WIDTH = 2


@dataclass
class OptionRow:
    """One line of the option pane."""

    label: str
    key: str = HEADER_KEY
    checked: bool = False
    indent: int = 0
    # The checkbox that must be on before this row has any effect.
    parent_key: str = HEADER_KEY

    @property
    def is_header(self) -> bool:
        """Return whether the row is a plain group title."""
        return self.key == HEADER_KEY


def build_default_rows() -> list[OptionRow]:
    """Build the option rows with their release defaults."""
    return [
        OptionRow(label="Unpack .big archives", key=KEY_UNPACK, checked=True),
        OptionRow(
            label="by section",
            key=KEY_BY_SECTION,
            checked=True,
            indent=1,
            parent_key=KEY_UNPACK,
        ),
        OptionRow(label="Post-processing"),
        OptionRow(label="Convert models", key=KEY_CONVERT_MODELS, indent=1),
        OptionRow(label="Render maps", key=KEY_RENDER_MAPS, indent=1),
    ]


class OptionSet:
    """The state behind the checkboxes of the option pane."""

    def __init__(self) -> None:
        self.rows = build_default_rows()

    def set_checked(self, key: str, checked: bool) -> None:
        """Store the new state of one checkbox."""
        for row in self.rows:
            if row.key == key:
                row.checked = checked
                return

    def is_checked(self, key: str) -> bool:
        """Return whether the checkbox with this key is on."""
        for row in self.rows:
            if row.key == key:
                return row.checked
        return False

    def is_enabled(self, row: OptionRow) -> bool:
        """Return whether a row currently has any effect."""
        if row.parent_key != HEADER_KEY:
            return self.is_checked(row.parent_key)

        # Post-processing looks for the *_MODEL and section folders that the
        # by-section pass names. A run that unpacks without it produces none,
        # so those stages have nothing to work on. Reading an already unpacked
        # directory is a different story: that tree may carry them already.
        if row.key in POST_PROCESSING_KEYS:
            unpacks_without_sections = (
                self.is_checked(KEY_UNPACK) and not self.is_checked(KEY_BY_SECTION)
            )
            if unpacks_without_sections:
                return False

        return True

    def is_active(self, key: str) -> bool:
        """Return whether a checkbox is on *and* currently has any effect.

        A disabled checkbox keeps whatever it was ticked with, so the task
        chain has to ask this rather than ``is_checked``.
        """
        for row in self.rows:
            if row.key == key:
                return row.checked and self.is_enabled(row)
        return False

    def any_task_selected(self) -> bool:
        """Return whether at least one task checkbox is on."""
        task_keys = [KEY_UNPACK, KEY_CONVERT_MODELS, KEY_RENDER_MAPS]
        for key in task_keys:
            if self.is_checked(key):
                return True
        return False


def collect_problems(option_set: OptionSet, input_text: str) -> list[str]:
    """Return the reasons why the current selection cannot run yet."""
    problems: list[str] = []

    input_dir = parse_input_path(input_text)
    if input_dir is None:
        problems.append("Drop a directory into the input field.")
    elif not input_dir.is_dir():
        problems.append(f"Not a directory: {input_dir}")

    problems.extend(collect_task_problems(option_set))
    return problems


def collect_task_problems(option_set: OptionSet) -> list[str]:
    """Return the reasons the chosen tasks cannot run, whatever the input is."""
    problems: list[str] = []

    if not option_set.any_task_selected():
        problems.append("Select at least one task.")

    # Map rendering reads the section column that only the by-section pass fills.
    renders_maps = option_set.is_checked(KEY_RENDER_MAPS)
    unpacks = option_set.is_checked(KEY_UNPACK)
    if renders_maps and unpacks and not option_set.is_checked(KEY_BY_SECTION):
        problems.append("Render maps needs 'by section' when unpacking.")

    return problems


def parse_input_path(input_text: str) -> Path | None:
    """Turn the raw input field text into a path.

    Dropping a folder onto a console window pastes it quoted when the path
    contains spaces, so the quotes are stripped here.
    """
    text = input_text.strip().strip('"').strip("'").strip()
    if not text:
        return None
    return Path(text)
