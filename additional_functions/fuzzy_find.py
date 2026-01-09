import os
import struct
from config import ROOT_DIR

def find_map_files(directory):
    for filename in os.listdir(directory):
        if filename.endswith(".bin"):
            filepath = os.path.join(directory, filename)

            # 1. 检查文件大小
            file_size = os.path.getsize(filepath)
            if file_size < 5:
                continue

            with open(filepath, 'rb') as f:
                # 读取第一个字节（被代码忽略的那个）
                f.read(1)

                # 2. 读取宽度和高度
                # '<H' 表示小端序的无符号短整型 (16-bit)
                try:
                    width = struct.unpack('<H', f.read(2))[0]
                    height = struct.unpack('<H', f.read(2))[0]
                except struct.error:
                    continue  # 文件太小，读取失败

                # 4. 检查W和H是否合理
                if not (0 < width < 2048 and 0 < height < 2048):
                    continue

                # 5. 验证文件总大小
                expected_size = 5 + (width * height * 2)
                if file_size == expected_size:
                    print(f"找到可能的地图文件: {filename} (尺寸: {width}x{height})")

if __name__ == '__main__':
    find_map_files(ROOT_DIR / 'output240' / 'pack3_xga')
# 替换为你的游戏数据目录
# find_map_files(ROOT_DIR / 'output240' / 'pack3_xga')