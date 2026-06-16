"""多关键词搜索 → 过滤 → 去重合并 → 可选评论与 LLM prompt。"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from typing import Any

from .batch_util import (
    FilterKeywords,
    merge_similar_records,
    months_ago_ts,
    video_to_record,
)
from .client import DouyinClient, SearchOptions, format_search_failure

PUBLISH_TIME_FILTER = '180'


def _build_events_analysis_input(
    merged: list[dict[str, Any]],
    *,
    report_name: str,
    cutoff_date: str,
    task: str,
) -> str:
    lines = [
        f'【报告】{report_name}',
        f'【时间范围】{cutoff_date} 至今',
        f'【合并事件数】{len(merged)}',
        f'【分析任务】{task}',
    ]
    for i, row in enumerate(merged, 1):
        lines.append(f'\n--- 事件 {i}（合并 {row.get("merge_count", 1)} 条）---')
        lines.append(f'企业: {row.get("company") or "未识别"}')
        lines.append(f'地址: {row.get("address") or "未识别"}')
        lines.append(f'日期: {row.get("event_date") or "未识别"}')
        lines.append(f'发布: {row.get("publish_time") or ""}')
        lines.append(f'链接:\n{row.get("video_urls") or ""}')
        desc = (row.get('desc') or '')[:800]
        lines.append(f'摘要: {desc}')
    return '\n'.join(lines)


def collect_videos(client: DouyinClient, queries: list[str], per_query: int) -> list[dict[str, Any]]:
    seen_ids: set[str] = set()
    videos: list[dict[str, Any]] = []
    for query in queries:
        print(f'搜索关键词: {query}', file=sys.stderr)
        opts = SearchOptions(
            keyword=query,
            num=per_query,
            sort_type='2',
            publish_time=PUBLISH_TIME_FILTER,
        )
        result = client.search(opts)
        batch = result.videos
        if not batch:
            print(format_search_failure(result, query), file=sys.stderr)
        print(f'[{query}] 本批 {len(batch)} 条 (method={result.method})', file=sys.stderr)
        for v in batch:
            aid = str(v.get('aweme_id') or '')
            if not aid or aid in seen_ids:
                continue
            seen_ids.add(aid)
            videos.append(v)
        print(f'[{query}] 累计候选 {len(videos)} 条', file=sys.stderr)
        time.sleep(0.5)
    return videos


def run_batch_pipeline(
    client: DouyinClient,
    *,
    queries: list[str],
    filter_keywords: FilterKeywords,
    report_name: str = 'douyin_batch',
    months: float = 3,
    per_query: int = 35,
    comments_per_video: int = 0,
    task: str = '',
) -> dict[str, Any]:
    if not queries:
        raise ValueError('queries 不能为空')
    if not filter_keywords.topic:
        raise ValueError('filter_keywords.topic 不能为空')

    cutoff_ts = months_ago_ts(months)
    cutoff_date = datetime.fromtimestamp(cutoff_ts).strftime('%Y-%m-%d')

    all_videos = collect_videos(client, queries, per_query)
    records = []
    for v in all_videos:
        rec = video_to_record(v, cutoff_ts, filter_keywords)
        if rec:
            records.append(rec)

    merged = merge_similar_records(records)

    bundles: list[dict[str, Any]] = []
    analysis_prompt = ''
    if comments_per_video > 0 and merged:
        analysis_task = task or (
            '归纳各事件的涉事企业、地点、时间线、关键事实与处置情况，'
            '对比描述与评论是否一致，列出舆论焦点与待核实信息。'
        )
        target_urls: list[str] = []
        for row in merged:
            for url in row['video_urls'].split('\n'):
                if url.strip():
                    target_urls.append(url.strip())
        print(f'拉取评论: {len(target_urls)} 条视频', file=sys.stderr)
        for i, url in enumerate(target_urls, 1):
            print(f'评论 [{i}/{len(target_urls)}] {url}', file=sys.stderr)
            try:
                bundle = client.video_detail(url, comments_per_video)
                bundles.append(bundle)
            except Exception as e:
                bundles.append({'video': {'share_url': url}, 'error': str(e)})
            time.sleep(0.5)
        combined = '\n\n---\n\n'.join(
            b.get('analysis_input', '') for b in bundles if b.get('analysis_input')
        )
        analysis_prompt = f'【分析任务】{analysis_task}\n\n【合并事件数】{len(merged)}\n\n{combined}'

    default_task = task or '归纳各事件的涉事企业、地点、时间线与关键事实，标注待核实项。'
    analysis_input = _build_events_analysis_input(
        merged,
        report_name=report_name,
        cutoff_date=cutoff_date,
        task=default_task,
    )

    result = {
        'report_name': report_name,
        'cutoff_date': cutoff_date,
        'queries': queries,
        'topic_keywords': list(filter_keywords.topic),
        'enterprise_keywords': list(filter_keywords.enterprise),
        'candidates': len(all_videos),
        'filtered_records': len(records),
        'merged_events': len(merged),
        'events': merged,
        'analysis_input': analysis_input,
    }
    if analysis_prompt:
        result['analysis_prompt'] = analysis_prompt
        if bundles:
            result['comment_bundles'] = bundles
        result['next_step'] = (
            '脚本阶段结束。Agent 须读取 analysis_prompt（含评论）按用户意图完成 LLM 分析；'
            'events[] / analysis_input 用于核对与补全。'
        )
    else:
        result['next_step'] = (
            '脚本阶段结束。Agent 须读取 analysis_input 与 events[]，'
            '按用户意图在本对话或外部 LLM 完成归纳、对比、舆情与报告；'
            '规则抽取字段有误时以 desc 为准。'
            '若用户要评论舆情，应重跑并加 --comments-per-video。'
        )

    return result
