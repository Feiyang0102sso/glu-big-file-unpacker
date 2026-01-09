import os
import mmap
import binascii
from pathlib import Path
from typing import List, Optional, Tuple

# 从你的 config.py 导入 logger 和路径获取函数
# 假设 config.py 提供了 logger 和路径常量
from config import logger, OUTPUT_DIR_PATH_V360, OUTPUT_DIR_PATH, ROOT_DIR


# 假设的路径常量
# OUTPUT_DIR_PATH = Path('./search_test_output')

# =========================================
# [硬编码配置区域] - 修改此处来改变搜索目标
# =========================================

"""
--- 搜索配置说明 ---

TARGET_VALUE: 
    要查找的数值。
    - 十进制数: 10000
    - 十六进制数: 0x2710 (推荐使用)

SEARCH_MODE:
    - 'exact': (严格模式) 目标值必须匹配，且必须满足所有额外的过滤条件 (大小/偏移)。
    - 'fuzzy': (模糊模式) 目标值必须匹配。额外的过滤条件 (大小/偏移) 每匹配一个，
               会额外奖励一个 '*'。星号越多的文件越优先显示。

SEARCH_BIG_ENDIAN:
    True = 大端序 (BE), False = 小端序 (LE) (默认)

SEARCH_FILE_EXT:
    指定要搜索的文件后缀 (例: '.bin', '.dat')。
    - 空字符串 (''): 仅搜索没有后缀名的文件。
    - '*' 或 None: 搜索所有文件。

SEARCH_PATH: 
    搜索的根目录。

--- 额外匹配选项 (Extra Filters) ---
(不填 None 或 0 代表不应用该过滤条件)

START_OFFSET_HEX: 
    目标值必须在此十六进制偏移处开始。
    例: '0x1000'

FILE_SIZE_MIN_HEX / FILE_SIZE_MAX_HEX: 
    文件大小范围过滤 (十六进制)。
    例: ('0x800', '0x100000') 代表文件大小在 2KB 到 1MB 之间。
"""

TARGET_VALUE = "0x8275260001"
SEARCH_MODE = "exact"  # **必填** 'exact' 或 'fuzzy'
SEARCH_BIG_ENDIAN = True  # True = 大端序, False = 小端序 (默认)
SEARCH_FILE_EXT = ".bin"  # 指定要搜索的文件后缀。''表示无后缀，'*'或None表示所有文件。
SEARCH_PATH = Path(r'D:\python coding\big_asserts\DATAS\output360\pack2_xga\0xf4e02223')

# OUTPUT_DIR_PATH_V360

# 额外过滤条件 (Extra Filters)
START_OFFSET_HEX: Optional[str] = None # 目标值必须从此偏移开始 (十六进制)
FILE_SIZE_MIN_HEX: Optional[str] = '0x00'  # 文件最小大小 (十六进制)
FILE_SIZE_MAX_HEX: Optional[str] = None  # 文件最大大小 (十六进制)


# =========================================


def parse_value_to_bytes(value_str: str, big_endian: bool = False) -> Optional[bytes]:
    """
    将十进制或十六进制字符串转换为字节序列。
    """
    clean_value = str(value_str).strip()

    if clean_value.lower().startswith('0x'):
        # 十六进制处理
        clean_hex = clean_value[2:].lower().replace(' ', '').replace(',', '').replace('_', '')
        if len(clean_hex) == 0:
            logger.error(f"配置错误: '{value_str}' 不是有效的十六进制字符串")
            return None
        if len(clean_hex) % 2 != 0:
            clean_hex = '0' + clean_hex

        try:
            target_bytes = bytes.fromhex(clean_hex)
        except ValueError:
            logger.error(f"配置错误: '{value_str}' 不是有效的十六进制字符串")
            return None
    else:
        # 十进制处理
        try:
            decimal_val = int(clean_value)
        except ValueError:
            logger.error(f"配置错误: '{value_str}' 不是有效的数值 (十进制或十六进制)")
            return None

        if decimal_val < 0:
            logger.error("配置错误: 目标数值不能为负数")
            return None

        # 自动确定字节长度 (至少1字节，保证是2的幂次)
        length = (decimal_val.bit_length() + 7) // 8
        if length == 0:  # 处理 0 的情况
            length = 1
            # 确保长度为 2, 4, 或 8 字节
        if length > 4:
            length = 8
        elif length > 2:
            length = 4
        else:
            length = 2  # 默认至少搜索2字节，除非用户明确输入1字节的hex

        # 将整数转换为定长字节
        try:
            target_bytes = decimal_val.to_bytes(length, byteorder='big' if big_endian else 'little')
        except OverflowError:
            logger.error(f"配置错误: 数值 {decimal_val} 过大，无法转换为 {length} 字节")
            return None

    if not big_endian:
        target_bytes = target_bytes[::-1]  # 反转以匹配小端序

    return target_bytes


def search_in_file(filepath: Path, target_bytes: bytes) -> List[int]:
    """
    在单个文件中搜索目标字节序列，返回偏移量列表。
    """
    offsets = []
    try:
        # 如果文件为空，直接返回
        if filepath.stat().st_size == 0:
            return offsets

        with open(filepath, 'rb') as f:
            # 使用 mmap 进行高效文件搜索
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as s:
                loc = s.find(target_bytes)
                while loc != -1:
                    offsets.append(loc)
                    # 从下一个字节开始继续搜索，防止重复匹配
                    loc = s.find(target_bytes, loc + 1)
    except Exception as e:
        logger.error(f"无法读取文件 {filepath.name}: {e}")

    return offsets


