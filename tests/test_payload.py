import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from payload import PayloadError, normalize, parse_ad


class PayloadTests(unittest.TestCase):
    def example(self):
        return json.loads((ROOT / "examples/ibeacon-service-data.json").read_text())

    def test_documented_example_fields(self):
        value = normalize(self.example())
        self.assertEqual(value["advertisingBytes"], 30)
        self.assertEqual(value["scanResponseBytes"], 19)
        primary = bytes.fromhex(value["advertisingDataHex"])
        self.assertEqual(primary[9:25].hex(), "1234567812345678123456789abcdef0")
        self.assertEqual(int.from_bytes(primary[25:27], "big"), 1)
        self.assertEqual(int.from_bytes(primary[27:29], "big"), 1)
        response = parse_ad(bytes.fromhex(value["scanResponseDataHex"]), scan_response=True)
        self.assertEqual(response[0]["dataHex"], "F0FF01020304")
        self.assertEqual(bytes.fromhex(response[1]["dataHex"]).decode(), "RawBLELab")

    def test_second_example(self):
        normalize(json.loads((ROOT / "examples/service-data.json").read_text()))

    def test_31_byte_boundary(self):
        value = normalize({"advertisingDataHex": "1EFF" + "00" * 29,
                           "scanResponseDataHex": ""})
        self.assertEqual(value["advertisingBytes"], 31)
        self.assertEqual(value["scanResponseBytes"], 0)

    def test_overflow_rejected(self):
        with self.assertRaises(PayloadError):
            normalize({"advertisingDataHex": "1FFF" + "00" * 30, "scanResponseDataHex": ""})

    def test_incomplete_structure_rejected(self):
        with self.assertRaises(PayloadError):
            parse_ad(bytes.fromhex("05160102"))

    def test_zero_padding_rejected(self):
        with self.assertRaises(PayloadError):
            parse_ad(bytes.fromhex("02010600"))

    def test_scan_response_flags_rejected(self):
        with self.assertRaises(PayloadError):
            parse_ad(bytes.fromhex("020106"), scan_response=True)

    def test_missing_service_uuid_rejected(self):
        for value in ("0116", "031601", "022000", "022100"):
            with self.subTest(value=value), self.assertRaises(PayloadError):
                parse_ad(bytes.fromhex(value))

    def test_missing_company_id_rejected(self):
        with self.assertRaises(PayloadError):
            parse_ad(bytes.fromhex("02FF00"))

    def test_misleading_name_rejected(self):
        value = self.example()
        value["name"] = "Other name"
        with self.assertRaises(PayloadError):
            normalize(value)

    def test_bad_hex_and_unknown_fields_rejected(self):
        for field, data in (("advertisingDataHex", "0"), ("advertisingDataHex", "ZZ"),
                            ("advertisingDataHex", None), ("unexpected", 1)):
            value = self.example()
            value[field] = data
            with self.subTest(field=field, data=data), self.assertRaises(PayloadError):
                normalize(value)

    def test_whitespace_and_case_normalized(self):
        value = self.example()
        expected = normalize(value)
        value["advertisingDataHex"] = " \n".join(value["advertisingDataHex"].lower()[i:i+2]
                                                   for i in range(0, len(value["advertisingDataHex"]), 2))
        self.assertEqual(normalize(value), expected)

    def test_payload_change_changes_fingerprint(self):
        value = self.example()
        before = normalize(value)["payloadSHA256"]
        value["scanResponseDataHex"] = value["scanResponseDataHex"].replace("01020304", "01020305")
        self.assertNotEqual(normalize(value)["payloadSHA256"], before)


if __name__ == "__main__":
    unittest.main()
