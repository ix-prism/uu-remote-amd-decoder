# 网易 UU 远程 AMD 核显解码适配

这个项目提供一个轻量 Python 工具，在运行中的网易 UU 远程进程里调整解码器的适配器排序，让 AMD 显卡优先参与 DXVA 解码。适配器选择改变后，UU 新建的解码器可以使用 AMD 显卡的 Video Decode 引擎。

## 支持范围

| 项目 | 支持情况 |
| --- | --- |
| UU 版本 | 4.40.1.2090 |
| `streamer.dll` SHA-256 | `C6A5429C076F4A564EC2CA73E7476D2429F017005215AEE85C2BFAE13AA9D212` |
| 系统与 Python | Windows；64 位 Python 3.10 或更新版本，仅使用标准库 |
| 实机验证 | AMD Radeon 780M + NVIDIA RTX 4060 Laptop |

工具会同时核对目标版本的哈希和补丁位置的原始字节。版本或字节不匹配时不会写入。当前仅适配上表中的官方构建；其他 UU 版本和 AMD 显卡组合尚未验证。

这项适配按 VendorId 排序，目标是让 AMD 优先。Intel 核显不会因此成为优先解码器；如果机器上有多块 AMD 显卡，补丁也无法从 VendorId 判断哪块是核显。

## 使用

先打开 UU，再从项目目录打开终端：

```powershell
python uu_gpu_patch.py
```

默认对正在运行的 `GameViewer.exe` 应用补丁。应用后请断开并重新连接 UU 会话，让它创建新的解码器。

其他操作：

```powershell
python uu_gpu_patch.py --launch
python uu_gpu_patch.py --launch --exe "C:\path\to\GameViewer.exe"
python uu_gpu_patch.py --undo
```

`--launch` 启动 UU 并应用补丁；`--launch --exe` 指定自定义安装路径；`--undo` 撤销正在运行进程中的补丁。也可以使用项目内的 `start.cmd` 应用补丁，或用 `restore.cmd` 撤销。

## 实测结果

在 Radeon 780M + RTX 4060 Laptop 上，修改前 UU 3D 进程运行在核显，但 Video Decode 位于 RTX 4060。修改后仅断开并重连，780M 的 Video Codec 0 开始解码，RTX Video Decode 上下文消失。独立调用 `streamer.dll` 的适配器枚举函数时，顺序从 NVIDIA → AMD → 软件适配器变为 AMD → NVIDIA → 软件适配器。

这项验证仅覆盖上述设备和 UU 构建。

## 工作方式

补丁只作用于运行进程的内存，不修改安装目录里的 DLL。进程退出后补丁随之消失；下次启动时再通过项目启动器应用。原厂 DLL 文件保持原有签名。

有关适配器枚举、比较器和字节改动的说明见 [`docs/reversing.md`](docs/reversing.md)。

## 源码与分发

项目不包含网易 UU 的 DLL。使用者需在本机安装受支持的官方版本。项目源码使用 MIT 许可证。

## 作者

ix-prism