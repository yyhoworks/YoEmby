# YoEmby CoreELEC 定制改动账本

基线 Tag：`upstream-12.4.24`（提交 `39aacb6`）  
目标环境：CoreELEC 21.3 (`avdvplus`) / Amlogic S905X4 / YoLink STRM / YoPlayer·Infuse

## 改动总览

| 批次 | 主题 | 触碰上游文件 | 新增 `ce_opt/` 模块 | 回退 / 开关 | 实测效果 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 基线 | 品牌更名与工程守卫 | `addon.xml`（仅 `name`/`provider-name`/`source`，锁死 `id`/`version`） | — | `git checkout upstream-12.4.24` | 建好 `AGENTS.md` 与 `verify_guardrails.py` 自动拦截 |
| Batch 1 (`b37c006`) | 基础框架 + 上游 P0/P1 稳定性止血 | `helper/utils.py`, `hooks/webservice.py`, `helper/player.py`, `database/dbio.py`, `emby/http.py` | `ce_opt/__init__.py`, `ce_opt/config.py`, `ce_opt/safety.py` | `ce_enabled`, `ce_safe_workers`, `ce_fix_subtitle_select` | 修复 57342 worker 遇错永久死亡、`wait_for_Embyserver` 倒置循环持锁休眠、空 `MetaData`/无流 STRM 多版本崩溃、`DBConnectionsRO` 泄漏与 `DBOpenRW` 死循环、外挂字幕误关内封字幕、WS 握手与 EBADF 刷错；单测 8/8 通过 |
| Batch 2 (`9f70c0e`) | 同步去重、刷新防抖、增量索引与懒过期 | `hooks/websocket.py`, `database/library.py`, `helper/utils.py`, `hooks/monitor.py`, `database/emby_db.py`, `database/dbio.py`, `helper/player.py`, `emby/httpcache.py` | `ce_opt/sync_fast.py`, `ce_opt/db_opt.py` | `ce_sync_debounce`, `ce_sync_fingerprint`, `ce_widget_debounce`, `ce_db_indexes`, `ce_db_pragmas`, `ce_pause_sync_during_playback`, `ce_lazy_httpcache` | `emby_*.db` 无损自动创建 8 个 `idx_ce_*` 覆盖索引，`Episode.EmbyPresentationKey` 查询从 `2.276 ms/q` 降至 `0.068 ms/q`（实测 **33.6× 加速**）；消除 `httpcache` 常驻 5Hz 轮询线程；启动期伪扫描刷新收口为 3 次；单测 15/15 通过 |
| Batch 3 (`653654b`) | `avdvplus` 完整徽标 + STRM 缺流自愈 + 多版本策略 | `core/common.py`, `database/video_db.py`, `hooks/webservice.py`, `helper/player.py` | `ce_opt/stream_meta.py`, `ce_opt/stream_heal.py`, `ce_opt/strm.py` | `ce_avdvplus_badges`, `ce_strm_heal`, `ce_strm_path_fix`, `ce_strm_timeout`, `ce_multiversion_policy` | 自动检测 `MyVideos131.db` 的 `avdvplus` 扩展列并原生写入 `strDvProfile`/`strHdrTypeAlt`/`strAudioProfile`（部署后首次增量同步即实测写入新音频 Profile，4→8）；修复 HTTP/STRM 双拼 `|redirect-limit` 与 307 中文编码；补齐播后缺流自愈回写与 SMB 优先多版本策略；单测 23/23 通过 |
| Batch 4 (`1e556b4`) | 海报 307 瘦身 + 运维体检工具 + 设置页 | `hooks/webservice.py`, `helper/artworkcache.py`, `core/common.py`, `hooks/monitor.py`, `resources/settings.xml`, `en_gb`/`zh_cn` `strings.po` | `ce_opt/artwork.py`, `ce_opt/maintenance.py` | `ce_artwork_307_opt`, `ce_artwork_webp`, `ce_skip_chapter_bookmarks` | 实测 `127.0.0.1:57342` 海报 307 重定向已带 `tag=...&maxWidth=800&quality=85` 且去除多余 `?&`；`artworkcache` 支持 WebP 解析与空批次跳过；新增 Kodi 设置页「YoEmby 优化」及只读健康体检/索引核对/批量回填/二次确认清理工具；单测 27/27 通过 |
| Batch 5 (`6b82eef`) | 10-foot 电视 UI 重构与设置页精简 | `resources/settings.xml`, `en_gb`/`zh_cn` `strings.po`, `1080i/script-emby-ce-maintenance.xml`, `1080i/script-emby-skip*.xml`, `1080i/script-emby-context.xml` | `ce_opt/maintenance_ui.py` | `ce_enabled`（含 `<dependencies>` 自动联动灰显） | 彻底消除 YoPlayer 皮肤下半透明 `DialogTextViewer` 叠加重影（插件独立不透明黑曜石 `WindowXMLDialog` 一体化摘要/明细/一键运维面板）；「YoEmby 优化」基本层级从 15 项精简至 4 项（顶部维护入口 + 总开关 + 本地化 `spinner` 多版本策略 + 精简书签 + 全中文 `help` 提示）；跳过片头/片尾改为右下角 Infuse 风格高对比悬浮胶囊避让字幕；上下文菜单琥珀金高亮并去除左右键误关；单测 32/32 通过 |
| Batch 6 (`ec684a2`) | CoreELEC 纯观影轻装模式与无用功能裁剪 | `hooks/monitor.py`, `hooks/webservice.py`, `core/movies.py`, `core/series.py`, `database/library.py`, `helper/utils.py`, `resources/settings.xml` | `ce_opt/lite.py` | `ce_lite_mode`（专家级开关，关闭或关总开关即完整恢复上游行为） | `black.*` 15 个黑屏文件改为按扩展名首次按需懒加载（`hooks/webservice.py` 净删 76 行，省 ~4.3 MB 启动内存与 15 次闪存读取）；主题未启用时不启动 `monitor_Themes` 常驻线程且跳过每部电影/剧集的 Emby Theme/Trailer 冗余同步请求；停止自动复制 33 MB `rollback/`；设置页原生 `<visible>false</visible>` 隐藏 4 个无用分页（主题音乐/影院开场/动态库/备份）与 11 个转码/远程/分页/压缩分组；默认屏蔽 15 项杂乱或误删类右键菜单；单测 36/36 通过 |
| Batch 5.1 (`1bd106c`) | 视觉交还皮肤主导（移除自定义黑框，中性化默认覆盖层） | `resources/skins/default/1080i/script-emby-skip*.xml`, `script-emby-context.xml`（并移除 `script-emby-ce-maintenance.xml`） | 精简 `ce_opt/maintenance.py`（移除 `maintenance_ui.py`） | 全程原生 Kodi 弹窗，皮肤自动接管全部主题与材质 | 移除自定义暗色维护弹窗与硬编码亮黄/红绿配色；`open_maintenance_menu()` 打开前自动收起底层 `DialogAddonSettings`（彻底避免双层毛玻璃透字重影），退出时自动切回设置页，使用无 `[COLOR]` 纯文本动态摘要供 `Dialog.select`/`textviewer`/`yesno`/`DialogProgressBG` 由 YoPlayer 皮肤原生渲染；跳过片头/片尾与右键菜单改为中性灰白微透兜底（皮肤侧放置同名 XML 即可自动覆盖）；单测 36/36 通过，实机 0 报错 |
| Batch 7 | YoEmby 健康体检分页卡片仪表盘（方案 3） | 新增 `resources/skins/default/1080i/script-yoemby-health.xml`（非 YoPlayer 皮肤兜底 XML；零改动既有上游 Python 文件） | `ce_opt/yoemby_health_dashboard.py`, 升级 `ce_opt/maintenance.py` | 自动匹配 YoPlayer 皮肤同名厚磨砂覆写窗口，非 YoPlayer 皮肤无缝回退至兜底 XML | 接入 `open_health_dashboard(...)` 3 页 × 2×2 分页卡片仪表盘，直接构造结构化 `report_data` 并保留 `raw_text` 供「查看原始报告」使用；绑定 `fix_missing_streams` / `clean_rollback` / `rebuild_index` / `refresh` 回调并在维护后自动刷新卡片与原始报告；精确拆分「Emby 总缺流」与「本机可回填」指标避免未播 STRM 误报；严格遵循控件 ID（`1001`/`1002`/`1003`/`1009`/`1101`-`1103`/`2000`/`3001`/`3002`）、`YoEmby.Page` 与 `ListItem` 属性契约 |

