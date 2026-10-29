"""Exercise PID-bound permission writes against a memory model."""
from pathlib import Path
import sys
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import session_gate


class Error:
    def __init__(self):
        self.ok = True

    def Success(self):
        return self.ok

    def __str__(self):
        return "simulated memory failure"


class Memory:
    base = 0x1000

    def __init__(self, pid=123, flag=0):
        self.data = bytearray(0xC0)
        self.data[0x28:0x2C] = pid.to_bytes(4, "little")
        self.data[0xBF] = flag
        self.writes = []
        self.read_failure = self.write_failure = self.stuck = False

    def ReadMemory(self, address, count, error):
        offset = address - self.base
        if self.read_failure or offset < 0 or offset + count > len(self.data):
            error.ok = False
            return b""
        return bytes(self.data[offset:offset + count])

    def WriteMemory(self, address, data, error):
        self.writes.append((address, data))
        if self.write_failure:
            error.ok = False
            return 0
        offset = address - self.base
        if not self.stuck:
            self.data[offset:offset + len(data)] = data
        return len(data)


class GatePolicyTests(unittest.TestCase):
    def setUp(self):
        self.original_lldb = session_gate.lldb
        session_gate.lldb = types.SimpleNamespace(SBError=Error)

    def tearDown(self):
        session_gate.lldb = self.original_lldb

    def grant(self, memory, pid=123):
        return session_gate.grant_session(memory, memory.base, pid, 0x28, 0xBF)

    def test_one_byte_and_all_other_bytes_unchanged(self):
        memory = Memory()
        before = bytes(memory.data)
        outcome = self.grant(memory)
        changed = [i for i, (a, b) in enumerate(zip(before, memory.data)) if a != b]
        self.assertEqual(changed, [0xBF])
        self.assertEqual(memory.writes, [(memory.base + 0xBF, b"\x01")])
        self.assertEqual(outcome["changedByteCount"], 1)

    def test_rejects_other_client(self):
        memory = Memory()
        before = bytes(memory.data)
        self.assertIsNone(self.grant(memory, pid=124))
        self.assertEqual(bytes(memory.data), before)
        self.assertEqual(memory.writes, [])

    def test_rejects_unexpected_flag(self):
        memory = Memory(flag=2)
        with self.assertRaises(RuntimeError):
            self.grant(memory)
        self.assertEqual(memory.writes, [])

    def test_already_allowed_records_zero_changed_bytes(self):
        memory = Memory(flag=1)
        outcome = self.grant(memory)
        self.assertEqual(outcome["changedByteCount"], 0)
        self.assertEqual(outcome["writtenByteCount"], 1)

    def test_rejects_failed_read(self):
        memory = Memory()
        memory.read_failure = True
        with self.assertRaises(RuntimeError):
            self.grant(memory)
        self.assertEqual(memory.writes, [])

    def test_raises_on_failed_write(self):
        memory = Memory()
        memory.write_failure = True
        with self.assertRaises(RuntimeError):
            self.grant(memory)

    def test_raises_on_readback_failure(self):
        memory = Memory()
        memory.stuck = True
        with self.assertRaises(RuntimeError):
            self.grant(memory)

    def test_rejects_invalid_pid(self):
        memory = Memory()
        with self.assertRaises(RuntimeError):
            self.grant(memory, pid=1)
        self.assertEqual(memory.writes, [])


if __name__ == "__main__":
    unittest.main()
