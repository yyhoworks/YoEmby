# -*- coding: utf-8 -*-
"""YoEmby Health Checkup Dashboard (WindowXMLDialog controller).

Drop this module into YoEmby and ship the fallback skin XML under:
  resources/skins/default/1080i/script-yoemby-health.xml

When YoPlayer skin (skin.yoplayer.infuse) is active, Kodi automatically uses
YoPlayer's frosted glass override `1080p/script-yoemby-health.xml`.
"""
import re

try:
    import xbmc
    import xbmcgui
except ImportError:  # Allow importing pure helpers & unit testing outside Kodi
    xbmc = None  # type: ignore[assignment]
    xbmcgui = None  # type: ignore[assignment]

XML_FILENAME = 'script-yoemby-health.xml'

CTRL_TITLE = 1001
CTRL_SUMMARY = 1002
CTRL_FOOTER_HINT = 1003
CTRL_CLOSE = 1009
CTRL_TAB_IDS = (1101, 1102, 1103)
CTRL_CARD_PANEL = 2000
CTRL_REFRESH = 3001
CTRL_RAW_REPORT = 3002

ACTION_PREVIOUS_MENU = 10
ACTION_NAV_BACK = 92
ACTION_PAGE_UP = 5
ACTION_PAGE_DOWN = 6

_BASE_WINDOW_DIALOG = xbmcgui.WindowXMLDialog if xbmcgui is not None else object


def _quantize_percent(value):
    if value is None or value == '':
        return ''
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return ''
    if numeric <= 0:
        return ''
    step = int(round(numeric / 10.0) * 10)
    step = max(10, min(100, step))
    return str(step)


def _extract_mb(text, pattern):
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return 0.0, ''
    value = float(match.group(1))
    unit = match.group(2).upper() if match.lastindex and match.lastindex >= 2 and match.group(2) else 'MB'
    if unit == 'GB':
        value *= 1024.0
    return value, match.group(0)


def _extract_int(text, pattern, default=0):
    match = re.search(pattern, text, re.IGNORECASE)
    return int(match.group(1)) if match else default


def _extract_str(text, pattern, default=''):
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else default


