def cstring_to_key(s: str, ignore_case: bool = False) -> int:
    """
    完全基于提供的 ARM 汇编复现的字符串哈希函数。

    Args:
        s (str): 输入字符串。
        ignore_case (bool): 如果为 True，则启用不区分大小写模式 (对应汇编中 R1 != 0)。
                            如果为 False，则为区分大小写模式 (对应汇编中 R1 == 0)。

    Returns:
        int: 32位无符号哈希值 (DWORD)。
    """

    # 1. 初始化哈希值为字符串长度
    # 汇编中，R0 最初被 _strlen 设置为长度，并作为第一次哈希运算的初始累加器。
    current_hash = len(s)

    for char in s:
        # 获取字符的 ASCII 码 (0-255)
        c_val = ord(char) & 0xFF

        # --- 模式 A: 不区分大小写逻辑 (当 R1 != 0 时) ---
        # 对应汇编:
        # SUB R9, R3, #0x41  ('A')
        # CMP R9, #0x19
        # ADDLS R3, R3, #0x20 ('a' - 'A')
        # 这段逻辑仅将 'A'-'Z' 转换为 'a'-'z'。
        if ignore_case:
            if 0x41 <= c_val <= 0x5A:  # 如果是 'A' 到 'Z'
                c_val += 0x20

        # --- 模拟 LDRSB (加载带符号字节) ---
        # 汇编使用了 LDRSB，这意味着 >= 0x80 的字节会被符号扩展为 32 位负数。
        # 例如 0x80 会变成 0xFFFFFF80。
        # 如果你的应用场景只涉及标准 ASCII (0-127)，这一步不会有影响。
        if c_val >= 0x80:
            c_val |= 0xFFFFFF00

        # --- 核心哈希运算 ---
        # 对应汇编: EOR R0, R3, R0, ROR#28
        # 公式: NewHash = Char ^ (CurrentHash ROR 28)
        # ROR 28 (循环右移28位) 在 32 位下等同于 ROL 4 (循环左移4位)

        # 模拟 32 位 ROR 28:
        rotated = ((current_hash >> 28) | (current_hash << 4)) & 0xFFFFFFFF

        # 执行异或 (EOR)
        current_hash = rotated ^ c_val

        # 确保结果保持为 32 位无符号整数
        current_hash &= 0xFFFFFFFF

    return current_hash


# =========================================
# 测试用例
# =========================================
if __name__ == '__main__':
    # 测试 1: 区分大小写 (R1=0)
    str1 = "pack1-en-leads"
    hash1 = cstring_to_key(str1, ignore_case=False)
    print(f"'{str1}' (Case Sensitive)   -> 0x{hash1:08X}")

    # 测试 2: 不区分大小写 (R1=1)
    str2 = "pack1-en-leads"
    hash2 = cstring_to_key(str2, ignore_case=True)
    print(f"'{str2}' (Case Insensitive) -> 0x{hash2:08X}")

    # 验证不区分大小写模式下，两者结果是否相同
    # hash1_nocase = cstring_to_key(str1, ignore_case=True)
    # print(f"'{str1}' (Case Insensitive) -> 0x{hash1_nocase:08X}")
    # assert hash2 == hash1_nocase
    # print("验证成功: 在忽略大小写模式下，'FileName.txt' 与 'FILENAME.TXT' 哈希值相同。")