import json
import struct
import tempfile
import unittest
from pathlib import Path

import pwarchive


class ArchiveTests(unittest.TestCase):
    def test_cipher_round_trip(self):
        data = bytes(range(64))
        encrypted = pwarchive.crypt_words(data, 0x12345678, 0xABCDEF01, 0x31415926)
        self.assertEqual(pwarchive.crypt_words(encrypted, 0x12345678, 0xABCDEF01, 0x31415926), data)

    def test_known_hashes(self):
        self.assertEqual(pwarchive.filename_hash("STAGEDAT.PDT"), 0x9645FA)
        self.assertEqual(pwarchive.filename_hash("SLOT.DAT"), 0x2ABA34)
        self.assertEqual(pwarchive.filename_hash("BRIEFING.DAT"), 0x76531D)

    def test_pc_resource_cipher_vector_and_round_trip(self):
        encrypted = bytes.fromhex(
            "d68defbbe7c3988c267312ab267850b7f120397f6b91051d5"
            "5c07c0a32bab879bd4de5db3edaad16"
        )
        expected = bytes.fromhex(
            "babe9ec7b1c141dfb9436ab00100300416005001cb9c4641"
            "4300000015000000160060042b005001"
        )
        decoded = pwarchive.crypt_pc_resource(encrypted, "002aba34.KEY")
        self.assertEqual(decoded, expected)
        self.assertEqual(pwarchive.crypt_pc_resource(decoded, "002aba34.KEY"), encrypted)

    def test_dlc_texture_classification(self):
        kind, description = pwarchive.classify_pc_resource(
            Path(r"J:\game\mgspw\ms0\EU\DLCTEX\ad1af1fb.PDT")
        )
        self.assertEqual(kind, "pc-resource")
        self.assertEqual(description, "DLC texture package")

    def test_xpr2_classification_and_extraction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "00000001.xpr"
            header_size, surface = 0x80, b"SURFACE!"
            decoded = bytearray(header_size + len(surface) + 4)
            decoded[:4] = b"XPR2"
            struct.pack_into(">III", decoded, 4, header_size, len(surface), 2)
            struct.pack_into(">4sIIIII", decoded, 0x10, b"TX2D", 0x40, 0x10, 0, 0, 0)
            struct.pack_into(">4sIIIII", decoded, 0x28, b"USER", 0x50, 0x08, 0, 0, 0)
            decoded[0x40:0x50] = b"texture-header!!"
            decoded[0x50:0x58] = b"fontdata"
            decoded[header_size:header_size + len(surface)] = surface
            decoded[-4:] = b"TAIL"
            source.write_bytes(pwarchive.crypt_pc_resource(bytes(decoded), source.name))
            self.assertEqual(pwarchive.classify_pc_resource(source)[0], "xpr")
            output = root / "out"
            pwarchive.extract_xpr2(source, output)
            self.assertEqual((output / "00000_TX2D.bin").read_bytes(), b"texture-header!!")
            self.assertEqual((output / "00001_USER.bin").read_bytes(), b"fontdata")
            self.assertEqual((output / "FontTexture.a8.bin").read_bytes(), surface)
            manifest = json.loads((output / pwarchive.MANIFEST).read_text(encoding="utf-8"))
            self.assertEqual(manifest["format"], "xpr2")
            self.assertEqual(manifest["trailing_size"], 4)

    def test_dar_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "sample.dar"
            folder = root / "out"
            folder.mkdir()
            (folder / pwarchive.MANIFEST).write_text(json.dumps({
                "format": "dar", "entries": [
                    {"index": 0, "name": "hello.bin", "file": "00000_hello.bin", "size": 3},
                    {"index": 1, "name": "world.txt", "file": "00001_world.txt", "size": 5},
                ]}), encoding="utf-8")
            (folder / "00000_hello.bin").write_bytes(b"abc")
            (folder / "00001_world.txt").write_bytes(b"12345")
            pwarchive.repack_dar(folder, source)
            extracted = root / "again"
            pwarchive.extract_dar(source, extracted)
            self.assertEqual((extracted / "00000_hello.bin").read_bytes(), b"abc")
            self.assertEqual((extracted / "00001_world.txt").read_bytes(), b"12345")

    def test_slot_page_contents_extract_and_edit(self):
        table = bytearray(struct.pack("<II", 3, 0))
        table += struct.pack("<IIII", 0x7F000002, 0, 0, 0)
        table += struct.pack("<IIII", 0x14123456, 0, 0, 0)
        table += struct.pack("<IIII", 0x7F000000, 0, 4, 0)
        payload = bytes(table) + b"\0" * (0x1000 - len(table)) + b"TXP!"
        parsed = pwarchive.parse_slot_contents(payload)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["extension"], "txp")
        self.assertEqual(parsed[0]["offset"], 0x1000)
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            entries = pwarchive.extract_slot_contents(payload, folder)
            path = folder / entries[0]["file"]
            self.assertEqual(path.read_bytes(), b"TXP!")
            path.write_bytes(b"NEW")
            rebuilt = pwarchive.apply_slot_content_edits(payload, folder)
            self.assertEqual(rebuilt[0x1000:0x1004], b"NEW\0")

    def test_general_simple_pdt_detection_and_extraction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "sample.pdt"
            decoded = bytearray(0x44)
            decoded[0] = 0x5A
            struct.pack_into("<H", decoded, 24, 1)
            struct.pack_into("<III", decoded, 40, 4, 0x12345678, 0x40)
            decoded[0x40:0x44] = b"FEL!"
            encoded = bytearray(decoded)
            for index in range(17, len(encoded)):
                encoded[index] ^= encoded[0]
            source.write_bytes(encoded)
            self.assertEqual(pwarchive.detect_pdt_variant(source), "simple-pdt")
            output = root / "out"
            pwarchive.extract_pdt(source, output)
            extracted = output / "00000_12345678.fel"
            self.assertEqual(extracted.read_bytes(), b"FEL!")

    def test_ogg_stream_range(self):
        page = bytearray(b"OggS" + b"\0" * 23)
        page[5] = 0x04
        page[26] = 1
        page += b"\x03abc"
        payload = b"wrapper" + bytes(page) + b"padding"
        self.assertEqual(pwarchive.find_ogg_stream(payload), (7, 38))

    def test_stage_filename_codes_and_cnf(self):
        code = pwarchive.stage_file_code("data.cnf")
        self.assertEqual(code >> 24, 0xF2)
        names = pwarchive.cnf_filenames(
            b".nocache\n.cache\n@cache0.qar\n?vram.vram\nscene.gcx\n"
        )
        self.assertEqual(names, ["cache0.qar", "vram.vram", "scene.gcx"])


if __name__ == "__main__":
    unittest.main()