def parse_legacy_report_text(raw_text):
    """Parse YoEmby's plain-text CoreELEC health checkup report into 3 dashboard pages."""
    text = raw_text or ''
    ce_enabled = _extract_str(text, r'ce_enabled\s*[:：]\s*([^\s|｜]+)', '开启')
    multi_ver = _extract_str(text, r'多版本策略\s*[:：]\s*([^\s|｜]+)', 'prefer_local')

    myvideos_mb, _ = _extract_mb(text, r'MyVideos\s*DB\s*[:：]\s*([\d.]+)\s*(GB|MB)')
    emby_mb, _ = _extract_mb(text, r'Emby\s*DB\s*[:：]\s*([\d.]+)\s*(GB|MB)')
    textures_mb, _ = _extract_mb(text, r'Textures\s*DB\s*[:：]\s*([\d.]+)\s*(GB|MB)')
    thumbs_mb, _ = _extract_mb(text, r'Thumbnails\s*[:：]\s*([\d.]+)\s*(GB|MB)')
    thumbs_files = _extract_int(text, r'Thumbnails\s*[:：][^\n]*?\((\d+)\s*文件\)')
    temp_mb, _ = _extract_mb(text, r'addon\s*temp/?\s*[:：]\s*([\d.]+)\s*(GB|MB)')
    temp_files = _extract_int(text, r'addon\s*temp/?\s*[:：][^\n]*?\((\d+)\s*文件\)')
    rollback_mb, _ = _extract_mb(text, r'rollback/?\s*[:：]\s*([\d.]+)\s*(GB|MB)')
    rollback_files = _extract_int(text, r'rollback/?\s*[:：][^\n]*?\((\d+)\s*文件\)')

    db_total = round(myvideos_mb + emby_mb + textures_mb, 1)
    total_mb = round(db_total + thumbs_mb + temp_mb + rollback_mb, 1)
    total_display = '{:.2f} GB'.format(total_mb / 1024.0) if total_mb >= 1024.0 else '{:.1f} MB'.format(total_mb)

    idx_cur = _extract_int(text, r'Emby\s*增量索引\s*[:：]\s*(\d+)\s*/\s*\d+')
    idx_tot = _extract_int(text, r'Emby\s*增量索引\s*[:：]\s*\d+\s*/\s*(\d+)')
    total_items = _extract_int(text, r'媒体源分布\s*[:：]\s*总\s*(\d+)')
    smb_items = _extract_int(text, r'SMB\s*(\d+)')
    strm_items = _extract_int(text, r'HTTP\s*STRM\s*(\d+)')
    missing_streams = _extract_int(text, r'Emby\s*缺流条目\s*[:：]\s*(\d+)')

    optimizable = int(missing_streams > 0) + int(rollback_mb > 0)
    idx_ok = idx_tot > 0 and idx_cur >= idx_tot
    idx_label = '{} / {}'.format(idx_cur, idx_tot) if idx_tot else '未检测'

    summary = '总存储 {} · 增量索引 {} · {} 项可优化'.format(
        total_display,
        '{} 健康'.format(idx_label) if idx_ok else idx_label,
        optimizable,
    )

    denom = total_mb if total_mb > 0 else 1.0
    strm_pct = round(strm_items * 100.0 / total_items, 1) if total_items > 0 else 0.0
    idx_pct = round(idx_cur * 100.0 / idx_tot, 1) if idx_tot > 0 else 0.0
    missing_pct = min(100, round(missing_streams * 100.0 / max(1, strm_items or total_items), 1)) if missing_streams else 0

    storage_cards = [
        {
            'title': 'Thumbnails 缩略图缓存',
            'value': '{:.1f} MB'.format(thumbs_mb),
            'detail': '{} 个文件 · 占总存储 {:.1f}%'.format(thumbs_files, thumbs_mb * 100.0 / denom),
            'badge': '正常缓存',
            'tone': 'info',
            'percent': thumbs_mb * 100.0 / denom,
        },
        {
            'title': 'Kodi & Emby 数据库',
            'value': '{:.1f} MB'.format(db_total),
            'detail': 'MyVideos {:.1f} · Emby {:.1f} · Textures {:.1f} MB'.format(
                myvideos_mb, emby_mb, textures_mb
            ),
            'badge': '结构健康',
            'tone': 'ok',
            'percent': max(10.0, db_total * 100.0 / denom) if db_total > 0 else 0,
        },
        {
            'title': 'addon temp/ 临时缓存',
            'value': '{:.1f} MB'.format(temp_mb),
            'detail': '{} 个临时文件 · 运行期缓存'.format(temp_files),
            'badge': '正常',
            'tone': 'info',
            'percent': max(10.0, temp_mb * 100.0 / denom) if temp_mb > 0 else 0,
        },
        {
            'title': 'rollback/ 旧插件备份',
            'value': '{:.1f} MB'.format(rollback_mb),
            'detail': '{} 个历史备份文件'.format(rollback_files),
            'badge': '可优化' if rollback_mb > 0 else '已清空',
            'tone': 'warn' if rollback_mb > 0 else 'ok',
            'percent': max(10.0, rollback_mb * 100.0 / denom) if rollback_mb > 0 else 0,
            'action_id': 'clean_rollback' if rollback_mb > 0 else '',
            'action_label': '按确定：清理旧插件备份 ›' if rollback_mb > 0 else '',
        },
    ]

    library_cards = [
        {
            'title': 'Emby 增量覆盖索引',
            'value': idx_label,
            'detail': '所有媒体库索引覆盖正常' if idx_ok else '建议核对并补建增量索引',
            'badge': '完全健康' if idx_ok else '待核对',
            'tone': 'ok' if idx_ok else 'warn',
            'percent': idx_pct,
            'action_id': 'rebuild_index',
            'action_label': '按确定：核对 / 补建索引 ›',
        },
        {
            'title': '媒体源分布（总 {}）'.format(total_items),
            'value': '{:.1f}% STRM'.format(strm_pct) if total_items else '0',
            'detail': 'HTTP STRM {} 条 · 本地/SMB {} 条'.format(strm_items, smb_items),
            'badge': multi_ver,
            'tone': 'info',
            'percent': strm_pct,
        },
        {
            'title': 'Emby 缺流条目',
            'value': '{} 条'.format(missing_streams),
            'detail': '补齐后可改善音轨、字幕预选与媒体标识' if missing_streams else '全部条目流信息完整',
            'badge': '建议补齐' if missing_streams else '完整',
            'tone': 'warn' if missing_streams else 'ok',
            'percent': max(20.0, missing_pct) if missing_streams else 100,
            'action_id': 'fix_missing_streams' if missing_streams else '',
            'action_label': '按确定：批量补齐 STRM 缺流 ›' if missing_streams else '',
        },
        {
            'title': 'CoreELEC 优化总开关',
            'value': ce_enabled,
            'detail': '多版本选源策略：{}'.format(multi_ver),
            'badge': '运行中' if ce_enabled in ('开启', 'on', 'true', '1') else '未开启',
            'tone': 'ok' if ce_enabled in ('开启', 'on', 'true', '1') else 'warn',
            'percent': 100 if ce_enabled in ('开启', 'on', 'true', '1') else 10,
        },
    ]

    action_cards = [
        {
            'title': '维护 1 · 批量补齐 STRM 缺流',
            'value': '{} 条待补'.format(missing_streams) if missing_streams else '无需补齐',
            'detail': '仅处理已播或缺少流信息的 STRM 条目',
            'badge': '推荐执行' if missing_streams else '已完成',
            'tone': 'warn' if missing_streams else 'ok',
            'percent': 70 if missing_streams else 100,
            'action_id': 'fix_missing_streams',
            'action_label': '按确定：开始批量补齐 ›',
        },
        {
            'title': '维护 2 · 清理 rollback/ 备份',
            'value': '释放 {:.1f} MB'.format(rollback_mb) if rollback_mb > 0 else '无需清理',
            'detail': '安全移除 {} 个旧插件历史文件'.format(rollback_files),
            'badge': '安全清理' if rollback_mb > 0 else '已清空',
            'tone': 'warn' if rollback_mb > 0 else 'ok',
            'percent': 30 if rollback_mb > 0 else 100,
            'action_id': 'clean_rollback',
            'action_label': '按确定：立即清理备份 ›',
        },
        {
            'title': '维护 3 · 核对 / 补建增量索引',
            'value': idx_label,
            'detail': '检查并修复 Emby 增量同步覆盖索引',
            'badge': '健康' if idx_ok else '需核对',
            'tone': 'ok' if idx_ok else 'warn',
            'percent': idx_pct or 100,
            'action_id': 'rebuild_index',
            'action_label': '按确定：立即核对索引 ›',
        },
        {
            'title': '维护 4 · 查看完整原始体检文本',
            'value': '原始报告',
            'detail': '以纯文本阅读器查看完整诊断输出',
            'badge': '诊断详情',
            'tone': 'info',
            'percent': 100,
            'action_id': 'raw_report',
            'action_label': '按确定：打开文本阅读器 ›',
        },
    ]

    return {
        'title': 'YoEmby 健康体检仪表盘',
        'summary': summary,
        'pages': [
            {'title': '1. 存储分布', 'cards': storage_cards},
            {'title': '2. 媒体库与流信息', 'cards': library_cards},
            {'title': '3. 维护与一键修复', 'cards': action_cards},
        ],
    }


