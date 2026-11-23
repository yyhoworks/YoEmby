# YoEmby CoreELEC 定制改动账本

基线 Tag：`upstream-12.4.24`（提交 `39aacb6`）  
目标环境：CoreELEC 21.3 / Amlogic S905X4 / YoLink STRM / YoPlayer·Infuse

## 改动总览

| 批次 | 主题 | 触碰上游文件 | 新增 `ce_opt/` 模块 | 回退 / 开关 | 实测效果 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 基线 | 品牌更名与工程守卫 | `addon.xml`（仅 `name`/`provider-name`/`source`，锁死 `id`/`version`） | — | `git checkout upstream-12.4.24` | 建好 `AGENTS.md` 与 `verify_guardrails.py` 自动拦截 |
| Batch 1.1 | 修复上游 5 处 Bug + `emby_*.db` `KodiId` 索引 + SQLite RW 缓存 | `video_db.py`, `dbio.py`, `emby_db.py`, `player.py`, `webservice.py`（共 `+25` 行） | `ce_opt/config.py`, `ce_opt/db_indexes.py` | `ce_opt.json`: `ENABLED` / `EXTRA_EMBY_INDEXES` / `DB_RW_CACHE_KB` | 启动自动增量创建 6 个 `KodiId`/`KodiFileId` 索引；`Episode WHERE KodiId=?` 走索引 `0.067 ms/次`；`kodi.log` 0 报错 / 0 `Errno 98` |
| Batch 1.2 | `/picture/` 307 补齐 `tag`/`maxWidth`/`quality` + 并发 Keep-Alive 海报预缓存 + JPEG/WebP 解析修复 | `hooks/webservice.py`, `helper/artworkcache.py`（累计 `+44` 行） | `ce_opt/artwork.py` | `ce_opt.json`: `PICTURE_REDIRECT_OPT` / `PICTURE_RESIZE_ENABLED` / `ARTWORK_CACHE_CONCURRENT` | 海报 `id=885750` 经 `127.0.0.1:57342` 体积 `1,143 KB → 89.4 KB`（`-92.2%`），热耗时 `73.9 ms → 8.5 ms`（`8.7×`）；ClearLogo 保留 PNG 透明通道（`55.5 KB` / `7.8 ms`）；Backdrop `443.7 KB` / `12.1 ms` |
| Batch 1.3 | HTTP STRM 快路径（免阻塞 HEAD 探测 + 局域网 302 网关直连 307） | `hooks/webservice.py`（累计 `+50` 行） | `ce_opt/strm.py` | `ce_opt.json`: `STRM_FAST_PATH` / `STRM_SKIP_REMOTE_HEAD` / `STRM_LAN_DIRECT_REDIRECT` | 保持 `http://127.0.0.1:57342/http/...` 契约兼容 YoPlayer `embypath.py`；规避远程 HEAD 302/超时误触发 HLS 转码；单元测试 10/10 通过 |

## Batch 1 实测基准明细（CoreELEC `192.168.1.123`）

| 指标 | 上游 12.4.24 基线 | YoEmby Batch 1 | 变化 |
| :--- | :--- | :--- | :--- |
| 海报 `885750` 经本地 57342 传输体积 | `1,143 KB`（原图） | `89.4 KB`（`maxWidth=600&quality=85`） | **`-92.2%`** |
| 海报 `885750` 经本地 57342 热请求耗时 | `73.9 ms` | `8.5 ms`（含 `tag` 强缓存） | **`8.7×` 提速** |
| 背景图 `885750` 经本地 57342（`maxWidth=1920&quality=85`） | 原图未限宽 | `443.7 KB` / `12.1 ms` | 4K 观感与速度兼顾 |
| ClearLogo `885750` 经本地 57342（`maxWidth=800`，无 `quality`） | 原图未限宽 | `55.5 KB` (`image/png`) / `7.8 ms` | 保持 PNG 透明通道 |
| `emby_*.db` `Episode WHERE KodiId=?` 查询计划 | `SCAN Episode`（全表扫描） | `SEARCH Episode USING INDEX idx_Episode_KodiId`（`0.067 ms/次`） | 消除全表扫描 |
| 启动 `kodi.log` 插件报错 / `Errno 98` | 存在 `Errno 98` | `0` 报错 / `0` `Errno 98` | 干净启动 |
| 上游文件总 Diff 规模 | `0` | 7 个上游文件共 `+50` 行（全部收口到 `ce_opt/`） | 极小侵入 |
