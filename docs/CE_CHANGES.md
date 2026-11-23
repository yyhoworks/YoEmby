# YoEmby CoreELEC 定制改动账本

基线 Tag：`upstream-12.4.24`（提交 `39aacb6`）  
目标环境：CoreELEC 21.3 / Amlogic S905X4 / YoLink STRM / YoPlayer·Infuse

## 改动总览

| 批次 | 主题 | 触碰上游文件 | 新增 `ce_opt/` 模块 | 回退 / 开关 | 实测效果 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 基线 | 品牌更名与工程守卫 | `addon.xml`（仅 `name`/`provider-name`/`source`，锁死 `id`/`version`） | — | `git checkout upstream-12.4.24` | 建好 `AGENTS.md` 与 `verify_guardrails.py` 自动拦截 |
| Batch 1.1 | 修复上游 5 处 Bug + `emby_*.db` `KodiId` 索引 + SQLite RW 缓存 | `video_db.py`, `dbio.py`, `emby_db.py`, `player.py`, `webservice.py`（共 `+25` 行） | `ce_opt/config.py`, `ce_opt/db_indexes.py` | `ce_opt.json`: `ENABLED` / `EXTRA_EMBY_INDEXES` / `DB_RW_CACHE_KB` | 启动自动增量创建 6 个 `KodiId`/`KodiFileId` 索引；`Episode WHERE KodiId=?` 走索引 `0.067 ms/次`；`kodi.log` 0 报错 / 0 `Errno 98` |
| Batch 1.2 | `/picture/` 307 补齐 `tag`/`maxWidth`/`quality` + 并发 Keep-Alive 海报预缓存 + JPEG/WebP 解析修复 | `hooks/webservice.py`, `helper/artworkcache.py`（累计 `+44` 行） | `ce_opt/artwork.py` | `ce_opt.json`: `PICTURE_REDIRECT_OPT` / `PICTURE_RESIZE_ENABLED` / `ARTWORK_CACHE_CONCURRENT` | 海报 `id=885750` 经 `127.0.0.1:57342` 体积 `1,143 KB → 89.4 KB`（`-92.2%`），热耗时 `73.9 ms → 8.5 ms`（`8.7×`）；ClearLogo 保留 PNG 透明通道（`55.5 KB` / `7.8 ms`）；Backdrop `443.7 KB` / `12.1 ms` |
| Batch 1.3 | HTTP STRM 快路径（免阻塞 HEAD 探测 + 局域网 302 网关直连 307） | `hooks/webservice.py`（累计 `+50` 行） | `ce_opt/strm.py` | `ce_opt.json`: `STRM_FAST_PATH` / `STRM_SKIP_REMOTE_HEAD` / `STRM_LAN_DIRECT_REDIRECT` | 保持 `http://127.0.0.1:57342/http/...` 契约兼容 YoPlayer `embypath.py`；规避远程 HEAD 302/超时误触发 HLS 转码 |
| Batch 2.1 | 扫库去冗余（关主题曲跳过 Theme 队列 + 进度条 250ms 节流 + 关联表批量查写 + 演员 `art` 去重 + 过滤无图 5 分钟假章节 + `PersonPaging` 限幅） | `movies.py`, `series.py`, `common.py`, `person.py`, `utils.py`, `api.py`（累计 `+91` 行） | `ce_opt/sync_fast.py` | `ce_opt.json`: `SYNC_SKIP_DISABLED_THEMES` / `SYNC_THROTTLE_PROGRESS` / `SYNC_BATCH_LINKS` / `SYNC_DEDUP_PERSON_ART` / `SYNC_SKIP_NOIMAGE_CHAPTERS` / `SYNC_PERSON_PAGING_OPT` | 全库省 ~1,000 次无意义 `ThemeMedia` 请求；100% 保留 `IntroStart`/`IntroEnd`/`CreditsStart` 去片头片尾标记；演员 `art` 冗余行减少 ~67% |
| Batch 2.2 | 启动增量同步 `KodiStartSync` 信任 Kodi Companion 空结果快路径 | `database/library.py`（累计 `+100` 行） | `ce_opt/sync_fast.py` | `ce_opt.json`: `SYNC_TRUST_COMPANION_EMPTY` / `SYNC_COMPANION_EMPTY_TYPES` | 无变更重启时查询从 `88` 次降至 `12` 次（`-86.4%`），耗时 `~700 ms → 143~147 ms`（`~5×`） |
| 运维清理（用户授权） | 清理旧版 11.x 残留缩略图与 `Textures13.db` 压缩 | —（不改动代码） | — | 已备份 `/storage/backup/emby-dev/Textures13.db.bak.*` | 清理 `6,466` 个过期文件释放 **`735.5 MB`**；`Textures13.db` `5.20 MB → 0.48 MB`（`-90.8%`）；保留全部 `622` 个有效 12.x/皮肤缓存 |
| Batch 3.1 | `HDR10+` / `TrueHD Atmos` / `DD+ Atmos` / `DTS:X` 徽标映射 + 未探针 STRM 文件名兜底与播后 `streamdetails` 自动回填 | `core/common.py`, `helper/player.py`（累计 `+109` 行） | `ce_opt/stream_meta.py` | `ce_opt.json`: `STREAM_META_ENHANCED` / `STREAM_STRM_NAME_FALLBACK` / `STREAM_PLAYBACK_BACKFILL` | 精准对齐 `skin.yoplayer.infuse` 徽标词表；未探针 STRM 首次播放后自动补全 Kodi `streamdetails`，不覆盖已有实测流 |
| Batch 3.2 | 事件驱动 `interruptible_sleep` 与空闲后台轮询线程收敛 | `utils.py`, `monitor.py`, `themes.py`, `webservice.py`, `favorites.py`, `artworkcache.py`（累计 `+123` 行） | `ce_opt/idle_opt.py` | `ce_opt.json`: `IDLE_WAKEUP_OPT` / `IDLE_*_SEC` | `kodi.bin` 待机自愿上下文切换 **`1,583.0/s → 1,044.7/s`**（**`-34.0%`**）；关机/重启 `<1 ms` 立即唤醒退出；21/21 单元测试通过 |
| Hotfix `ce.2` | 修复预缓存选「全部」卡顿 UI（256 表查表法 `fast_kodi_hash` 提速 ~20× + 跳过无图 `noimage` 书签 + Pillow 水印串行让出 GIL + 预处理实时进度与秒取消） | `helper/utils.py`（累计 `+126` 行） | `ce_opt/artwork.py`, `ce_opt/config.py` | `ce_opt.json`: `ARTWORK_CACHE_SKIP_NOIMAGE` / `ARTWORK_FAST_KODI_HASH` | 消除 5.5 万条哈希 3 分钟阻塞与 Pillow 抢 GIL 卡死遥控器；22/22 单元测试通过（逐比特对齐原版 `kodi_hash`） |

