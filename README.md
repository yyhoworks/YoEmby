# YoEmby

面向 **CoreELEC 21.3（`avdvplus` / Amlogic S905X4）+ 网盘 STRM 302（YoLink）+ 本地 SMB + YoPlayer · Infuse** 深度定制与性能调优的 Emby Kodi 同步插件。

基于上游 `plugin.service.emby-next-gen` **v12.4.24**（GPLv3，原作者 `quickmic`），采用**最小侵入钩子 + 独立 `ce_opt/` 模块收口**架构：不改动 CoreELEC 系统、不改动 YoPlayer 皮肤与首页插件、不破坏上游 SQLite 契约；所有优化均可在 Kodi 插件设置页「**YoEmby 优化**」中一键开关或无缝回退至上游默认行为。

> 工程守卫与契约红线见 [AGENTS.md](AGENTS.md)，完整改动账本与实机对比见 [docs/CE_CHANGES.md](docs/CE_CHANGES.md)。

## 生态定位

```text
YoLink (STRM / 302) + NAS SMB ──▶ Emby Server ──▶ YoEmby (同步 / 57342 桥接 / 维护) ──▶ YoPlayer · Infuse (UI)
```

- **Addon 显示名**：`YoEmby`
- **Addon ID（契约锁死）**：`plugin.service.emby-next-gen`（100% 兼容 YoPlayer 9 处集成契约）
- **Addon Version（白名单锁死）**：`12.4.24`（留在 YoPlayer `VERIFIED_VERSIONS` 白名单内）

## 实测效果（CoreELEC 21.3 `avdvplus` / S905X4）

| 指标 | 改造前基线 | YoEmby (`v12.4.24-ce.4`) | 改善 |
| :--- | :--- | :--- | :--- |
| `Episode.EmbyPresentationKey` 200 次查询 | `455.30 ms`（`2.276 ms/q` 全表扫描） | **`13.57 ms`**（`0.068 ms/q` 覆盖索引） | **33.6× 加速** |
| Kodi 空闲常驻内存 `VmRSS` | `~811 MB`（同步峰值 `1.6 GB`） | **`516~521 MB`**（开机直连稳定） | **-290 MB** |
| `kodi.log` EMBY 错误与警告 | 存在 worker 异常 / 重连刷错 | **`0` 错误 / `0` 警告**，3.4s 在线 | 干净稳定 |
| 57342 本地海报跳转 | 原图直跳 + 多余 `?&` | **307 带 `tag` 缓存 + `maxWidth=800&quality=85`** | 体积大幅瘦身 |
| 后台空转与冗余资源 | `httpcache` 5Hz 轮询 + 主题常驻线程 + 15 个黑屏文件预读 | **事件懒过期 + 零主题常驻线程 + `black.*` 懒加载** | 省启动内存与 I/O |
| 插件设置与右键菜单 | 10 分页 / 245 项设置 / 15 项杂乱右键 | **精简 4 项基本设置 + 隐藏无用分页 + 纯观影右键** | 电视遥控极简操作 |

## 核心优化模块（`ce_opt/`）

1. **P0/P1 稳定性止血**（`ce_opt/safety.py`）
   - 修复本地 `57342` worker 线程遇错永久退出、`wait_for_Embyserver` 倒置循环持锁休眠、空 `MetaData`/无流 STRM 多版本崩溃、`DBConnectionsRO` 泄漏与 `DBOpenRW` 死循环、外挂字幕误关内封字幕等上游 Bug。
2. **同步去重、防抖与增量索引**（`ce_opt/sync_fast.py`、`ce_opt/db_opt.py`）
   - WebSocket `LibraryChanged` 突发合并（防抖去重）、写库前元数据指纹跳过未变更条目、首页 Widget 刷新防抖、播放期自动暂停后台写库、`httpcache` 懒过期消除 5Hz 轮询线程。
   - 自动在 `emby_*.db` 无损创建 8 个 `idx_ce_*` 覆盖索引，RW/RO 连接应用 16 MB SQLite 缓存调优，100% 保持原表与列名契约。