class YoEmbyHealthDashboard(_BASE_WINDOW_DIALOG):
    """3-page 2x2 metric & maintenance card dialog for YoEmby."""

    def __init__(self, *args, **kwargs):
        self._data = kwargs.pop('report_data', None) or {}
        self._raw_text = kwargs.pop('raw_text', '') or ''
        self._actions = dict(kwargs.pop('actions', None) or {})
        self._page = 0
        if _BASE_WINDOW_DIALOG is not object:
            super(YoEmbyHealthDashboard, self).__init__(*args, **kwargs)
        else:
            super(YoEmbyHealthDashboard, self).__init__()

    def onInit(self):
        self._apply_header_and_tabs()
        self._render_page(self._page)
        self.setFocusId(CTRL_CARD_PANEL)

    def _pages(self):
        pages = self._data.get('pages') or []
        return pages[:3]

    def _apply_header_and_tabs(self):
        title = self._data.get('title') or 'YoEmby 健康体检仪表盘'
        summary = self._data.get('summary') or ''
        self._set_label(CTRL_TITLE, title)
        self._set_label(CTRL_SUMMARY, summary)
        pages = self._pages()
        for idx, ctrl_id in enumerate(CTRL_TAB_IDS):
            if idx < len(pages):
                self._set_label(ctrl_id, pages[idx].get('title') or '第 {} 页'.format(idx + 1))

    def _set_label(self, ctrl_id, text):
        try:
            ctrl = self.getControl(ctrl_id)
            ctrl.setLabel(str(text))
        except Exception:
            pass

    def _render_page(self, page_index):
        pages = self._pages()
        if not pages:
            return
        self._page = page_index % len(pages)
        self.setProperty('YoEmby.Page', str(self._page))
        self._set_label(
            CTRL_FOOTER_HINT,
            '← → 切换分页（第 {} / {} 页）· 确定执行维护 · 返回退出'.format(self._page + 1, len(pages)),
        )
        panel = self.getControl(CTRL_CARD_PANEL)
        panel.reset()
        cards = pages[self._page].get('cards') or []
        for card in cards[:4]:
            item = xbmcgui.ListItem(
                label=str(card.get('title') or ''),
                label2=str(card.get('detail') or ''),
            )
            item.setProperty('value', str(card.get('value') or ''))
            item.setProperty('badge', str(card.get('badge') or ''))
            item.setProperty('tone', str(card.get('tone') or 'info'))
            item.setProperty('meter_step', _quantize_percent(card.get('percent')))
            item.setProperty('action_id', str(card.get('action_id') or ''))
            item.setProperty('action_label', str(card.get('action_label') or ''))
            panel.addItem(item)

    def _run_action(self, action_id):
        if not action_id:
            return
        if action_id == 'raw_report':
            self._open_raw_report()
            return
        callback = self._actions.get(action_id)
        if not callable(callback):
            return
        result = callback()
        if action_id == 'refresh':
            self._ingest_refresh_result(result)
        elif callable(self._actions.get('refresh')):
            self._ingest_refresh_result(self._actions['refresh']())

    def _ingest_refresh_result(self, result):
        if isinstance(result, tuple) and len(result) == 2:
            data_part, raw_part = result
            if isinstance(data_part, dict):
                self._data = data_part
            if isinstance(raw_part, str) and raw_part.strip():
                self._raw_text = raw_part
        elif isinstance(result, dict):
            self._data = result
            raw_in_dict = result.get('raw_text')
            if isinstance(raw_in_dict, str) and raw_in_dict.strip():
                self._raw_text = raw_in_dict
        elif isinstance(result, str) and result.strip():
            self._raw_text = result
            self._data = parse_legacy_report_text(result)
        self._apply_header_and_tabs()
        self._render_page(self._page)

    def _open_raw_report(self):
        heading = self._data.get('title') or 'YoEmby 健康体检报告'
        body = self._raw_text or self._data.get('summary') or '暂无原始报告内容'
        xbmcgui.Dialog().textviewer(heading, body)

    def onFocus(self, control_id):
        if control_id in CTRL_TAB_IDS:
            idx = CTRL_TAB_IDS.index(control_id)
            if idx != self._page:
                self._render_page(idx)

    def onClick(self, control_id):
        if control_id == CTRL_CLOSE:
            self.close()
        elif control_id in CTRL_TAB_IDS:
            self._render_page(CTRL_TAB_IDS.index(control_id))
            self.setFocusId(CTRL_CARD_PANEL)
        elif control_id == CTRL_REFRESH:
            self._run_action('refresh')
        elif control_id == CTRL_RAW_REPORT:
            self._open_raw_report()
        elif control_id == CTRL_CARD_PANEL:
            item = self.getControl(CTRL_CARD_PANEL).getSelectedItem()
            if item is not None:
                self._run_action(item.getProperty('action_id'))

    def onAction(self, action):
        action_id = action.getId()
        if action_id in (ACTION_PREVIOUS_MENU, ACTION_NAV_BACK):
            self.close()
        elif action_id == ACTION_PAGE_UP:
            self._render_page(self._page - 1)
        elif action_id == ACTION_PAGE_DOWN:
            self._render_page(self._page + 1)


def open_health_dashboard(addon_path, report_data=None, raw_text='', actions=None):
    """Open YoEmby Health Dashboard (uses YoPlayer glass override automatically)."""
    data = report_data if isinstance(report_data, dict) else parse_legacy_report_text(raw_text)
    dialog = YoEmbyHealthDashboard(
        XML_FILENAME,
        addon_path,
        'default',
        '1080i',
        report_data=data,
        raw_text=raw_text,
        actions=actions,
    )
    dialog.doModal()
    del dialog
