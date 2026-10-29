"""Validate legacy BLE AD structures using the Python standard library."""
import hashlib
import json
import re
from pathlib import Path


class PayloadError(ValueError):
    pass


def decode_hex(value, field):
    if not isinstance(value, str):
        raise PayloadError(f"{field} must be a hexadecimal string.")
    compact = re.sub(r"\s+", "", value)
    if len(compact) % 2 or re.search(r"[^0-9a-fA-F]", compact):
        raise PayloadError(f"{field} contains invalid hex or an incomplete byte.")
    return bytes.fromhex(compact)


def parse_ad(data, *, scan_response=False):
    if len(data) > 31:
        raise PayloadError("ADV and SCAN_RSP each have a 31-byte capacity.")
    blocks = []
    offset = 0
    flags_seen = False
    while offset < len(data):
        length = data[offset]
        if length == 0:
            raise PayloadError("Remove trailing zero padding; each AD structure requires a type byte.")
        end = offset + 1 + length
        if end > len(data):
            raise PayloadError(f"AD length at offset {offset} exceeds the buffer.")
        kind = data[offset + 1]
        body = data[offset + 2:end]
        if kind == 1:
            if scan_response:
                raise PayloadError("Place Flags (0x01) in ADV.")
            if len(body) != 1 or flags_seen:
                raise PayloadError("Flags requires exactly one data byte and a single occurrence.")
            flags_seen = True
        service_uuid_bytes = {0x16: 2, 0x20: 4, 0x21: 16}.get(kind)
        if service_uuid_bytes and len(body) < service_uuid_bytes:
            raise PayloadError("Service Data requires a complete UUID.")
        if kind == 0xFF and len(body) < 2:
            raise PayloadError("Manufacturer Data requires a two-byte Company ID.")
        if kind in (0x08, 0x09):
            try:
                body.decode("utf-8")
            except UnicodeDecodeError as error:
                raise PayloadError("The advertising name must be valid UTF-8.") from error
        blocks.append({"offset": offset, "type": f"0x{kind:02X}",
                       "dataHex": body.hex().upper()})
        offset = end
    return blocks


def normalize(config):
    if not isinstance(config, dict):
        raise PayloadError("Configuration must be a JSON object.")
    allowed = {"name", "description", "advertisingDataHex", "scanResponseDataHex"}
    unknown = set(config) - allowed
    if unknown:
        raise PayloadError("Unknown configuration fields: " + ", ".join(sorted(unknown)))
    for field in ("name", "description"):
        if field in config and not isinstance(config[field], str):
            raise PayloadError(f"{field} must be a string.")
    if "advertisingDataHex" not in config or "scanResponseDataHex" not in config:
        raise PayloadError("Provide both advertisingDataHex and scanResponseDataHex.")
    adv = decode_hex(config["advertisingDataHex"], "advertisingDataHex")
    rsp = decode_hex(config["scanResponseDataHex"], "scanResponseDataHex")
    if not adv:
        raise PayloadError("ADV requires at least one AD structure.")
    blocks = parse_ad(adv) + parse_ad(rsp, scan_response=True)
    full_names = [bytes.fromhex(b["dataHex"]).decode("utf-8")
                  for b in blocks if b["type"] == "0x09"]
    if len(full_names) > 1:
        raise PayloadError("Provide one Complete Local Name.")
    # 'name' is a label that must agree with the bytes when a complete name exists.
    if full_names and config.get("name") and config["name"] != full_names[0]:
        raise PayloadError("name differs from the Complete Local Name bytes. Update both fields.")
    result = {"name": config.get("name", full_names[0] if full_names else "Raw BLE"),
              "description": config.get("description", ""),
              "advertisingDataHex": adv.hex().upper(),
              "scanResponseDataHex": rsp.hex().upper()}
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    result["payloadSHA256"] = hashlib.sha256(canonical).hexdigest()
    result["advertisingBytes"] = len(adv)
    result["scanResponseBytes"] = len(rsp)
    return result


def load_config(path):
    try:
        return normalize(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as error:
        raise PayloadError(f"Reading the configuration failed: {error}") from error
