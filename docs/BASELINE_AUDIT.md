# CoreELEC 基线审计与 YoPlayer 契约说明

采集日期：2026-11-23  
基线版本：`plugin.service.emby-next-gen` **v12.4.24**（配套 `video/audio/image` **v10.1.2**）

---

## 1. 升级前后数据库对比（无损验证记录）

| 指标 | 升级前 (`11.1.27`) | 升级后 (`12.4.24`) | 变化说明 |
| :--- | ---: | ---: | :--- |
| `MyVideos131.db` 体积 | 425.3 MB | **126.7 MB** | 重建去除了历史碎片与膨胀 |
| `emby_*.db` 体积 | 14.3 MB | 24.1 MB | 12.x 新结构，全量重扫耗时约 4 分钟 |
| 同步分库数 | 12 个 | 12 个 | 完全一致 |
| 电影 (`movie`) | 803 | 803 | 100% 一致 |
| 剧集 (`tvshow`) | 191 | 192 | +1（补全此前漏同步条目） |
| 单集 (`episode`) | 7,809 | 7,819 | +10 |
| 已看记录 (`playCount > 0`) | 4,390 | 4,393 | +3 |
| 断点续播 (`bookmark type=1`) | 100 | 99 | -1 |
| 评分总数 (`rating`) | 8,057 | 8,176 | +119 |
| 烂番茄影评 (`tomatometerallcritics`) | 526 | 530 | +4 |
| 含流信息文件 (`streamdetails`) | 8,113 | 8,093 | -20（12.x 清理了部分无效 STRM 空流） |

---

## 2. 修改插件时不可破坏的 YoPlayer 契约红线

后续对 `plugin.service.emby-next-gen` 做任何重构或优化，**必须保持以下 4 项契约兼容**（否则会触发 YoPlayer 降级）：

1. **评分契约**（`plugin.video.yoplayer.home/resources/lib/emby_rating.py`）
   - `addon.xml` 的 `version` 必须在 `emby_rating.py` 的 `VERIFIED_VERSIONS` 白名单内（若修改本插件版本号，需同步更新 YoPlayer 白名单）。
   - `CommunityRating` 仍写入 Kodi `default`（开启 `imdbrating` 时写为 `imdb`）；`CriticRating / 10.0` 仍写入 `tomatometerallcritics`。
   - `emby_*.db` 中 `Movie`/`Video`/`Series`/`Episode` 表的 `EmbyId`、`KodiId`、`KodiFileId`、`KodiPathId` 列名与语义不可破坏。
2. **开播前选轨契约**（`skin.yoplayer.infuse/scripts/infuse_preplay.py`）
   - 读取 `emby_*.db` 的 `MediaSources (EmbyId, MediaSourceId, Path)`、`AudioStreams (EmbyId, StreamIndex, DisplayTitle, Codec)`、`Subtitles (EmbyId, StreamIndex, DisplayTitle, Codec, Language, External)`。
3. **分库节点目录契约**（`plugin.video.yoplayer.home/resources/lib/catalog.py`）
   - 依赖 `special://profile/library/video/emby_(dynamic_)?(movies|tvshows|musicvideos)_*/` 下的 `all.xml` 与 `index.xml`。
4. **分库本地封面目录契约**（`plugin.video.yoplayer.home/resources/lib/library_art.py`）
   - 依赖 `special://profile/addon_data/plugin.service.emby-next-gen/temp/` 路径。

---

## 3. 已发现的待优化点清单

- **同步抢占播放资源**：当前 `settings.xml` 中 `PauseSyncDuringPlayback=false`、`syncduringplayback=true`。
- **STRM 网络超时过短**：当前 `curltimeouts=5`（`advancedsettings.xml` `<curlclienttimeout>5</curlclienttimeout>`），网盘 302 跳转易触发超时；Kodi `filecache.memorysize` 目前仅 `64 MB`（机器空闲可用内存约 `1.8 GB`）。
- **直连模式冗余开销**：当前 `useDirectPaths=true` 直连 `/CloudNAS/MVStrm/...`，但默认开启了 5 个 `WebserviceWorkers` 及本地预告片/MV 关联同步。
- **部分 `.strm` 缺少媒体流信息**：同步日志中部分剧集提示 `No mediastreams found`，可结合服务端探测或播后回写机制优化。
- **内存基线**：同步结束后 `kodi.bin` 占约 `1.6 GB`（44.6%），可结合模块懒加载和缓存上限进一步观测。
