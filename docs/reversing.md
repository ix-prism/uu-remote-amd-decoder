# UU 解码选卡逻辑与补丁

分析版本：网易 UU 远程 4.40.1.2090，`streamer.dll`。

UU 会按固定的厂商顺序排列解码设备：NVIDIA 在前，AMD 在后。补丁调整这段比较逻辑，让 AMD 排在 NVIDIA 前面。Radeon 780M + RTX 4060 Laptop 已成功切换到 780M 解码。

下文地址均为 PE RVA，文件偏移另行标注。

## 调用路径

`VideoDecoderFactory::CreateVideoDecoder`（`0xCFDCD0`）按 H.264/H.265 建立候选解码器。DXVA 初始化构造 D3D11 allocator 列表，逐项检查设备、video context 和解码 profile，采用首个满足条件的候选。

| 位置 | 作用 |
| --- | --- |
| `0xD19170` | H.265 DXVA 初始化，默认以 flags `0x18` 调用 `0x99DC80` |
| `0xD28990` | H.264 DXVA 初始化，默认以 flags `0x18` 调用 `0x99DC80` |
| `0x99DC80` | 枚举 DXGI 适配器，建立 allocator 列表 |
| `0xD1953F` / `0xD28C9B` | 遍历 H.265 / H.264 候选并检查能力 |
| `0xD1A3F8` / `0xD29C95` | 保存选中的 allocator |

`0x99DC80` 使用 `DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE`（值为 `2`）枚举设备，随后交给比较器 `0x99B470` 重新排序。解码器使用的最终顺序由这个比较器决定。

## 厂商排序

比较器读取两个适配器的 `DXGI_ADAPTER_DESC.VendorId`，通过 `0x9B2310` 转成等级，再按等级升序排列：

| VendorId | 厂商 | 原始等级 |
| --- | --- | ---: |
| `0x10DE` | NVIDIA | 0 |
| `0x1002` | AMD | 1 |
| `0x8086` | Intel | 2 |
| 其他 | 其他适配器 | 5 |

这使 RTX 4060 排在 Radeon 780M 前面。补丁在比较器中直接按 VendorId 无符号升序排列，得到 AMD `0x1002` → NVIDIA `0x10DE` 的顺序。

## 补丁位置与字节

| 项目 | 值 |
| --- | --- |
| RVA | `0x99B4F3` |
| 文件偏移 | `0x99A8F3` |
| 长度 | 31 字节 |

原始字节：

```text
8B 8C 24 20 01 00 00 E8 11 6E 01 00 8B 8C 24 50 02 00 00
8B D8 E8 03 6E 01 00 3B C3 0F 9C C0
```

替换字节：

```text
8B 84 24 50 02 00 00 3B 84 24 20 01 00 00 0F 92 C0
90 90 90 90 90 90 90 90 90 90 90 90 90 90
```

对应指令：

```asm
mov  eax, [rsp+0x250]
cmp  eax, [rsp+0x120]
setb al
; 后接 14 个单字节 nop，补齐原指令长度
```

脚本将这 31 字节写入 UU 当前进程中的对应位置。进程退出后，这次内存修改随之结束。

## 生效过程

解码器初始化时按新顺序尝试设备，并保存选中的 allocator。因此，应用补丁后断开再连接，就会创建使用新顺序的解码器。

本机观察到的变化：

| 项目 | 修改前 | 修改后 |
| --- | --- | --- |
| 设备候选顺序 | RTX 4060 → Radeon 780M → 软件适配器 | Radeon 780M → RTX 4060 → 软件适配器 |
| UU 视频解码 | RTX 4060 Video Decode | Radeon 780M Video Codec 0 |
