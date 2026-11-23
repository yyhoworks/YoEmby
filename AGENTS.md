# YoEmby 项目工程规则（AGENTS.md）

本文件是 `YoEmby` 仓库的最高约束，所有协作与改动必须严格遵守。

---

## 1. 绝对作用域边界（严禁改动 CE 与 UI）

- **唯一允许修改的目录**：
  - `plugin.service.emby-next-gen/`（核心插件代码）
  - `scripts/`（校验、巡检、部署脚本）
  - `docs/`（审计、变更账本与说明文档）
  - `tests/`（本地单元测试）
- **严禁改动（零例外）**：
  - CoreELEC 系统文件（`/flash`、`/storage/.config`、内核、驱动、systemd 服务等）。
  - YoPlayer 相关任何插件与皮肤（`skin.yoplayer.infuse`、`plugin.video.yoplayer.home`）。
  - Emby 服务端及任何第三方 Kodi 插件。
- **SSH 远端操作纪律**：
  - 对 CoreELEC 主机（`yoplayer-ce` / `192.168.1.123`）默认**只读采集**（日志、SQLite `?mode=ro`、性能基准）。
  - 远端写操作仅允许通过 `scripts/deploy_to_ce.ps1` 部署 `plugin.service.emby-next-gen`；修改盒子上用户配置（`settings.xml`、`guisettings.xml`）或清理缓存目录前，**必须先获得用户明确确认**。

---

## 2. 不可破坏的 YoPlayer 契约红线

`skin.yoplayer.infuse` 与 `plugin.video.yoplayer.home` 有 9 处硬编码依赖本插件，必须 100% 兼容：

1. **ID 与版本号锁死**：
   - `addon.xml` 的 `id` 必须保持 `plugin.service.emby-next-gen`。
   - `addon.xml` 的 `version` 必须锁定为 `12.4.24`（留在 `emby_rating.py`、`infuse_rating.py`、`infuse_watched.py`、`infuse_network_tools.py` 的 `VERIFIED_VERSIONS` 白名单内；除非用户明确要求升级并同步处理白名单，否则禁止修改）。
   - `addon.xml` 的显示名 `name` 保持纯 ASCII 的 `YoEmby`（兼顾 Kodi UI 与 HTTP `User-Agent` / `Emby Client` 头）。
2. **数据库 Schema 契约**：
   - 严禁修改、删除或重命名 `emby_*.db` 中 `Movie`、`Video`、`Series`、`Season`、`Episode`、`MediaSources`、`VideoStreams`、`AudioStreams`、`Subtitles`、`LibrarySynced`、`EmbyLibraryMapping` 的已有表名与列名。
   - **允许**纯增量添加 `CREATE INDEX IF NOT EXISTS ...` 索引。
3. **评分与节点契约**：
   - `CommunityRating` 继续写入 Kodi `default`（开启 `imdbrating` 时为 `imdb`）；`CriticRating / 10.0` 继续写入 `tomatometerallcritics`。
   - 保持 `special://profile/library/video/emby_(dynamic_)?(movies|tvshows|musicvideos)_*/` 下 `all.xml` / `index.xml` 契约不变。
   - 保持 `special://profile/addon_data/plugin.service.emby-next-gen/temp/` 封面目录路径不变。
4. **路径编码契约**：
   - 保持 `http://127.0.0.1:57342/http/...` 路径结构兼容 YoPlayer 的 `embypath.py` 解码逻辑。

---

## 3. 防屎山化架构铁律（上游最小侵入 + `ce_opt/` 收口）

1. **定制逻辑全部收口到 `plugin.service.emby-next-gen/ce_opt/`**：
   - 按职责拆分为小而纯的模块（如 `config.py`、`artwork.py`、`strm.py`、`sync_fast.py`、`stream_meta.py`），单模块职责单一、可脱离 Kodi 独立单测。
2. **上游文件最小 Diff**：
   - 修改上游官方文件（如 `webservice.py`、`library.py`、`common.py`、`player.py`、`video_db.py`、`emby_db.py`）时，除精准修 Bug 外，**只允许插入 1~5 行钩子调用**，严禁在上游大函数内堆积大段嵌套逻辑或复制粘贴代码。
   - 单次对单个上游文件净增超过 80 行时，必须先拆分到 `ce_opt/`。
3. **统一标记，便于合并上游升级**：
   - 上游文件每处修改必须附带 `# [CE-OPT] <简短原因>` 注释；随时可通过 `git diff upstream-12.4.24..HEAD --stat` 清晰审计全部改动。
4. **可开关、可降级、零重依赖**：
   - 仅使用 Kodi 内置 Python 标准库与原插件已有依赖，禁止引入外部重依赖。
   - 禁止新增常驻高频轮询线程（优先事件驱动或长超时等待）。
   - 涉及行为变化的功能优化必须在 `ce_opt/config.py` 提供明确开关，关闭即可无缝退回上游默认行为。

---

## 4. 开发粒度与验证闭环

1. **一主题一提交**：每次只落地一个清晰主题（例如“修复上游 Bug”、“海报 307 与预缓存”、“扫库去冗余”），不将无关改动混入同一 Commit。
2. **先校验后部署**：任何改动提交或部署前，**必须通过** `python scripts/verify_guardrails.py`（检查版本锁、表契约、语法、无敏感文件、上游 Diff 规模、单元测试）。
3. **禁止盲改，指标说话**：每批优化部署到 CoreELEC 后，必须用日志/实测数据记录改动前后对比，并更新 `docs/CE_CHANGES.md`。
4. **严禁泄露凭证**：任何代码、日志、文档与提交记录中严禁包含 AccessToken、密码、公网 IP 或敏感路径凭据。
