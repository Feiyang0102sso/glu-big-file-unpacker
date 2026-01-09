# utils_file_type.py

class FileTypeUtils:
    @staticmethod
    def guess_extension(data: bytes, group_hash: int = None) -> str:
        """
        add extension to the extracted files
        """
        # 1. the one file in this group can be seen as pure text file
        if group_hash == 0xf686aadc:
            return ".txt"

        if not data:
            return ".bin"

        # 2. currently only have .png .wav
        if data.startswith(b'\x89PNG'):
            return ".png"
        if data.startswith(b'RIFF') and data[8:12] == b'WAVE':
            return ".wav"

        # 3. others are all seen as .bin
        return ".bin"