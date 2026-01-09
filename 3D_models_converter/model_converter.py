# 3D_models_converter/model_converter.py
import struct
import json
import sys
import configparser
from pathlib import Path

from config import ROOT_DIR, get_output_dir
from logger import logger, add_file_handler

# --- Constants ---
CONVERTED_DIR_NAME = 'converted_models'
CONFIG_FILENAME = 'config.ini'


# --- Core Logic Functions ---

def save_obj(filename, verts, uvs, indices):
    """ Save as OBJ format. """
    with open(filename, 'w') as o:
        o.write("# Batch Exported Glu Mesh\n")
        for v in verts:
            o.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
        for vt in uvs:
            o.write(f"vt {vt[0]:.6f} {vt[1]:.6f}\n")

        flip = False
        for i in range(len(indices) - 2):
            v1, v2, v3 = indices[i] + 1, indices[i + 1] + 1, indices[i + 2] + 1
            if v1 != v2 and v2 != v3 and v1 != v3:
                if flip:
                    o.write(f"f {v1}/{v1} {v3}/{v3} {v2}/{v2}\n")
                else:
                    o.write(f"f {v1}/{v1} {v2}/{v2} {v3}/{v3}\n")
            flip = not flip


def convert_single_bin(input_file, output_prefix):
    """
    Parse a single BIN file.
    """
    try:
        with open(input_file, 'rb') as f:
            # 1. Header
            version = struct.unpack('B', f.read(1))[0]
            index_count = struct.unpack('<I', f.read(4))[0]
            bone_count = struct.unpack('B', f.read(1))[0]
            frame_count = struct.unpack('<H', f.read(2))[0]
            vertex_count = struct.unpack('<H', f.read(2))[0]

            # 2. Nodes
            for _ in range(bone_count):
                name_len = struct.unpack('B', f.read(1))[0]
                f.read(name_len)

            # 3. Indices
            indices = [struct.unpack('<H', f.read(2))[0] for _ in range(index_count)]

            # 4. UVs
            uvs = []
            for _ in range(vertex_count):
                u, v = struct.unpack('<ff', f.read(8))
                uvs.append((u, 1.0 - v))

            # 5. Frames
            anim_start_pos = f.tell()
            animation_data = {
                "metadata": {"vertex_count": vertex_count, "frame_count": frame_count},
                "frames": []
            }

            stride = 4 + (bone_count * 28) + (vertex_count * 12)
            for i in range(frame_count):
                f.seek(anim_start_pos + i * stride)
                time_ms = struct.unpack('<I', f.read(4))[0]
                f.seek(bone_count * 28, 1)

                verts = []
                for _ in range(vertex_count):
                    x, y, z = struct.unpack('<fff', f.read(12))
                    verts.append([x, z, -y])

                animation_data["frames"].append({"time": time_ms, "vertices": verts})

        # 6. Export
        save_obj(f"{output_prefix}.obj", animation_data["frames"][0]["vertices"], uvs, indices)
        with open(f"{output_prefix}.json", 'w') as jf:
            json.dump(animation_data, jf)
        return True

    except Exception as e:
        # warning if the file can not be processed
        logger.warning(f"Skipping file {Path(input_file).name}: {e}")
        return False


# --- Helper Functions ---

def load_targets_from_config():
    """ Load paths from config.ini """
    config_path = ROOT_DIR / CONFIG_FILENAME
    targets = []
    if not config_path.exists():
        logger.warning(f"Config file not found at: {config_path}")
        return targets
    try:
        config = configparser.ConfigParser()
        config.read(config_path, encoding='utf-8')
        if 'Settings' in config and 'Targets' in config['Settings']:
            targets = [line.strip() for line in config['Settings']['Targets'].split('\n') if line.strip()]
            logger.info(f"Loaded {len(targets)} paths from config.ini")
    except Exception as e:
        logger.error(f"Error reading config: {e}")
    return targets


def process_directory(target_path_str):
    """ Scan and Convert (No Deletion) """
    target_path = Path(target_path_str)

    if not target_path.exists():
        logger.warning(f"Path does not exist: {target_path}")
        return 0

    local_output_dir = target_path / CONVERTED_DIR_NAME

    # overwrite instead of cleaning
    try:
        local_output_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"Cannot create dir {local_output_dir}: {e}")
        return 0

    bin_files = list(target_path.glob('*.bin'))
    if not bin_files:
        logger.info(f"No .bin files in {target_path.name}")
        return 0

    logger.info(f"Processing directory: {target_path.name}")

    converted_count = 0
    for bin_file in bin_files:
        output_prefix = local_output_dir / bin_file.stem
        if convert_single_bin(str(bin_file), str(output_prefix)):
            converted_count += 1

    return converted_count


def print_recommendations():
    """ Print final info """
    # Force a buffer flush to ensure the Log is printed first, then the banner is printed.
    sys.stdout.flush()
    sys.stderr.flush()

    print("\n" + "=" * 60)
    print(" BATCH PROCESSING COMPLETE")
    print("-" * 60)
    print(" [NOTE]")
    print(" Yellow warnings above mean some files were not valid models.")
    print(" This is normal behavior for asset extraction.")
    print(" Please note the code can make some mistakes, if you cant open a model files, just skip it")
    print("-" * 60)
    print(" >>> RECOMMENDATION <<<")
    print(" To preview .obj files directly in Windows Explorer,")
    print(" install 'Space Thumbnails':")
    print(" https://github.com/EYHN/space-thumbnails")
    print("=" * 60 + "\n")


def main():
    # Setup Logging
    output_dir = get_output_dir(False) # avoid creating an empty folder
    log_file = ROOT_DIR / "extractor.log"
    add_file_handler(log_file)

    logger.info(f"App Started. Logs: {log_file}")

    # Load Config
    targets = load_targets_from_config()
    mode = 'batch' if targets else 'single'

    if mode == 'batch':
        print(f"\nConfig loaded {len(targets)} paths.")
        i = input("Press [Enter] for Batch, or 's' for Single path: ").strip().lower()
        if i == 's': mode = 'single'

    total = 0

    if mode == 'batch':
        for path in targets:
            total += process_directory(path)
    else:
        while True:
            raw = input("\nEnter path (or 'q'): ").strip().strip('"')
            if raw.lower() == 'q': break
            if raw: total += process_directory(raw)

    logger.info(f"Total files successfully converted: {total}")

    print_recommendations()

    # Force refresh again to prevent the Input prompt from appearing in the middle of the log.
    sys.stdout.flush()
    sys.stderr.flush()
    input("Press Enter to exit...")


if __name__ == "__main__":
    main()