---

## CoreELEC 实测验收快照（2026-11-24 14:04，Batch 7 健康体检分页卡片仪表盘）

- **部署方式**：`scripts/deploy_to_ce.ps1`（护栏检查 + 41/41 单测通过，自动备份旧插件并排除 `__pycache__`，不触碰用户 `settings.xml` 与 YoPlayer 皮肤）。
- **日志与服务状态**：`kodi.log` 中 `EMBY` / `ce_opt` / `yoemby` / `settings.xml` 报错与警告为 **0 条**；`127.0.0.1:57342` 监听正常；重启稳定后常驻 `VmRSS` 为 **516.3 MB**（`528,736 kB`）。
- **实机只读数据校验**：在 CoreELEC Python 3 环境直接对真实数据库执行 `collect_health_report()` + `build_dashboard_data()`，准确生成 3 页 × 2×2 卡片：
  - 顶部摘要：`总存储 1.52 GB · 增量索引 8 / 8 健康 · 1 项可优化`（不再将未播云盘 STRM 误计为待优化）
  - 第 1 页（存储分布）：Thumbnails `1.26 GB`（`step=80`）、数据库 `158.9 MB`、`addon temp/` `73.7 MB`、`rollback/` `33.0 MB`（`warn`，绑定 `clean_rollback`）
  - 第 2 页（媒体库与流信息）：增量索引 `8 / 8`（`ok`，绑定 `rebuild_index`）、媒体源分布 `总 8,851 / 72.9% STRM`、Emby 缺流条目 `417 条`（精确 `LEFT JOIN` 统计，本机可回填 `0` 条，标记 `待播后自愈` / `info`）、CoreELEC 优化与徽标 `开启`
  - 第 3 页（维护与一键修复）：4 项维护动作卡片（`fix_missing_streams` 显示 `暂无可回填 / 播后自愈`，`clean_rollback` / `rebuild_index` / `raw_report` 全部就绪）。