## 全阶段实测基准汇总（CoreELEC `192.168.1.123`）

| 指标 | 上游 12.4.24 基线 | YoEmby（Batch 1 + 2 + 3） | 变化 |
| :--- | :--- | :--- | :--- |
| 海报 `885750` 经本地 57342 传输体积 | `1,143 KB`（原图） | **`89.4 KB`**（`maxWidth=600&quality=85`） | **`-92.2%`** |
| 海报 `885750` 经本地 57342 热请求耗时 | `73.9 ms` | **`8.5 ms`**（含 `tag` 强缓存） | **`8.7×` 提速** |
| 背景图 `885750`（`maxWidth=1920&quality=85`） | 原图未限宽 | `443.7 KB` / `12.1 ms` | 4K 观感与速度兼顾 |
| ClearLogo `885750`（`maxWidth=800`，无 `quality`） | 原图未限宽 | `55.5 KB` (`image/png`) / `7.8 ms` | 保持 PNG 透明通道 |
| `emby_*.db` `Episode WHERE KodiId=?` 查询计划 | `SCAN Episode`（全表扫描） | **`SEARCH ... USING INDEX idx_Episode_KodiId`**（`0.067 ms/次`） | 消除全表扫描 |
| 启动增量同步 `KodiStartSync`（无变更） | `88` 次查询 / `~700 ms` | **`12` 次查询 / `143~147 ms`** | **`-86.4%` 请求 / `~5×` 提速** |
| `kodi.bin` 待机自愿上下文切换率 | `1,583.0 /s` | **`1,044.7 /s`** | **`-34.0%`（`-538/s`）** |
| `kodi.bin` 内存常驻（VmRSS） | `766 MB` | **`607.6 MB`** | **`-158 MB`** |
| 旧版 11.x 残留缩略图 & `Textures13.db` | `774.1 MB` / `5.20 MB` | **`38.6 MB`（保留有效）/ `0.48 MB`** | 释放 **`735.5 MB`** |
| 启动 `kodi.log` 插件报错 / `Errno 98` | 存在 `Errno 98` | **`0` 报错 / `0` `Errno 98`** | 干净启动 |
| 上游文件总 Diff 规模 | `0` | 17 个上游文件共 `+123` 行（全部收口到 `ce_opt/`） | 极小侵入 |
