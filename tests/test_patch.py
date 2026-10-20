import tempfile
import unittest
from pathlib import Path
from unittest import mock

import uu_gpu_patch as patcher


class FakeKernel32:
    def __init__(self, api):
        self.api = api

    def VirtualProtectEx(self, handle, address, size, protection, old_pointer):
        old_pointer._obj.value = self.api.protection
        self.api.protection = protection
        self.api.protection_changes.append(protection)
        return 1

    def CloseHandle(self, handle):
        self.api.closed_handles += 1
        return 1


class FakeNtdll:
    def __init__(self, api):
        self.api = api

    def NtSuspendProcess(self, handle):
        self.api.suspend_calls += 1
        self.api.suspended = True
        return 0

    def NtResumeProcess(self, handle):
        self.api.resume_calls += 1
        self.api.suspended = False
        return 0


class FakeAPI:
    def __init__(self, memory, dll_path):
        self.memory = memory
        self.dll_path = dll_path
        self.protection = 0x20  # PAGE_EXECUTE_READ
        self.protection_changes = []
        self.writes = []
        self.suspend_calls = 0
        self.resume_calls = 0
        self.closed_handles = 0
        self.suspended = False
        self.corrupt_next_read = False
        self.k = FakeKernel32(self)
        self.n = FakeNtdll(self)

    @staticmethod
    def check(ok):
        if not ok:
            raise OSError("fake Windows API failure")

    def open(self, pid, modify=False):
        return "fake-handle"

    def executable(self, handle):
        return Path("GameViewer.exe")

    def module(self, handle):
        return 0x100000, self.dll_path

    def read(self, handle, address, size):
        if self.corrupt_next_read:
            self.corrupt_next_read = False
            return b"\xcc" * size
        return self.memory[:size]

    def write(self, handle, address, data):
        self.writes.append(data)
        self.memory = data
        if len(self.writes) == 1:
            self.corrupt_next_read = True


class PatchTests(unittest.TestCase):
    def test_apply_rejects_unsupported_dll_hash_before_modifying_process(self):
        with tempfile.TemporaryDirectory() as directory:
            dll = Path(directory) / "streamer.dll"
            dll.write_bytes(b"an unsupported build")
            api = FakeAPI(patcher.PROFILE.before, dll)

            with self.assertRaises(patcher.PatchError):
                patcher.apply(api, 1234)

        self.assertEqual(api.writes, [])
        self.assertEqual(api.suspend_calls, 0)
        self.assertEqual(api.memory, patcher.PROFILE.before)
        self.assertEqual(api.closed_handles, 1)

    def test_apply_rejects_unknown_runtime_bytes_without_writing(self):
        unknown = b"\x00" * len(patcher.PROFILE.before)
        api = FakeAPI(unknown, Path("streamer.dll"))

        with mock.patch.object(patcher, "verify_dll", return_value="supported"):
            with self.assertRaises(patcher.PatchError):
                patcher.apply(api, 1234)

        self.assertEqual(api.writes, [])
        self.assertEqual(api.suspend_calls, 0)
        self.assertEqual(api.memory, unknown)
        self.assertEqual(api.closed_handles, 1)

    def test_apply_and_undo_are_idempotent(self):
        api = FakeAPI(patcher.PROFILE.after, Path("streamer.dll"))

        with mock.patch.object(patcher, "verify_dll", return_value="supported"):
            applied = patcher.apply(api, 1234)
            api.memory = patcher.PROFILE.before
            restored = patcher.apply(api, 1234, undo=True)

        self.assertEqual(applied["status"], "already-applied")
        self.assertEqual(restored["status"], "already-restored")
        self.assertEqual(api.writes, [])
        self.assertEqual(api.suspend_calls, 0)
        self.assertEqual(api.resume_calls, 0)
        self.assertEqual(api.closed_handles, 2)

    def test_failed_readback_restores_bytes_protection_and_thread_state(self):
        api = FakeAPI(patcher.PROFILE.before, Path("streamer.dll"))

        with mock.patch.object(patcher, "verify_dll", return_value="supported"):
            with self.assertRaisesRegex(patcher.PatchError, "回读校验失败"):
                patcher.apply(api, 1234)

        self.assertEqual(api.memory, patcher.PROFILE.before)
        self.assertEqual(api.writes, [patcher.PROFILE.after, patcher.PROFILE.before])
        self.assertEqual(api.protection, 0x20)
        self.assertEqual(api.protection_changes, [0x40, 0x20])
        self.assertFalse(api.suspended)
        self.assertEqual(api.suspend_calls, 1)
        self.assertEqual(api.resume_calls, 1)
        self.assertEqual(api.closed_handles, 1)


if __name__ == "__main__":
    unittest.main()
