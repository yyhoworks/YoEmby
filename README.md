# emby-next-gen-ce

基于官方 `plugin.service.emby-next-gen` **v12.4.24** 的独立优化工程，面向 **CoreELEC（Amlogic S905X4 / Kodi 21.3）+ 网盘 STRM 直连（`/CloudNAS/MVStrm`）+ YoPlayer · Infuse 皮肤** 深度定制与性能调优。

## 目录结构

```text
emby-next-gen-ce/
├── plugin.service.emby-next-gen/   # 核心插件源码（基线：上游 12.4.24）
├── docs/
│   └── BASELINE_AUDIT.md           # 实测硬件/数据库基线、YoPlayer 契约红线与瓶颈分析
├── scripts/
│   ├── deploy_to_ce.ps1            # 语法校验 -> 停 Kodi -> 远端快照 -> 部署 -> 启动并查日志
│   └── inspect_ce.ps1              # 采集 CE 内存、数据库体积、最近 Emby 日志与异常
└── README.md
```

## 目标运行环境（基线：2026-11-23）

- **设备**：`yoplayer-ce` (`192.168.1.123`)，Amlogic S905X4 / 4 核 / 3.7 GB RAM / 12.3 GB `/storage`
- **系统**：CoreELEC `21.3-Omega_forbxy_X10.4` (`Amlogic-ng.arm`，Kernel 4.9.269) + Kodi `21.3`
- **皮肤与首页数据源**：`skin.yoplayer.infuse` `v2026.10.3.269` + `plugin.video.yoplayer.home` `v1.0.85`
- **Emby 服务端**：`DemoUser_Home_Nas`，Emby Server `4.10.2.0`
- **媒体库体量**：12 个分库（803 电影 / 192 剧集 / 7819 单集），`MyVideos131.db` 126.7 MB，`emby_*.db` 24.1 MB

## 重点优化方向（立项路线图）

1. **P0 · 播放体验与 STRM 稳定性**
   - 播放时暂停后台同步（防止高码率 4K / 杜比视界 FEL 播放抢占 CPU 与 SQLite I/O）
   - 优化网盘 STRM 播放前链路（超时策略、起播前冗余探测精简、302 重定向处理）
   - 排查并优化 `No mediastreams found` 的 `.strm` 条目流信息处理
2. **P1 · 启动速度、内存与后台线程瘦身**
   - 审计直连模式下闲置的内部 Webservice workers（默认 5 线程）及非必要后台监听线程（直播/主题曲等）
   - 跟踪并降低 `kodi.bin` 1.6 GB 常驻内存中的插件侧开销
3. **P1 · 与 YoPlayer · Infuse 协同加速**
   - 严格守住 YoPlayer 依赖的 SQLite 契约（详见 [BASELINE_AUDIT.md](docs/BASELINE_AUDIT.md)）
   - 评估针对首页分库/评分/开播前选轨的索引与增量事件联动优化
4. **P2 · 同步效率与版本可维护性**
   - 保持对上游 `emby-next-gen` 的清晰 Git diff，便于后续合并上游修复

## 常用脚本

```powershell
# 查看 CE 盒子当前状态与日志
.\scripts\inspect_ce.ps1

# 检查语法并部署当前源码到 yoplayer-ce（自动停 Kodi、做回滚备份、重启验证）
.\scripts\deploy_to_ce.ps1
```