3. **`avdvplus` 徽标、STRM 自愈与智能多版本**（`ce_opt/stream_meta.py`、`ce_opt/stream_heal.py`、`ce_opt/strm.py`）
   - 自动检测 CoreELEC `avdvplus` 的 `streamdetails` 扩展列，原生写入 `strDvProfile`（如 `8.1` / `7.6`）、`strHdrTypeAlt`（`hdr10plus` / `hdr10`）与 `strAudioProfile`（`Dolby Atmos` / `DTS:X`）。
   - 修复 HTTP/STRM 双拼 `|redirect-limit` 与 307 中文路径编码；STRM 播放后自动将 Kodi 实测流信息回写至 `emby_*.db`；支持多版本自动优先本地 SMB 或最高分辨率。
4. **海报 307 优化与健康体检分页卡片仪表盘**（`ce_opt/artwork.py`、`ce_opt/maintenance.py`、`ce_opt/yoemby_health_dashboard.py`）
   - 海报 307 重定向附带 `tag` 强缓存与尺寸限宽；`artworkcache` 补齐 WebP 尺寸解析并支持可选精简 5 分钟普通章节书签（保留片头片尾跳过）。
   - 接入 3 页 × 2×2 健康体检分页卡片仪表盘（`script-yoemby-health.xml`）：在 YoPlayer 皮肤下自动启用内置厚磨砂玻璃覆写窗口，非 YoPlayer 皮肤无缝回退至插件自带兜底 XML；打开前自动收起底层设置窗以消除双层毛玻璃重影，支持存储分布、媒体库与流信息（精确区分总缺流与本机可回填数）、一键维护修复、实时刷新与原始文本报告查看。
5. **CoreELEC 纯观影轻装模式**（`ce_opt/lite.py`）
   - `black.*` 15 个黑屏文件按扩展名首次按需懒加载；未开启主题/影院模式时不启动 `monitor_Themes` 常驻线程、跳过每部电影/剧集的 Emby Theme/Trailer 冗余同步请求、不再自动复制 `rollback/`。
   - 隐藏 4 个无用设置分页（主题音乐 / 影院开场 / 动态库 / 备份）与 11 个转码/远程/分页/旧图片压缩分组；自动隐藏 15 项杂乱或误删类右键菜单。

## 安装方式

### 方式一：Kodi 内直接安装（推荐）
1. 前往本仓库 [Releases](https://github.com/yyhoworks/YoEmby/releases) 下载最新 `plugin.service.emby-next-gen-12.4.24-yoemby-ce*.zip`。
2. 在 CoreELEC / Kodi 中进入 **插件 → 从 ZIP 文件安装**，选择压缩包覆盖安装。
3. 重启 Kodi（或 SSH 执行 `systemctl restart kodi`），即可在 **YoEmby 设置 → YoEmby 优化** 中查看与管理。

### 方式二：开发者本地校验与一键部署

```powershell
# 运行守卫校验（版本锁、表契约、语法、上游 Diff 审计、41 项单元测试）
python .\scripts\verify_guardrails.py

# 通过守卫校验并部署插件到 CoreELEC（自动远端备份旧版）
.\scripts\deploy_to_ce.ps1

# 只读巡检 CoreELEC 内存、数据库体积与最近 Emby 日志
.\scripts\inspect_ce.ps1
```

## 目录结构

```text
YoEmby/
├── AGENTS.md                        # 项目硬规则（防屎山、禁动 CE/UI、契约红线）
├── plugin.service.emby-next-gen/    # 核心插件源码（基线 tag: upstream-12.4.24）
│   └── ce_opt/                      # CoreELEC 专有优化收口目录（11 个独立纯模块）
├── docs/
│   ├── BASELINE_AUDIT.md            # 实测硬件/数据库基线、YoPlayer 契约红线与瓶颈审计
│   └── CE_CHANGES.md                # 定制改动账本（触碰文件、回退开关、实测对比）
├── scripts/
│   ├── verify_guardrails.py         # 契约守卫 + 语法校验 + 上游 Diff 审计 + 单测入口
│   ├── deploy_to_ce.ps1             # 守卫校验 -> 停 Kodi -> 远端快照 -> 部署 -> 启动
│   └── inspect_ce.ps1               # 只读采集 CE 内存、数据库体积、最近日志与异常
├── tests/                           # 41 项纯 Python 本地单元测试
└── README.md
```

## 开源协议与致谢

本项目基于 [MediaBrowser/plugin.video.emby](https://github.com/MediaBrowser/plugin.video.emby) (`plugin.service.emby-next-gen` v12.4.24，作者 `quickmic`)，延续原项目 **GPL-3.0** 协议。
