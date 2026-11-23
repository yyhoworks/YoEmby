# YoEmby

面向 **CoreELEC（Amlogic S905X4 / Kodi 21.3）+ 网盘 STRM 302（YoLink）+ YoPlayer · Infuse** 深度定制与性能调优的 Emby Kodi 同步插件。

基于上游 `plugin.service.emby-next-gen` **v12.4.24**（GPLv3，原作者 `quickmic`），采用**最小侵入钩子 + 独立 `ce_opt/` 模块收口**架构，在不改动 CoreELEC 系统、不动 YoPlayer 皮肤/首页插件、不破坏上游数据库契约的前提下，重点提升海报加载速度、全量/增量扫库效率、STRM 起播稳定性与流信息/HDR10+ 支持。

> 完整契约与工程治理规则见 [AGENTS.md](AGENTS.md) 与 [docs/BASELINE_AUDIT.md](docs/BASELINE_AUDIT.md)。

## 生态定位

```text
YoLink (NAS STRM / 302 入口) ──▶ Emby Server ──▶ YoEmby (同步 / 海报 / 播放桥) ──▶ YoPlayer (Kodi Infuse UI)
```

- **Addon 显示名**：`YoEmby`
- **Addon ID（兼容锁死）**：`plugin.service.emby-next-gen`（保持与 YoPlayer 9 处集成契约 100% 兼容）
- **Addon Version（白名单锁死）**：`12.4.24`（保持留在 YoPlayer `VERIFIED_VERSIONS` 已核验白名单内）

## 目录结构

```text
YoEmby/
├── AGENTS.md                        # 项目硬规则（防屎山、禁动 CE/UI、契约红线）
├── plugin.service.emby-next-gen/    # 核心插件源码（基线 tag: upstream-12.4.24）
│   └── ce_opt/                      # CoreELEC 专有优化收口目录（后续按模块渐进添加）
├── docs/
│   ├── BASELINE_AUDIT.md            # 实测硬件/数据库基线、YoPlayer 契约红线与瓶颈审计
│   └── CE_CHANGES.md                # 定制改动账本（触碰文件、回退开关、实测前后数据）
├── scripts/
│   ├── verify_guardrails.py         # 契约守卫 + 语法校验 + 上游 Diff 膨胀审计 + 单测入口
│   ├── deploy_to_ce.ps1             # 守卫校验 -> 停 Kodi -> 远端快照 -> 部署 -> 启动
│   └── inspect_ce.ps1               # 采集 CE 内存、数据库体积、最近 Emby 日志与异常
├── tests/                           # 纯 Python 本地单元测试（不依赖真机 Kodi）
└── README.md
```

## 重点优化方向

1. **海报与图片加载提速**
   - `/picture/` 307 跳转补齐 `Tag`、按图种附带 `maxWidth` / `quality`、修复开机等待条件 Bug
   - `artworkcache` 改造为多线程分级预热（优先电影/剧集/季核心封面，演员/单集懒加载）并修复 JPEG 解析 Bug
2. **扫库与启动增量加速**
   - 主题曲关闭时跳过全量 `ThemeMedia` 串行请求
   - 进度条更新节流、写路径内存映射缓存 + `executemany` 批量写入、演员 `art` 去重、可选跳过无图假章节
   - 利用 Kodi Companion 精简开机 88 轮冗余查询，开启播放期暂停同步
3. **STRM 播放与功能补全**
   - 网盘 STRM 直连网关跳过高危阻塞 `HEAD` 探测，杜绝 4K 杜比视界误降级 HLS 转码
   - 补齐 `HDR10+` 与精细音轨识别、缺失 `streamdetails` 的 STRM 播后自动回写
   - 为 `emby_*.db` 增补 `KodiId` / `KodiFileId` 索引，同步加速 YoPlayer 评分与开播前选轨
4. **稳定性与后台瘦身**
   - 修复更新播放进度误覆写章节书签、只读连接字典泄漏、原生多版本选高画质等上游 Bug
   - 精简空转轮询线程，降低 S905X4 播放期 Python GIL 竞争

## 常用命令

```powershell
# 运行本地守卫校验（版本锁、表结构契约、语法、上游 Diff 体积、单元测试）
python .\scripts\verify_guardrails.py

# 查看 CoreELEC 盒子运行状态与日志（只读）
.\scripts\inspect_ce.ps1

# 通过守卫校验并部署插件到 CoreELEC（自动备份旧版以支持秒回滚）
.\scripts\deploy_to_ce.ps1
```

## 开源协议与致谢

本项目基于 [MediaBrowser/plugin.video.emby](https://github.com/MediaBrowser/plugin.video.emby) (`plugin.service.emby-next-gen` v12.4.24，作者 `quickmic`)，延续原项目 **GPL-3.0** 协议。
