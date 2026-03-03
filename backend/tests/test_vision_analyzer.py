"""Tests for vision_analyzer module (#281)."""


class TestCompressImage:
    def test_compress_small_png(self):
        from vision_analyzer import compress_image
        # Create a minimal valid PNG (1x1 red pixel)
        import struct
        import zlib
        def _make_png():
            sig = b'\x89PNG\r\n\x1a\n'
            ihdr_data = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
            ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data).to_bytes(4, 'big')
            ihdr = struct.pack('>I', 13) + b'IHDR' + ihdr_data + ihdr_crc
            raw = b'\x00\xff\x00\x00'
            idat_data = zlib.compress(raw)
            idat_crc = zlib.crc32(b'IDAT' + idat_data).to_bytes(4, 'big')
            idat = struct.pack('>I', len(idat_data)) + b'IDAT' + idat_data + idat_crc
            iend_crc = zlib.crc32(b'IEND').to_bytes(4, 'big')
            iend = struct.pack('>I', 0) + b'IEND' + iend_crc
            return sig + ihdr + idat + iend
        png = _make_png()
        result, content_type, w, h = compress_image(png, "image/png")
        assert isinstance(result, bytes)
        assert len(result) > 0
        assert w >= 1
        assert h >= 1
