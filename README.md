# YoEmby

面向 **CoreELEC（Amlogic S905X4 / Kodi 21.3）+ 网盘 STRM 302（YoLink）+ YoPlayer · Infuse** 深度定制与性能调优的 Emby Kodi 同步插件。

基于上游 `plugin.service.emby-next-gen` **v12.4.24**（GPLv3，原作者 `quickmic`），采用**上游极小侵入钩子（17 个上游文件累计仅 `+123` 行）+ 独立 `ce_opt/` 模块收口**架构：不动 CoreELEC 系统、不动 YoPlayer 皮肤/首页插件、不破坏上游数据库契约，全部优化项均可通过 `ce_opt.json` 随时单项开关或一键退回上游原版行为。

> 完整契约与工程治理规则见 [AGENTS.md](AGENTS.md)，详细改造与实测记录见 [docs/CE_CHANGES.md](docs/CE_CHANGES.md)。

## 生态定位

```text
YoLink (NAS STRM / 302 入口) ──▶ Emby Server ──▶ YoEmby (同步 / 海报 / 播放桥) ──▶ YoPlayer (Kodi Infuse UI)
```

- **Addon 显示名**：`YoEmby`
- **Addon ID（兼容锁死）**：`plugin.service.emby-next-gen`（保持与 YoPlayer 9 处集成契约 100% 兼容）
- **Addon Version（白名单锁死）**：`12.4.24`（保持留在 YoPlayer `VERIFIED_VERSIONS` 已核验白名单内）

## 实测效果（CoreELEC 21.3 / S905X4）

| 指标 | 上游 12.4.24 基线 | YoEmby (`v12.4.24-ce.1`) | 提升 |
| :--- | :--- | :--- | :--- |
| 海报经本地 `57342` 传输体积 | `1,143 KB`（原图） | **`89.4 KB`**（`maxWidth=600&quality=85`） | **`-92.2%`** |
| 海报经本地 `57342` 热请求耗时 | `73.9 ms` | **`8.5 ms`**（含 `tag` 强缓存） | **`8.7×` 提速** |
| `emby_*.db` 按 `KodiId` 反查 | `SCAN` 全表扫描 | **`SEARCH ... idx_Episode_KodiId`**（`0.067 ms/次`） | 消除全表扫描 |
| 启动增量同步 `KodiStartSync`（无变更） | `88` 次查询 / `~700 ms` | **`12` 次查询 / `143~147 ms`** | **`-86.4%` 请求 / `~5×`** |
| `kodi.bin` 待机自愿上下文切换 | `1,583.0 /s` | **`1,044.7 /s`** | **`-34.0%`** |
| 启动 `kodi.log` 插件报错 / `Errno 98` | 存在 `Errno 98` | **`0` 报错 / `0` `Errno 98`** | 干净启动 |

## 已落地优化模块（`ce_opt/`）

1. **海报与图片加载**（`ce_opt/artwork.py`）
   - `/picture/` 307 跳转补齐 `tag`、按图种附带 `maxWidth`（Primary 600 / Thumb 640 / Logo 800 / Backdrop 1920）与 `quality=85`（Logo/Art/Disc 保留 PNG 透明通道）
   - `artworkcache` 升级为 6 并发 Keep-Alive 预缓存 + URL 去重 + 250ms 进度节流 + 修复 JPEG `0xC4` DHT 误判并新增 WebP/GIF 尺寸解析
2. **扫库与启动增量提速**（`ce_opt/sync_fast.py`）
   - 主题音乐/视频关闭时跳过全库无意义 `Theme` 入队（开启开关即自动恢复，不影响去片头/片尾）
   - 进度条 `250ms` 节流、演员/导演/编剧/流派/标签/制片商关联表分批 `IN` + `executemany` 批量写入
   - 演员 `art` 冗余 `poster`/`landscape` 去重、过滤无图 5 分钟假章节（100% 保留 `IntroStart`/`IntroEnd`/`CreditsStart` 去片头片尾标记）、`PersonPaging` 限幅至 `5000`
   - 启动增量同步信任 Kodi Companion 空队列快路径，无变更时跳过 86% 冗余查询
