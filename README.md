# 网易 UU 远程 AMD 核显解码适配

本工具调整 UU 解码器的显卡适配器排序，让 AMD 显卡优先参与 DXVA 解码。适配于网易 UU 4.40.1.2090，运行环境为 Windows 和 64 位 Python 3.10 或更新版本；已在 AMD Radeon 780M + NVIDIA RTX 4060 Laptop 上成功运行。

## 使用

先打开 UU，再在项目目录运行：

```powershell
python uu_gpu_patch.py
```

也可以用 `start.cmd` 启动并应用补丁。要由工具启动 UU 并应用补丁，运行：

```powershell
python uu_gpu_patch.py --launch
```

自定义 UU 安装路径：

```powershell
python uu_gpu_patch.py --launch --exe "D:\Apps\GameViewer\GameViewer.exe"
```

应用补丁后，断开并重新连接 UU 会话，让新连接使用 AMD 解码。恢复时运行 `python uu_gpu_patch.py --undo`，也可以使用 `restore.cmd`。补丁保存在运行进程的内存中，进程退出后自动消失；之后通过 `start.cmd` 启动并应用即可。

## 工作方式

UU 的排序比较器将 NVIDIA 排在 AMD 前面。本工具调整比较器，让 AMD 排在 NVIDIA 前面，使新建的解码器优先使用 AMD 显卡的 Video Decode 引擎。在 Radeon 780M + RTX 4060 Laptop 上，应用补丁并重新连接后，Video Decode 使用 780M。

适配器枚举与比较器的技术说明见 [`docs/reversing.md`](docs/reversing.md)。

许可证：MIT