- **皮肤覆写状态**：实机日志已确认加载 `/storage/.kodi/addons/skin.yoplayer.infuse/1080p/script-yoemby-health.xml`（YoPlayer 厚磨砂覆写窗口），且 `kodi.log` 零 Python 报错/异常。

---

## CoreELEC 实测验收快照（2026-11-24 11:53，Batch 5 + Batch 6）

- **部署方式**：`scripts/deploy_to_ce.ps1`（护栏检查 + 36/36 单测零警告通过后自动备份并部署，不触碰用户 `settings.xml` 与 YoPlayer）。
- **错误与警告日志**：`kodi.log` 中 `EMBY` / `ce_opt` / `settings.xml` 报错与警告为 **0 条**；启动至 `Server Online` 耗时 **3.4 秒**，`127.0.0.1:57342` 监听正常。
- **内存与线程对比**：重启后常驻 `VmRSS` 降至 **516 MB**（`528,560 kB`，较 Batch 4 部署后 547 MB 再降 ~31 MB，较改造前空闲 811 MB 降 ~295 MB）；`themes.monitor_Themes` 未启动，`rollback/` 未重新生成。
- **上下文菜单实测**：通过 Kodi JSON-RPC 实测 `Window(10000)` 属性，`EmbyRemote` / `EmbyDownload` / `EmbyRecording` / `EmbyPlayRandom` / `EmbySimilar` / `EmbySettings` / `EmbyDelete` 均为 `False`，而 `EmbySpecials` / `EmbyGoto` / `EmbyRefresh` / `EmbyFavourite` 均为 `True`。
- **一体化体检视图实测**：只读扫描真实数据库输出 `2 项可优化`（总存储 `1.52 GB` 含 `33.0 MB` 旧备份、8852 片源 / 8/8 覆盖索引 / 417 条缺流、`avdvplus` 徽标就绪），按键文案自动显示 `补齐缺流 (417)` 与 `清理旧备份 (33.0 MB)`。

### 历史基线验收快照（2026-11-24 11:07，Batch 1–4）

- **部署方式**：`scripts/deploy_to_ce.ps1`（自动备份旧插件至 `/storage/backup/emby-dev/`，并剔除本地 `__pycache__`）。
- **错误日志**：`kodi.log` 中 `EMBY` / `ce_opt` 报错与 Traceback 为 **0 条**。
- **内存基线**：重启同步完成后 `kodi.bin` RSS 为 **547 MB**（对比改造前空闲 811 MB / 同步峰值 1.6 GB）。
- **数据库与索引实测**：
  - `emby_*.db`（26.2 MB）：8 / 8 个 `idx_ce_*` 纯增量索引自动生效，表名与列名 100% 保持 YoPlayer 契约。
  - `Episode` 按 `EmbyPresentationKey` 200 次查询基准：全表扫描 `455.30 ms`（`2.276 ms/q`） vs 覆盖索引 `13.57 ms`（`0.068 ms/q`），**提速 33.6×**。
- **57342 海报 307 实测**：返回 `HTTP/1.1 307 Temporary Redirect`，`Location` 包含 `tag=`、`maxWidth=800`、`quality=85`。
- **已知存量说明**：历史已入库的 914 部杜比视界影片与未播条目将在后续增量更新或手动执行一次“更新媒体库”时逐步补全 `avdvplus` 扩展徽标；417 条 Emby 缺流 STRM 条目将在播放后自动自愈回写，也可在「YoEmby 优化 → 运维工具」中一键将 Kodi 已有 `streamdetails` 批量回填到 `emby_*.db`。
