# /utils_dirs.py
import shutil
from pathlib import Path
from logger import logger

def clear_directory(dir_path: Path, silent: bool = False):
    """
    Clear all contents of a directory. Asks for user confirmation if not silent.
    """
    if not dir_path.exists():
        dir_path.mkdir(parents=True, exist_ok=True)
        return

    if not silent:
        # User confirmation prompt
        confirm = input(f"(!) Warning: Directory '{dir_path}' will be cleared. Continue? (y/n): ")
        if confirm.lower() != 'y':
            logger.info("Directory clearing cancelled by user.")
            return

    try:
        # Using rmtree to delete everything
        shutil.rmtree(dir_path)
        # Recreate the empty directory
        dir_path.mkdir(parents=True, exist_ok=True)
        logger.warning(f"Directory cleared and rebuilt: '{dir_path}'")
    except PermissionError:
        logger.error(f"Permission denied: Could not clear '{dir_path}'. Is a file open?")
    except Exception as e:
        logger.critical(f"Unexpected error while clearing directory: {e}")