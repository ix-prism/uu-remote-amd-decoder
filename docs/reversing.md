# 逆向分析记录

本文记录网易 UU 远程 4.40.1.2090 的解码器适配器选择路径，以及运行时补丁所改动的位置。分析对象为官方 `streamer.dll`，SHA-256：

```text
C6A5429C076F4A564EC2CA73E7476D2429F017005215AEE85C2BFAE13AA9D212
```

下文地址均为 PE RVA；另有注明时，文件偏移按磁盘文件计算。

## 解码器与适配器选择

`VideoDecoderFactory::CreateVideoDecoder`（`0xCFDCD0`）按 H.264/H.265 建立候选解码器。DXVA 初始化会构造 D3D11 allocator 候选，随后遍历适配器列表，检查 D3D11 device、video device、video context 和解码 profile，并采用首个满足要求的候选。

| 位置 | 作用 |
| --- | --- |
| `0xD19170` | H.265 DXVA 初始化；无预设 allocator 时以 flags `0x18` 调用 `0x99DC80` |
| `0xD28990` | H.264 DXVA 初始化；默认路径同样以 flags `0x18` 调用 `0x99DC80` |
| `0x99DC80` | 枚举 DXGI 适配器并返回 allocator 候选列表 |
| `0xD1953F` / `0xD28C9B` | 遍历 H.265 / H.264 候选并逐项检查能力 |
| `0xD1A3F8` / `0xD29C95` | 保存选中的 allocator；后续重配可复用该对象 |

`0x99DC80` 在 IDXGIFactory6 可用时使用 `DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE`（值为 `2`）枚举适配器。枚举结果之后仍会交给 `0x99B470` 按 VendorId 排序，所以改变 DXGI preference 本身不能保证 AMD 排在 NVIDIA 前面。

## 原始厂商排序

比较器 `0x99B470` 在 `0x99B4F3` 和 `0x99B4FF` 读取两个适配器的 `DXGI_ADAPTER_DESC.VendorId`，并通过全局映射 `0x9B2310` 转成排序等级：

| VendorId | 厂商 | 原始 rank |
| --- | --- | ---: |
| `0x10DE` | NVIDIA | 0 |
| `0x1002` | AMD | 1 |
| `0x8086` | Intel | 2 |
| 其他 | 其他适配器 | 5 |

原排序会把 RTX 4060 放在 Radeon 780M 前面。补丁只替换这个 allocator 列表的比较逻辑，按原始 VendorId 无符号升序排列。结果是 AMD `0x1002` 排在 NVIDIA `0x10DE` 前，其他适配器继续按各自 VendorId 排序。全局厂商等级映射保持原样。

## 局部补丁

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

替换段的指令含义：

```asm
mov  eax, [rsp+0x250]
cmp  eax, [rsp+0x120]
setb al
nop × 14  ; 每条 1 字节，用于补齐原指令序列长度
```

运行工具会先校验目标构建哈希和该位置的原始字节，再在目标进程内存中替换这 31 字节。任一检查失败时不写入。磁盘上的 `streamer.dll` 不会被修改，因此它的原签名保持不变。

## 生效时机与适用边界

H.264/H.265 解码器对象会保存已选中的 allocator。若 UU 重配时复用已有 allocator，就会跳过适配器枚举和排序。因此，应用补丁后需要断开并重新连接，让 UU 创建新解码器。

补丁的排序依据是 VendorId。它使 AMD 设备优先于 NVIDIA、软件和 Intel 适配器，但不会识别“核显”这一类别：Intel 核显不是目标；存在多块 AMD 适配器时，也无法区分 AMD 核显和 AMD 独显。

实机观察覆盖 Windows 上的 AMD Radeon 780M 与 NVIDIA RTX 4060 Laptop，以及上述唯一列出的 UU 构建。其他硬件、驱动和 UU 版本需要单独验证。