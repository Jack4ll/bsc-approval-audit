"""Unit tests for the pure helpers in audit.py (no network)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from audit import (  # noqa: E402
    decode_symbol,
    encode_address,
    encode_uint,
    is_unlimited,
    load_pairs,
    verdict,
)


def abi_string(text: str) -> str:
    """Encode text the way Solidity returns a string from symbol()."""
    raw = text.encode()
    return ("0x" + (32).to_bytes(32, "big").hex()
            + len(raw).to_bytes(32, "big").hex()
            + raw.hex() + "00" * ((32 - len(raw) % 32) % 32))


class TestEncoding(unittest.TestCase):
    def test_encode_address(self):
        self.assertEqual(
            encode_address("0x0000000000000000000000000000000000000001"),
            "0" * 24 + "0000000000000000000000000000000000000001",
        )

    def test_encode_address_rejects_garbage(self):
        with self.assertRaises(ValueError):
            encode_address("not-an-address")

    def test_encode_uint(self):
        self.assertEqual(encode_uint(0), "0" * 64)
        self.assertEqual(encode_uint(2487), "0" * 61 + "9b7")
        with self.assertRaises(ValueError):
            encode_uint(-1)


class TestDecodeSymbol(unittest.TestCase):
    def test_abi_string(self):
        self.assertEqual(decode_symbol(abi_string("POKECHAIN")),
                         "POKECHAIN")
        self.assertEqual(decode_symbol(abi_string("LOOP")), "LOOP")

    def test_bytes32(self):
        self.assertEqual(
            decode_symbol("0x" + "4c4f4f50" + "00" * 28), "LOOP")

    def test_garbage_returns_none(self):
        self.assertIsNone(decode_symbol("0x"))
        self.assertIsNone(decode_symbol("0x" + "ff" * 32))


class TestLoadPairs(unittest.TestCase):
    def test_parses_comments_and_blanks(self):
        text = (
            "# a comment\n"
            "\n"
            "0x4EF929aF00cB93993c3D01834C4DA79200d31e32,"
            "0x3399E3AC0D6aA973a00D47Ff52072906841ee1a7,erc721\n"
            "0x20d1f12ef71d5e07ea4fb7fc2d6a200b0eb71420,"
            "0x3399E3AC0D6aA973a00D47Ff52072906841ee1a7,erc20\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".txt",
                                        delete=False) as fh:
            fh.write(text)
            path = fh.name
        pairs = load_pairs(path)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(pairs[0]["kind"], "erc721")
        self.assertEqual(pairs[1]["kind"], "erc20")
        self.assertEqual(pairs[0]["token"],
                         "0x4ef929af00cb93993c3d01834c4da79200d31e32")

    def test_bad_line_raises(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt",
                                        delete=False) as fh:
            fh.write("0x1234,0x5678,wrongkind\n")
            path = fh.name
        with self.assertRaises(ValueError):
            load_pairs(path)


class TestVerdict(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(verdict([]), "CLEAN — no live approvals")

    def test_live(self):
        live = [{"unlimited": False}, {"unlimited": True}]
        result = verdict(live)
        self.assertIn("2 live approval(s)", result)
        self.assertIn("1 UNLIMITED", result)

    def test_is_unlimited(self):
        self.assertTrue(is_unlimited((1 << 256) - 1))
        self.assertFalse(is_unlimited(1000))
        self.assertFalse(is_unlimited(None))


if __name__ == "__main__":
    unittest.main()
