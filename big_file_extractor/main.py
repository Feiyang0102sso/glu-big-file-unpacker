import re
import logging
import config
from logger import logger
from utils.utils_dirs import clear_directory
from big_archive import BigArchive
from extractor import ResourceExtractor


def natural_sort_key(path):
    """
    使文件按数字顺序排序，例如 8, 9, 10, 11 ...
    """
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split(r'(\d+)', path.name)]


def main():
    print("=== Big File Extractor ===")
    user_path = input("Please enter the folder path containing the .big file: ").strip().replace('"', '')

    # initialize log system
    if user_path:
        config.update_paths(new_input=user_path)
    else:
        config.update_paths()

    logger.info("=== Extraction task begins ===")
    # input dir after update
    logger.info(f"Scanning the directory: {config.input_dir}")

    # Get and sort all .big files
    big_files = list(config.input_dir.glob("*.big"))
    if not big_files:
        logger.warning(f"In '{config.input_dir}' No .big files were found.")
        return

    big_files.sort(key=natural_sort_key)
    logger.info(f"total {len(big_files)} .big files were found; processing them sequentially will begin...")

    for filepath in big_files:
        try:
            # remove old datas
            target_package_dir = config.input_dir / filepath.stem

            logger.info(f"正在处理: {filepath.name}")

            # silent mod here
            clear_directory(target_package_dir, silent=True)

            with BigArchive(filepath) as archive:
                # use the file path determined in extractor.py
                extractor = ResourceExtractor(archive, config.input_dir)
                extractor.extract_all()

        except Exception as e_file:
            logger.error(f"process file '{filepath.name}' fail:  {e_file}", exc_info=True)

    logger.info("=== All tasks completed. ===")
    logging.shutdown()

    # To optimize the user experience of the packaged EXE file
    # and prevent the window from disappearing abruptly.
    input("\nProcessing complete. Press Enter to exit...")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nUser interruption.")
    except Exception as e:
        print(f"A fatal error has occurred: {e}")