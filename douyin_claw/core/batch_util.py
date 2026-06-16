# coding=utf-8
"""多关键词搜索结果：相关性过滤、实体抽取、去重合并。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher

DEFAULT_ENTERPRISE_KEYWORDS: tuple[str, ...] = (
    '企业', '公司', '工厂', '厂房', '车间', '仓库', '园区', '集团', '有限公司', '生产',
)

COMPANY_PATTERNS = [
    re.compile(r'([^\s，,。；;：:#]{2,40}?(?:有限责任公司|股份有限公司|有限公司|集团公司|股份公司))'),
    re.compile(r'([^\s，,。；;：:#]{2,30}?(?:公司|工厂|企业|集团|园区)(?:[车间仓库厂房])?)'),
    re.compile(r'(?:位于|地处|在)([^\s，,。]{2,35}?(?:公司|工厂|企业|厂|园区))'),
    re.compile(
        r'((?:[\u4e00-\u9fff]{2,6}省)?'
        r'[^\s，,。]{0,12}(?:化工|工厂|企业))'
    ),
]

ADDRESS_PATTERNS = [
    re.compile(
        r'((?:[\u4e00-\u9fff]{2,10}[省市区县])'
        r'(?:[\u4e00-\u9fff]{1,10}[市区县镇乡街道村])?'
        r'(?:[\u4e00-\u9fff\d]{1,20}[路街道巷弄号楼栋层室园站])+)'
    ),
    re.compile(r'((?:[\u4e00-\u9fff]{2,8}[省市区县])[\u4e00-\u9fff\d]{2,30})'),
]

DATE_PATTERNS = [
    (re.compile(r'(\d{4})年(\d{1,2})月(\d{1,2})[日号]?'), 'ymd'),
    (re.compile(r'(\d{1,2})月(\d{1,2})[日号]'), 'md'),
    (re.compile(r'(\d{4})[./-](\d{1,2})[./-](\d{1,2})'), 'ymd_sep'),
]

REGION_PATTERN = re.compile(
    r'((?:[\u4e00-\u9fff]{2,6}省)?'
    r'(?:[\u4e00-\u9fff]{2,8}[市州])'
    r'(?:[\u4e00-\u9fff]{2,8}[县区镇乡])?)'
)


@dataclass(frozen=True)
class FilterKeywords:
    """描述相关性：须同时命中至少一个主题词与一个 enterprise 词。"""

    topic: tuple[str, ...]
    enterprise: tuple[str, ...] = DEFAULT_ENTERPRISE_KEYWORDS


def parse_keyword_csv(text: str) -> tuple[str, ...]:
    return tuple(k.strip() for k in text.split(',') if k.strip())


def months_ago_ts(months: float = 3) -> int:
    days = int(months * 30.5)
    return int((datetime.now() - timedelta(days=days)).timestamp())


def normalize_desc(text: str) -> str:
    if not text:
        return ''
    text = re.sub(r'#\S+', '', text)
    text = re.sub(r'@[^\s]+', '', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'\s+', '', text)
    return text


def is_relevant_incident(desc: str, keywords: FilterKeywords) -> bool:
    if not desc or not keywords.topic:
        return False
    has_topic = any(k in desc for k in keywords.topic)
    has_enterprise = any(k in desc for k in keywords.enterprise)
    return has_topic and has_enterprise


def extract_company(desc: str) -> str:
    for pat in COMPANY_PATTERNS:
        m = pat.search(desc)
        if m:
            name = m.group(1).strip('，,。：: ')
            if len(name) >= 4 and not name.startswith('#'):
                return name
    return ''


def extract_region(desc: str) -> str:
    m = REGION_PATTERN.search(desc)
    if m and len(m.group(1)) >= 4:
        return m.group(1).strip('，,。 ')
    return ''


def extract_address(desc: str) -> str:
    candidates = []
    region = extract_region(desc)
    if region:
        candidates.append(region)
    for pat in ADDRESS_PATTERNS:
        for m in pat.finditer(desc):
            addr = m.group(1).strip('，,。 ')
            if len(addr) >= 6 and '工厂' not in addr[-6:] and '企业' not in addr[-6:]:
                candidates.append(addr)
    if not candidates:
        return region
    return max(candidates, key=len)


def parse_event_date(desc: str, publish_ts: int = 0) -> str:
    now = datetime.now()
    year = now.year
    for pat, kind in DATE_PATTERNS:
        m = pat.search(desc)
        if not m:
            continue
        try:
            if kind == 'ymd':
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            elif kind == 'md':
                y = year
                mo, d = int(m.group(1)), int(m.group(2))
                if publish_ts:
                    y = datetime.fromtimestamp(publish_ts).year
            else:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= mo <= 12 and 1 <= d <= 31:
                return f'{y:04d}-{mo:02d}-{d:02d}'
        except (ValueError, IndexError):
            continue
    if publish_ts:
        return datetime.fromtimestamp(publish_ts).strftime('%Y-%m-%d')
    return ''


def format_publish_time(ts: int) -> str:
    if not ts:
        return ''
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')


def video_to_record(
    video: dict,
    cutoff_ts: int,
    keywords: FilterKeywords,
) -> dict | None:
    aweme_id = str(video.get('aweme_id') or '')
    desc = (video.get('desc') or video.get('title') or '').strip()
    create_time = int(video.get('create_time') or 0)
    if not aweme_id or not desc:
        return None
    if create_time < cutoff_ts:
        return None
    if not is_relevant_incident(desc, keywords):
        return None
    company = extract_company(desc)
    address = extract_address(desc)
    event_date = parse_event_date(desc, create_time)
    share_url = video.get('share_url') or f'https://www.douyin.com/video/{aweme_id}'
    return {
        'aweme_id': aweme_id,
        'desc': desc,
        'norm_desc': normalize_desc(desc),
        'company': company,
        'address': address,
        'event_date': event_date,
        'publish_time': format_publish_time(create_time),
        'publish_ts': create_time,
        'work_url': share_url,
        'nickname': video.get('author') or '',
    }


def merge_key(record: dict) -> str:
    region = extract_region(record['desc'])
    if record['company'] and record['event_date']:
        return f'{record["company"]}|{record["event_date"]}'
    if record['company'] and region:
        return f'{record["company"]}|{region}'
    if region and record['event_date']:
        return f'{region}|{record["event_date"]}'
    if record['company'] and record['address']:
        return f'{record["company"]}|{record["address"]}'
    return f'desc|{record["norm_desc"][:60]}'


def merge_similar_records(records: list, threshold: float = 0.82) -> list:
    buckets: dict[str, list] = {}
    for r in records:
        key = merge_key(r)
        buckets.setdefault(key, []).append(r)

    groups: list[list] = list(buckets.values())
    merged_groups: list[list] = []
    for group in groups:
        placed = False
        rep = group[0]
        for mg in merged_groups:
            base = mg[0]
            if SequenceMatcher(None, rep['norm_desc'], base['norm_desc']).ratio() >= threshold:
                mg.extend(group)
                placed = True
                break
        if not placed:
            merged_groups.append(group)

    results = []
    for group in merged_groups:
        company = max((g['company'] for g in group if g['company']), key=len, default='')
        if not company:
            for g in group:
                c = extract_company(g['desc'])
                if len(c) > len(company):
                    company = c
        address = max((g['address'] for g in group if g['address']), key=len, default='')
        if not address:
            for g in group:
                r = extract_region(g['desc'])
                if len(r) > len(address):
                    address = r
        event_dates = [g['event_date'] for g in group if g['event_date']]
        event_date = event_dates[0] if event_dates else ''
        urls = list(dict.fromkeys(g['work_url'] for g in group))
        desc = max((g['desc'] for g in group), key=len)
        results.append({
            'company': company,
            'address': address,
            'event_date': event_date,
            'publish_time': group[0]['publish_time'],
            'desc': desc,
            'merge_count': len(group),
            'video_urls': '\n'.join(urls),
            'aweme_ids': ','.join(g['aweme_id'] for g in group),
        })
    results.sort(key=lambda x: x['event_date'] or x['publish_time'], reverse=True)
    return results