3. **HTTP STRM 快路径**（`ce_opt/strm.py`）
   - 保持 `http://127.0.0.1:57342/http/...` 路径契约兼容 YoPlayer `embypath.py`
   - 跳过会误触发 HLS 转码的阻塞 `HEAD` 探测；对局域网 HTTP STRM 302 网关（如 YoLink）直出 307 跳转（显式 `main.m3u8` 转码除外）
4. **HDR10+ / 音轨徽标与流信息回填**（`ce_opt/stream_meta.py`）
   - 精准对齐 YoPlayer·Infuse 徽标词表：`hdr10plus`、`dolbyvision`、`truehd_atmos`、`eac3_ddp_atmos`、`dtsx`、`dtshd_ma`、`dtshd_hra`
   - 未探针 STRM 支持文件名保守兜底 + 首次播放起播后自动读取 Kodi 实测流回填 `streamdetails`
5. **数据库索引、上游 Bug 修复与待机降耗**（`ce_opt/db_indexes.py`、`ce_opt/idle_opt.py`）
   - 启动自动增量创建 6 个 `KodiId`/`KodiFileId` 索引，RW 连接启用 `PRAGMA cache_size=-32768`
   - 修复更新播放进度误覆写章节书签、只读连接字典泄漏、`webservice` 重复 bind `Errno 98`、开机等待条件反向及原生多版本分辨率比较 Bug
   - 事件驱动 `interruptible_sleep` 替换 10Hz 忙等，收敛待机后台轮询线程

## 安装方式

### 方式一：Kodi 内直接安装（推荐）
1. 前往本仓库 [Releases](https://github.com/yyhoworks/YoEmby/releases) 下载 `plugin.service.emby-next-gen-12.4.24-yoemby-ce*.zip`。
2. 在 CoreELEC / Kodi 中进入 **插件 → 从 ZIP 文件安装**，选择该压缩包覆盖安装。
3. 重启 Kodi（或在 SSH 执行 `systemctl restart kodi`），启动后将自动建好增量索引。

### 方式二：通过 SSH 脚本一键部署（开发者）

```powershell
# 运行本地守卫校验（版本锁、表结构契约、语法、上游 Diff 规模、21 项单元测试）
python .\scripts\verify_guardrails.py

# 通过守卫校验并部署到 CoreELEC（自动备份旧版以支持秒回滚）
.\scripts\deploy_to_ce.ps1

# 只读巡检 CoreELEC 状态、数据库体积与最近 Emby 日志
.\scripts\inspect_ce.ps1
```

## 运行时开关配置（`ce_opt.json`）

如需微调参数或关闭某项优化，无需改代码，在以下路径新建 `ce_opt.json` 并重启 Kodi 即可生效：

```text
/storage/.kodi/userdata/addon_data/plugin.service.emby-next-gen/ce_opt.json
```

示例：
```json
{
  "PICTURE_MAX_WIDTHS": {
    "Primary": 600,
    "Backdrop": 2560
  },
  "STRM_LAN_DIRECT_REDIRECT": true
}
```
写入 `{"ENABLED": false}` 可一键全部退回上游 `12.4.24` 原版行为。

## 目录结构

```text
YoEmby/
├── AGENTS.md                        # 项目硬规则（防屎山、禁动 CE/UI、契约红线）
├── plugin.service.emby-next-gen/    # 核心插件源码（基线 tag: upstream-12.4.24）
│   └── ce_opt/                      # CoreELEC 专有优化收口目录（7 个独立纯模块）
├── docs/
│   ├── BASELINE_AUDIT.md            # 实测硬件/数据库基线、YoPlayer 契约红线与瓶颈审计
│   └── CE_CHANGES.md                # 定制改动账本（触碰文件、回退开关、实测前后数据）
├── scripts/
│   ├── verify_guardrails.py         # 契约守卫 + 语法校验 + 上游 Diff 审计 + 单测入口
│   ├── deploy_to_ce.ps1             # 守卫校验 -> 停 Kodi -> 远端快照 -> 部署 -> 启动
│   └── inspect_ce.ps1               # 只读采集 CE 内存、数据库体积、最近日志与异常
├── tests/
│   └── test_ce_opt.py               # 21 项纯 Python 本地单元测试
└── README.md
```

## 开源协议与致谢

本项目基于 [MediaBrowser/plugin.video.emby](https://github.com/MediaBrowser/plugin.video.emby) (`plugin.service.emby-next-gen` v12.4.24，作者 `quickmic`)，延续原项目 **GPL-3.0** 协议。
