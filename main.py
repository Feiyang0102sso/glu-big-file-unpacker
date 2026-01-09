import time
import re
import logging
from config import logger,  add_file_handler_to_logger, BIG_ASSERTS_V100_PATH, OUTPUT_DIR_PATH
from big_archive import BigArchive
from extractor import ResourceExtractor
from utils_dirs import clear_output_dir


def natural_sort_key(path):
    """
    make all files in numeric order,
    eg 8,9,10,11 ...
    """
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split(r'(\d+)', path.name)]


def main():
    clear_output_dir()

    add_file_handler_to_logger()
    logger.info("=== extracting start ===")

    input_dir = BIG_ASSERTS_V100_PATH
    output_base_dir = OUTPUT_DIR_PATH

    # get all files
    big_files = list(input_dir.glob("*.big"))
    if not big_files:
        logger.warning(f"No .big files found in '{input_dir}'.")
        return

    # --- using numeric order ---
    big_files.sort(key=natural_sort_key)

    logger.info(f"Found {len(big_files)} .big files. Starting processing in natural order...")

    for filepath in big_files:
        # if one file fail to open, others can still proceed
        try:
            with BigArchive(filepath) as archive:
                extractor = ResourceExtractor(archive, output_base_dir)
                extractor.extract_all()
        except Exception as eFile:
            logger.error(f"Critical error processing file '{filepath.name}': {eFile}", exc_info=True)

    logger.info("=== extracting finishing ===")

    # shut down log
    logging.shutdown()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nThe user interrupted the process. ")  # logger might be shut down
    except Exception as e:
        print(f"An unexpected error occurred:{e}")