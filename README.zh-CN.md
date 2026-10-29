<div align="center">

![macOS BLE Raw Advertiser](docs/banner.svg)

[![Version](https://img.shields.io/badge/version-1.0-2563eb?style=flat-square)](CHANGELOG.md)
[![Platform](https://img.shields.io/badge/platform-Apple%20Silicon-17488c?style=flat-square)](#运行环境)
[![macOS](https://img.shields.io/badge/macOS-26.4%20%2825E246%29-17488c?style=flat-square)](#运行环境)
[![License](https://img.shields.io/badge/license-MIT-79b9ef?style=flat-square)](LICENSE)

[English](README.md) · 简体中文

[快速开始](#快速开始) · [使用示例](#使用示例) · [命令说明](#命令说明) · [配置](#配置) · [工作流程](#工作流程) · [架构](#架构) · [故障排查](#故障排查) · [开发](#开发)

</div>

---

macOS BLE Raw Advertiser 使用 Mac 的内置蓝牙发送自定义 BLE 主广播和扫描响应。通过 JSON 配置 iBeacon 厂商数据、Service Data 和设备名称，在 Finder 或终端启动和停止广播。

项目由原生 CoreBluetooth 应用和针对系统构建的 LLDB 辅助程序组成。辅助程序在 `bluetoothd` 中定位应用对应的会话，写入一个权限字节以启用原始广播，然后退出调试器。广播请求与无线调度交由 macOS 处理。

## 主要功能

- **原始主广播与扫描响应**：两份缓冲区独立配置，各支持最多 31 字节。
- **附加服务数据**：把 Service Data 与 iBeacon 数据、设备名称组合发送。
- **JSON 配置**：规范化十六进制，检查 AD 长度、字段结构，并输出解析预览。
- **按会话放行**：核对客户端 PID、可执行路径、创建时间和用户，再写入会话权限。
- **构建适配检查**：检查系统构建、daemon 哈希、加载模块 UUID 和权限判断指令。
- **后台运行**：启动窗口关闭后，独立应用继续广播。
- **生命周期管理**：提供启动、停止、状态和环境检查；用配置指纹识别正在运行的报文。
- **完整项目**：附带源码、系统适配资料、离线测试、构建和发行打包工具。

## 运行环境

| 项目 | 支持配置 |
| --- | --- |
| Mac | Apple Silicon，使用内置蓝牙 |
| macOS | **26.4，构建 25E246** |
| 开发工具 | Apple Command Line Tools 或 Xcode，含 Clang、LLDB、Python 3.9+ |
| 应用权限 | 蓝牙权限与项目文件夹访问权限 |
| 系统访问 | 管理员授权，以及允许系统进程调试的 SIP 调试配置 |

[平台适配资料](profiles/macos-26.4-25E246-arm64.json) 固定了这份构建对应的 `bluetoothd` SHA-256、arm64e UUID 和指令。匹配检查用于确认会话实验的运行环境。

## 快速开始

### 1. 构建并选择报文

将发行包解压或克隆到固定、可写的目录，在该目录打开终端：

```sh
# 新机器准备开发工具
xcode-select --install

# 构建 arm64 应用
./scripts/build.sh

# 创建本机配置
cp examples/ibeacon-service-data.json config.json

# 查看报文与环境检查结果
python3 scripts/cli.py validate
python3 scripts/cli.py doctor
```

发行包包含源码和 ad-hoc 签名的应用。启动程序检查源码指纹，源码变化后会重新构建。Python 部分使用标准库和 Apple LLDB 运行环境。

### 2. 配置系统调试权限

会话辅助程序使用系统进程调试权限。Apple Silicon Mac 的准备步骤：

1. 关机，持续按住电源键直到出现启动选项，选择“选项”→“继续”。
2. 在恢复模式打开“实用工具”→“终端”。
3. 执行：

   ```sh
   csrutil enable --without debug
   ```

4. 重启 macOS，再运行 `python3 scripts/cli.py doctor`。

该设置允许调试受保护的系统进程。准备与恢复命令是这项实验的操作流程。[Apple 的运行时保护文档](https://developer.apple.com/library/archive/documentation/Security/Conceptual/System_Integrity_Protection_Guide/RuntimeProtections/RuntimeProtections.html) 介绍了相关机制。

### 3. 开始广播

双击 **start.command**，或执行：

```sh
python3 scripts/cli.py start
```

按 macOS 提示允许 `RawBLEAdvertiser` 使用蓝牙、访问项目文件夹，再通过管理员窗口授权本次会话。成功后输出：

```text
Raw advertising accepted. Verify the payload with an active BLE scanner.
ADV 30 bytes / SCAN_RSP 19 bytes
```

启动窗口关闭后应用继续运行。双击 **status.command** 查看状态，双击 **stop.command** 结束会话。

## 使用示例

| 目的 | 命令 |
| --- | --- |
| 发送本机配置 | `python3 scripts/cli.py start` |
| 发送 iBeacon 与服务数据示例 | `python3 scripts/cli.py start --config examples/ibeacon-service-data.json` |
| 发送精简服务数据示例 | `python3 scripts/cli.py start --config examples/service-data.json` |
| 解析配置 | `python3 scripts/cli.py validate --config examples/service-data.json` |
| 读取 JSON 状态 | `python3 scripts/cli.py status --json` |
| 查看环境检查 | `python3 scripts/cli.py doctor --json` |
| 停止广播 | `python3 scripts/cli.py stop` |

公开示例字段：

| 字段 | 值 |
| --- | --- |
| 完整名称 | `RawBLELab` |
| iBeacon UUID | `12345678-1234-5678-1234-56789ABCDEF0` |
| Major / Minor | `1` / `1` |
| Measured Power | `-69` |
| Service UUID | `0xFFF0` |
| Service Data | `01020304` |

### 用手机核对接收结果

1. 启动前扫描一次，记录测试标识的基线。
2. 启动项目，使用支持**主动扫描**的工具寻找 `RawBLELab`。
3. 核对 iBeacon 字段与 `0xFFF0` 对应的数据。主动扫描获取包含名称和 Service Data 的扫描响应。
4. 导出带接收时间的完整记录；停止项目，对照条目是否继续更新，并注意扫描缓存。

`on` 状态记录本次会话授权、调试器退出和系统广播回调成功。导出扫描记录后，可以核对手机收到的报文字节。

## 命令说明

| 命令 | 作用 | Finder 入口 |
| --- | --- | --- |
| `start [--config FILE]` | 校验环境，启动广播会话 | `start.command` |
| `stop` | 根据路径与创建时间停止本项目客户端 | `stop.command` |
| `status [--json]` | 查看当前客户端状态 | `status.command` |
| `doctor [--json]` | 检查硬件、构建、哈希、LLDB 和调试权限 | `check.command` |
| `validate [--config FILE]` | 规范化十六进制并解析 AD 结构 | 终端 |

配置选择顺序：`--config FILE` → `config.json` → `examples/ibeacon-service-data.json`。

同配置重复启动会复用当前进程。更换正在发送的报文时，先停止再启动。睡眠、蓝牙重置或 daemon 重启后，检查状态并按需启动新会话。

## 配置

```json
{
  "name": "RawBLELab",
  "description": "iBeacon + Service Data example",
  "advertisingDataHex": "0201061AFF4C0002151234567812345678123456789ABCDEF000010001BB",
  "scanResponseDataHex": "0716F0FF010203040A09526177424C454C6162"
}
```

| 字段 | 含义 |
| --- | --- |
| `name` | 配置标签；报文包含完整名称时，校验标签与名称字节一致 |
| `description` | 便于阅读的说明 |
| `advertisingDataHex` | 主广播 AD 结构，1–31 字节 |
| `scanResponseDataHex` | 扫描响应 AD 结构，0–31 字节；空缓冲区用 `""` |

十六进制支持大小写和空白。校验器检查 AD 边界、Flags 所在缓冲区、Service Data UUID 长度、Company ID 长度、名称 UTF-8，以及名称标签与原始字节的一致性。

AD 结构为 `[Length][Type][Data]`，Length 包括 Type 和 Data。16 位服务 UUID 按低字节在前编码，例如 `0xFFF0` 写为 `F0 FF`。更改字段大小时同步更新 AD 长度，并填写每份缓冲区的有效数据。

默认示例拆分为：

```text
ADV       30 字节：Flags + iBeacon 厂商数据
SCAN_RSP  19 字节：Service Data + 完整名称
```

手机导出的 `rawHex` 常把主广播与扫描响应合并。按 AD 结构拆分到两份配置中。实际发射地址与无线调度由 macOS 管理。

## 工作流程

```mermaid
flowchart LR
    A[校验配置与构建] --> B[启动原生应用]
    B --> C[建立 LLDB 硬件断点]
    C --> D[提交 ADV 与 SCAN_RSP]
    D --> E[匹配客户端会话]
    E --> F[写入会话权限字节]
    F --> G[退出调试并确认广播]
```

校验后，应用通过 LaunchServices 启动。管理员辅助程序附加到 `bluetoothd`，核对加载模块和指令，建立硬件断点后释放广播请求。命中目标客户端会话时写入权限字节并回读，然后删除断点、退出调试。应用核对 PID、令牌与报文指纹，再记录 `on` 状态。

## 架构

| 模块 | 文件 | 职责 |
| --- | --- | --- |
| 原生应用 | `src/main.m`、`src/Info.plist` | CoreBluetooth、后台运行、状态和进程归属 |
| 控制 | `scripts/cli.py`、`scripts/control.sh` | 配置选择、环境检查、启动停止 |
| 报文解析 | `scripts/payload.py` | 十六进制规范化、AD 校验与预览 |
| 会话辅助程序 | `scripts/session_gate.py`、`scripts/gate-root.sh` | 身份核对、断点、权限写入和调试清理 |
| 适配资料 | `profiles/*.json` | 哈希、UUID、指令和会话布局 |
| 构建与发行 | `scripts/build.sh`、`scripts/package.py` | 编译、签名、ZIP 和校验清单 |

应用停止后，系统回收其 XPC 会话。调试附加与断点处理会短暂停止共享蓝牙进程。详细流程与偏移见 [architecture.md](docs/architecture.md)，相关公开工作见 [research.md](docs/research.md)。

## 运行文件

`.runtime/` 保存规范化请求、客户端状态、权限修改结果和两份日志。Git 忽略规则和发行打包工具将本机配置、运行文件及 `private/` 资料留在工作副本中。分享诊断摘录时，保留复现所需字段并检查其中的本机信息。

## 故障排查

| 现象 | 处理方法 |
| --- | --- |
| 构建或哈希不匹配 | 对照 `doctor --json` 与当前适配资料 |
| 工具查找失败 | 安装 Command Line Tools，检查 `xcrun --find lldb` 和 `xcrun --find python3` |
| 蓝牙准备超时 | 检查蓝牙开关以及应用的蓝牙、文件夹权限 |
| 管理员授权或 gate 失败 | 查看 `.runtime/gate.log`，处理报错后重试 |
| 状态为 error/off | 查看 `.runtime/advertiser.log`，再启动新会话 |
| 另一份报文正在运行 | 停止后再启动新配置 |
| 构建时提示客户端运行中 | 停止应用后重新构建 |
| 扫描器只显示 iBeacon 字段 | 检查主动扫描、扫描响应展示方式和缓存 |

### 恢复常规调试保护

先停止广播，进入恢复模式执行以下命令，再重启：

```sh
csrutil enable
```

管理员辅助程序在正常退出时恢复原先的 DevToolsSecurity 状态。实验被中断后可用 `DevToolsSecurity -status` 检查当前设置。系统配置说明见 [Apple 文档](https://developer.apple.com/documentation/security/disabling-and-enabling-system-integrity-protection)。

## 开发

```sh
# 配置、内存策略和打包测试
./scripts/test.sh

# 编译并签名原生应用
./scripts/build.sh

# 生成源码 + 应用 ZIP、内部文件清单与 ZIP 校验值
python3 scripts/package.py
```

离线测试覆盖 31 字节边界、AD 错误、客户端匹配、权限原值、读写失败、单字节写入范围和发行文件筛选。

目录包含 `src/`、`scripts/`、`profiles/`、`examples/`、`tests/` 和 `docs/`；构建结果存放在 `build/`，本次运行存放在 `.runtime/`。

新增系统适配与测试要求见 [CONTRIBUTING.md](CONTRIBUTING.md)，版本历史见 [CHANGELOG.md](CHANGELOG.md)。

## 许可证

作者：[ChengDSYJ-Studio](https://github.com/ChengDSYJ-Studio)。使用 [MIT](LICENSE) 许可证。