def parse_hex_param(hex_str: Optional[str]) -> Optional[int]:
    """解析十六进制或十进制字符串为整数，处理 None/空字符串。"""
    if hex_str is None or str(hex_str).strip() == '':
        return None

    clean_str = str(hex_str).strip()
    try:
        if clean_str.lower().startswith('0x'):
            return int(clean_str, 16)
        else:
            return int(clean_str, 10)
    except ValueError:
        logger.warning(f"警告: 无法解析参数 '{hex_str}' 为有效数值，将忽略此过滤条件。")
        return None


def check_extra_match(file_size: int, offsets: List[int], start_offset: Optional[int], size_min: Optional[int],
                      size_max: Optional[int]) -> Tuple[bool, int]:
    """
    检查文件是否满足额外的过滤条件。
    返回: (是否满足所有EXACT条件, 匹配的FUZZY条件数量)
    """
    exact_match = True
    fuzzy_stars = 0

    # 1. 检查起始偏移 (Start Offset)
    start_offset_match = start_offset is None or start_offset in offsets
    if start_offset is not None:
        if start_offset_match:
            fuzzy_stars += 1
        else:
            exact_match = False

    # 2. 检查文件大小 (Min Size)
    size_min_match = size_min is None or file_size >= size_min
    if size_min is not None:
        if size_min_match:
            fuzzy_stars += 1
        else:
            exact_match = False

    # 3. 检查文件大小 (Max Size)
    size_max_match = size_max is None or file_size <= size_max
    if size_max is not None:
        if size_max_match:
            fuzzy_stars += 1
        else:
            exact_match = False

    return exact_match, fuzzy_stars


def main():
    # 1. 获取搜索路径
    try:
        search_dir = SEARCH_PATH
        if not search_dir.is_dir():
            logger.critical(f"路径配置错误: 搜索目录 '{search_dir}' 不存在或不是一个目录。")
            return
    except Exception as e:
        logger.critical(f"路径配置错误: {e}")
        return

    # 2. 准备搜索数据和参数
    target_bytes = parse_value_to_bytes(TARGET_VALUE, SEARCH_BIG_ENDIAN)
    if not target_bytes:
        return

    # 解析额外过滤条件
    start_offset = parse_hex_param(START_OFFSET_HEX)
    size_min = parse_hex_param(FILE_SIZE_MIN_HEX)
    size_max = parse_hex_param(FILE_SIZE_MAX_HEX)

    # 准备日志信息
    endian_str = "大端序" if SEARCH_BIG_ENDIAN else "小端序"
    ext_str = f"'{SEARCH_FILE_EXT}'" if SEARCH_FILE_EXT != '' else "无后缀"
    ext_str = "所有文件" if SEARCH_FILE_EXT == '*' or SEARCH_FILE_EXT is None else ext_str

    logger.info(f"--- [ {SEARCH_MODE.upper()} 模式 ] 开始搜索 ---")
    logger.info(f"搜索目录: {search_dir}")
    logger.info(f"目标数值: {TARGET_VALUE} ({endian_str})")
    logger.info(f"实际字节: {binascii.hexlify(target_bytes).decode('utf-8')}")
    logger.info(f"文件后缀: {ext_str}")
    logger.info(
        f"额外过滤: 偏移={hex(start_offset) if start_offset is not None else 'N/A'}, 大小范围=[{hex(size_min) if size_min is not None else '0'} ~ {hex(size_max) if size_max is not None else '∞'}]")
    logger.info("-" * 30)

    match_count = 0
    file_count = 0
    fuzzy_results = []  # 存储模糊搜索结果 (星级, 相对路径, 偏移列表)

    # 3. 开始遍历和搜索
    for root, _, files in os.walk(search_dir):
        for file_name in files:
            file_path = Path(root) / file_name
            file_size = file_path.stat().st_size

            # 文件后缀过滤逻辑
            if SEARCH_FILE_EXT == '*':
                pass  # 搜索所有文件
            elif SEARCH_FILE_EXT == '' and '.' in file_name:
                continue  # 跳过带后缀的文件
            elif SEARCH_FILE_EXT != '' and SEARCH_FILE_EXT is not None and not file_name.lower().endswith(
                    SEARCH_FILE_EXT.lower()):
                continue  # 跳过不匹配后缀的文件

            file_count += 1

            # 搜索目标字节序列
            offsets = search_in_file(file_path, target_bytes)

            if offsets:
                # 检查额外匹配条件
                exact_match, fuzzy_stars = check_extra_match(file_size, offsets, start_offset, size_min, size_max)

                # 计算相对路径，让日志更简洁
                try:
                    rel_path = file_path.relative_to(search_dir)
                except ValueError:
                    rel_path = file_path

                offset_strs = [hex(off) for off in offsets]

                if SEARCH_MODE == 'exact':
                    if exact_match:
                        match_count += 1
                        logger.info(f"[EXACT MATCH] {rel_path} (Size: {hex(file_size)})")
                        logger.debug(f" └── Offset(Hex): {', '.join(offset_strs)}")

                elif SEARCH_MODE == 'fuzzy':
                    match_count += 1
                    # 存储结果，等待排序后统一输出
                    fuzzy_results.append((fuzzy_stars, rel_path, offset_strs, file_size))

    # 4. 结果输出
    if SEARCH_MODE == 'fuzzy':
        # 按照星级倒序排序 (星级高的排前面)
        fuzzy_results.sort(key=lambda x: x[0], reverse=True)

        for stars, rel_path, offset_strs, file_size in fuzzy_results:
            star_str = '*' * stars
            logger.info(f"[FUZZY MATCH] {star_str:<3} {rel_path} (Size: {hex(file_size)})")
            logger.debug(f" └── Offset(Hex): {', '.join(offset_strs)}")

    logger.info("-" * 30)
    logger.info(f"搜索完成: 扫描了 {file_count} 个文件，在 {match_count} 个文件中找到目标。")


if __name__ == '__main__':
    main()