"""Prefer AMD in UU Remote's D3D11 decoder allocator list (Windows x64)."""
from __future__ import annotations

import argparse
import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


@dataclass(frozen=True)
class PatchProfile:
    version: str
    sha256: str
    rva: int
    before: bytes
    after: bytes


PROFILE = PatchProfile(
    version="4.40.1.2090",
    sha256="c6a5429c076f4a564ec2ca73e7476d2429f017005215aee85c2bfae13aa9d212",
    rva=0x99B4F3,
    before=bytes.fromhex(
        "8b8c2420010000e8116e01008b8c24500200008bd8e8036e01003bc30f9cc0"
    ),
    after=bytes.fromhex("8b8424500200003b8424200100000f92c0") + b"\x90" * 14,
)


class PatchError(RuntimeError):
    pass


class ModuleNotReady(PatchError):
    pass


def patch_state(data: bytes) -> str:
    if data == PROFILE.before:
        return "original"
    if data == PROFILE.after:
        return "applied"
    raise PatchError("运行时代码与此版本的原始代码或补丁不匹配，已停止。")


def verify_dll(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != PROFILE.sha256:
        raise PatchError(
            "请更新此工具以适配当前 UU 版本。"
        )
    return digest


class WindowsAPI:
    def __init__(self):
        if sys.platform != "win32" or C.sizeof(C.c_void_p) != 8:
            raise PatchError("需要 Windows 和 64 位 Python 3.10 或更新版本。")
        self.k = C.WinDLL("kernel32", use_last_error=True)
        self.p = C.WinDLL("psapi", use_last_error=True)
        self.n = C.WinDLL("ntdll")
        bindings = [
            (self.k.OpenProcess, [W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
            (self.k.CloseHandle, [W.HANDLE], W.BOOL),
            (self.k.QueryFullProcessImageNameW,
             [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)], W.BOOL),
            (self.k.ReadProcessMemory,
             [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)], W.BOOL),
            (self.k.WriteProcessMemory,
             [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)], W.BOOL),
            (self.k.VirtualProtectEx,
             [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, C.POINTER(W.DWORD)], W.BOOL),
            (self.k.FlushInstructionCache, [W.HANDLE, C.c_void_p, C.c_size_t], W.BOOL),
            (self.p.EnumProcesses, [C.c_void_p, W.DWORD, C.POINTER(W.DWORD)], W.BOOL),
            (self.p.EnumProcessModulesEx,
             [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), W.DWORD], W.BOOL),
            (self.p.GetModuleFileNameExW,
             [W.HANDLE, C.c_void_p, W.LPWSTR, W.DWORD], W.DWORD),
            (self.n.NtSuspendProcess, [W.HANDLE], C.c_long),
            (self.n.NtResumeProcess, [W.HANDLE], C.c_long),
        ]
        for fn, argtypes, restype in bindings:
            fn.argtypes, fn.restype = argtypes, restype

    @staticmethod
    def check(ok):
        if not ok:
            raise C.WinError(C.get_last_error())

    def open(self, pid: int, modify: bool = False):
        access = 0x400 | 0x10
        if modify:
            access |= 0x20 | 0x8 | 0x800
        handle = self.k.OpenProcess(access, False, pid)
        self.check(handle)
        return handle

    def executable(self, handle) -> Path:
        name = C.create_unicode_buffer(32768)
        size = W.DWORD(len(name))
        self.check(self.k.QueryFullProcessImageNameW(handle, 0, name, C.byref(size)))
        return Path(name.value)

    def find_processes(self) -> list[int]:
        ids = (W.DWORD * 16384)()
        needed = W.DWORD()
        self.check(self.p.EnumProcesses(ids, C.sizeof(ids), C.byref(needed)))
        result = []
        for pid in ids[:needed.value // C.sizeof(W.DWORD)]:
            handle = self.k.OpenProcess(0x1000, False, pid)
            if not handle:
                continue
            try:
                try:
                    if self.executable(handle).name.casefold() == "gameviewer.exe":
                        result.append(pid)
                except OSError:
                    continue
            finally:
                self.k.CloseHandle(handle)
        return result

    def module(self, handle) -> tuple[int, Path]:
        modules = (C.c_void_p * 2048)()
        needed = W.DWORD()
        self.check(self.p.EnumProcessModulesEx(
            handle, modules, C.sizeof(modules), C.byref(needed), 3
        ))
        if needed.value > C.sizeof(modules):
            raise PatchError("进程模块列表超过缓冲区，已停止。")
        matches = []
        for base in modules[:needed.value // C.sizeof(C.c_void_p)]:
            name = C.create_unicode_buffer(32768)
            if self.p.GetModuleFileNameExW(handle, base, name, len(name)):
                path = Path(name.value)
                if path.name.casefold() == "streamer.dll":
                    matches.append((base, path))
        if not matches:
            raise ModuleNotReady("UU 尚未加载 streamer.dll。")
        if len(matches) != 1:
            raise PatchError("进程加载了多个 streamer.dll，已停止。")
        return matches[0]

    def read(self, handle, address: int, size: int) -> bytes:
        data = C.create_string_buffer(size)
        count = C.c_size_t()
        self.check(self.k.ReadProcessMemory(handle, address, data, size, C.byref(count)))
        if count.value != size:
            raise PatchError("读取的进程内存长度不完整。")
        return data.raw

    def write(self, handle, address: int, data: bytes):
        count = C.c_size_t()
        self.check(self.k.WriteProcessMemory(
            handle, address, data, len(data), C.byref(count)
        ))
        if count.value != len(data):
            raise PatchError("写入的进程内存长度不完整。")
        self.check(self.k.FlushInstructionCache(handle, address, len(data)))


def inspect(api: WindowsAPI, pid: int) -> dict:
    handle = api.open(pid)
    try:
        exe = api.executable(handle)
        if exe.name.casefold() != "gameviewer.exe":
            raise PatchError("目标进程不是 GameViewer.exe。")
        base, path = api.module(handle)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        supported = digest == PROFILE.sha256
        state = patch_state(api.read(handle, base + PROFILE.rva, len(PROFILE.before))) if supported else "unsupported"
        return {"pid": pid, "executable": str(exe), "dll": str(path),
                "supported": supported, "state": state}
    finally:
        api.k.CloseHandle(handle)


def apply(api: WindowsAPI, pid: int, undo: bool = False) -> dict:
    handle = api.open(pid, modify=True)
    suspended = False
    try:
        if api.executable(handle).name.casefold() != "gameviewer.exe":
            raise PatchError("目标进程不是 GameViewer.exe。")
        base, path = api.module(handle)
        verify_dll(path)
        address = base + PROFILE.rva
        current = api.read(handle, address, len(PROFILE.before))
        state = patch_state(current)
        desired = PROFILE.before if undo else PROFILE.after
        if current == desired:
            return {"pid": pid, "status": "already-restored" if undo else "already-applied"}
        status = api.n.NtSuspendProcess(handle)
        if status < 0:
            raise PatchError(f"暂停 UU 进程失败：NTSTATUS {status & 0xffffffff:#x}")
        suspended = True
        # Validate again with other threads suspended before making the local change.
        if api.read(handle, address, len(current)) != current:
            raise PatchError("暂停进程前后代码发生变化，已停止。")
        old = W.DWORD()
        api.check(api.k.VirtualProtectEx(handle, address, len(desired), 0x40, C.byref(old)))
        try:
            try:
                api.write(handle, address, desired)
                if api.read(handle, address, len(desired)) != desired:
                    raise PatchError("补丁写入后的回读校验失败。")
            except Exception as error:
                try:
                    api.write(handle, address, current)
                except Exception as rollback_error:
                    raise PatchError(
                        "补丁操作失败，且恢复原字节失败；请完全退出并重开 UU。"
                        f"原始错误：{error}；恢复错误：{rollback_error}"
                    ) from rollback_error
                raise
        finally:
            unused = W.DWORD()
            api.check(api.k.VirtualProtectEx(
                handle, address, len(desired), old.value, C.byref(unused)
            ))
        return {"pid": pid, "previous_state": state,
                "status": "restored" if undo else "applied"}
    finally:
        try:
            if suspended:
                status = api.n.NtResumeProcess(handle)
                if status < 0:
                    raise PatchError(f"恢复 UU 进程运行失败：NTSTATUS {status & 0xffffffff:#x}")
        finally:
            api.k.CloseHandle(handle)


def launcher_path(custom: str | None) -> Path:
    if custom:
        path = Path(custom).expanduser().resolve()
        if path.is_file() and path.name.casefold() == "gameviewer.exe":
            return path
        raise PatchError("--exe 需要指向已安装的 GameViewer.exe。")
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        parent = os.environ.get(variable)
        if parent:
            for relative in ("Netease/GameViewer/GameViewer.exe", "Netease/GameViewer/bin/GameViewer.exe"):
                path = Path(parent) / relative
                if path.is_file():
                    return path
    raise PatchError("未找到 UU。请通过 --exe 指定 GameViewer.exe 的路径。")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--launch", action="store_true", help="启动 UU 并应用核显优先补丁")
    modes.add_argument("--undo", action="store_true", help="还原运行中 UU 的原始选卡逻辑")
    modes.add_argument("--inspect", action="store_true", help="只读查看版本和补丁状态")
    parser.add_argument("--pid", type=int, help="指定 GameViewer.exe 的 PID")
    parser.add_argument("--exe", help="配合 --launch 指定自定义 UU 安装路径")
    args = parser.parse_args(argv)
    if args.pid is not None and (args.pid <= 0 or args.launch):
        parser.error("--pid 应为正整数，且不能与 --launch 同用。")
    if args.exe and not args.launch:
        parser.error("--exe 需要与 --launch 同用。")
    api = WindowsAPI()
    ids = [args.pid] if args.pid else api.find_processes()
    if args.launch:
        if not ids:
            exe = launcher_path(args.exe)
            subprocess.Popen([str(exe)], cwd=str(exe.parent))
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            ids = api.find_processes()
            if ids:
                try:
                    results = [apply(api, pid) for pid in ids]
                    break
                except ModuleNotReady:
                    pass
            time.sleep(0.2)
        else:
            raise PatchError("未找到已加载解码模块的 UU 进程，请先打开 UU 后再运行。")
    elif not ids:
        if args.undo:
            results = [{"status": "no-running-process"}]
        else:
            raise PatchError("请先打开 UU，或者使用 --launch。")
    else:
        results = [inspect(api, pid) if args.inspect else apply(api, pid, args.undo) for pid in ids]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    if not args.inspect:
        print("已有远程连接请断开后重连。完全退出 UU 后本次内存修改即失效。")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except (PatchError, OSError) as error:
        print(f"错误：{error}", file=sys.stderr)
        raise SystemExit(1)
