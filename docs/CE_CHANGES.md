# YoEmby CoreELEC 定制改动账本

基线 Tag：`upstream-12.4.24`（提交 `39aacb6`）  
目标环境：CoreELEC 21.3 / Amlogic S905X4 / YoLink STRM / YoPlayer·Infuse

## 改动总览

| 批次 | 主题 | 触碰上游文件 | 新增 `ce_opt/` 模块 | 回退 / 开关 | 实测效果 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 基线 | 品牌更名与工程守卫 | `addon.xml`（仅 `name`/`provider-name`/`source`，锁死 `id`/`version`） | — | `git checkout upstream-12.4.24` | 建好 `AGENTS.md` 与 `verify_guardrails.py` 自动拦截 |

> 后续每批优化落地并经实测验证后，按行追加记录。
