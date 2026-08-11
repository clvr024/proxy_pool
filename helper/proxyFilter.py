# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     proxyFilter.py
   Description :   代理过滤与 Session 粘性/轮换控制引擎
   Author :        JHao
   date：          2026/08/11
-------------------------------------------------
"""
__author__ = 'JHao'

import re
import random
import hashlib
import time
import threading
from collections import deque
from handler.logHandler import LogHandler

log = LogHandler('proxyFilter')

# Session 粘性缓存: session_id -> (proxy_str, expire_timestamp)
SESSION_CACHE = {}
SESSION_TTL = 600  # 默认粘性 IP 缓存时长 (秒)

# 轮换防重复历史队列与线程锁
ROTATION_HISTORY = deque(maxlen=100)
ROTATION_LOCK = threading.Lock()

# 常见国家/地区名称与代码对照映射
COUNTRY_MAP = {
    'cn': ['cn', 'china', '中国'],
    'us': ['us', 'united states', 'america', '美国'],
    'hk': ['hk', 'hong kong', '香港'],
    'tw': ['tw', 'taiwan', '台湾'],
    'jp': ['jp', 'japan', '日本'],
    'kr': ['kr', 'korea', '韩国'],
    'sg': ['sg', 'singapore', '新加坡'],
    'uk': ['uk', 'gb', 'united kingdom', 'britain', '英国'],
    'de': ['de', 'germany', '德国'],
    'fr': ['fr', 'france', '法国'],
    'ru': ['ru', 'russia', '俄罗斯'],
}


def _match_string(value, pattern):
    """ 字符串匹配，支持常见国家代码缩写映射与包含匹配 """
    if not value or not pattern:
        return False
    val_lower = str(value).lower()
    pat_lower = str(pattern).lower()

    expand_pats = COUNTRY_MAP.get(pat_lower, [pat_lower])
    for p in expand_pats:
        if p in val_lower:
            return True
    return False


def parse_username_options(username_filter):
    """
    解析 username 中的控制选项（如固定 IP/Session 粘性、轮换模式）与过滤条件
    :param username_filter: 用户名控制字符串
    :return: (conditions_list, options_dict)
    """
    if not username_filter:
        return [], {}

    raw_filter = str(username_filter).strip()
    if not raw_filter or raw_filter.lower() in ('default', 'all', 'none', 'root', 'admin'):
        return [], {}

    tokens = [c.strip() for c in re.split(r'[;&]', raw_filter) if c.strip()]
    conditions = []
    options = {
        'session_id': None,
        'mode': 'rotate',  # rotate (轮换) | sticky (粘性固定 IP)
        'ttl': SESSION_TTL
    }

    for token in tokens:
        # 1. Session 粘性/固定 IP 标识 (如 session=user1, sticky=sess123, sid=abc, id=1001)
        sess_match = re.match(r'^(session|sticky|sid|id)\s*=\s*(.+)$', token, re.I)
        if sess_match:
            options['session_id'] = sess_match.group(2).strip()
            options['mode'] = 'sticky'
            continue

        # 2. 轮换/固定模式切换 (如 mode=sticky, mode=rotate, type=fixed)
        mode_match = re.match(r'^(mode|type|select)\s*=\s*(rotate|sticky|random|fixed)$', token, re.I)
        if mode_match:
            m = mode_match.group(2).lower()
            options['mode'] = 'sticky' if m in ('sticky', 'fixed') else 'rotate'
            continue

        # 3. 粘性 TTL 设置 (如 ttl=300, expire=600)
        ttl_match = re.match(r'^(ttl|expire)\s*=\s*(\d+)$', token, re.I)
        if ttl_match:
            options['ttl'] = int(ttl_match.group(2))
            continue

        conditions.append(token)

    return conditions, options


def filter_proxies(proxies, conditions):
    """
    根据过滤条件筛选 Proxy 列表
    :param proxies: Proxy 对象列表
    :param conditions: 条件列表
    :return: 过滤后的 Proxy 对象列表
    """
    if not proxies or not conditions:
        return proxies

    filtered = list(proxies)

    for cond in conditions:
        if not filtered:
            break

        # 1. 键值对语法: key=val1,val2 或 key!=val1,val2 或 key!val1,val2
        kv_match = re.match(r'^([a-zA-Z_]+)\s*(!=|!|=)\s*(.+)$', cond)
        if kv_match:
            key, op, val_str = kv_match.groups()
            key = key.lower()
            is_negate = ('!' in op)
            values = [v.strip() for v in re.split(r'[,+|]', val_str) if v.strip()]

            if key in ('https', 'type', 'ssl', 'scheme', 'proto'):
                has_true = any(v.lower() in ('1', 'true', 'https', 'ssl') for v in values)
                has_false = any(v.lower() in ('0', 'false', 'http') for v in values)
                if has_true and not has_false:
                    target_https = not is_negate
                elif has_false and not has_true:
                    target_https = is_negate
                else:
                    target_https = True
                filtered = [p for p in filtered if p.https == target_https]

            elif key in ('region', 'country', 'area', 'loc'):
                def _match_region(p):
                    res = any(_match_string(p.region, v) for v in values)
                    return not res if is_negate else res
                filtered = [p for p in filtered if _match_region(p)]

            elif key in ('source', 'src'):
                def _match_source(p):
                    res = any(_match_string(p.source, v) for v in values)
                    return not res if is_negate else res
                filtered = [p for p in filtered if _match_source(p)]

            elif key in ('anonymous', 'ano'):
                def _match_ano(p):
                    res = any(_match_string(p.anonymous, v) for v in values)
                    return not res if is_negate else res
                filtered = [p for p in filtered if _match_ano(p)]

            elif key == 'ip':
                def _match_ip(p):
                    ip = p.proxy.split(':')[0] if ':' in p.proxy else p.proxy
                    res = any(_match_string(ip, v) for v in values)
                    return not res if is_negate else res
                filtered = [p for p in filtered if _match_ip(p)]

            elif key == 'port':
                def _match_port(p):
                    port = p.proxy.split(':')[1] if ':' in p.proxy else ''
                    res = any(port == v for v in values)
                    return not res if is_negate else res
                filtered = [p for p in filtered if _match_port(p)]
            continue

        # 2. 标签简写语法
        # 反选标签: !tag 或 -tag 或 ~tag
        if cond.startswith(('!', '-', '~')):
            tag = cond[1:].strip()
            if not tag:
                continue
            if tag.lower() in ('https', 'ssl'):
                filtered = [p for p in filtered if not p.https]
            elif tag.lower() == 'http':
                filtered = [p for p in filtered if p.https]
            else:
                filtered = [p for p in filtered if not (
                    _match_string(p.region, tag) or
                    _match_string(p.source, tag) or
                    _match_string(p.proxy, tag)
                )]
            continue

        # 正选单关键字标签: https / ssl / http
        cond_lower = cond.lower()
        if cond_lower in ('https', 'ssl'):
            filtered = [p for p in filtered if p.https]
            continue
        elif cond_lower == 'http':
            filtered = [p for p in filtered if not p.https]
            continue

        # 常用多选正选标签 (如 "us,hk,jp" 或 "us+hk")
        tags = [t.strip() for t in re.split(r'[,+|]', cond) if t.strip()]
        if tags:
            def _match_any_tag(p):
                return any(
                    _match_string(p.region, t) or
                    _match_string(p.source, t) or
                    _match_string(p.proxy, t)
                    for t in tags
                )
            filtered = [p for p in filtered if _match_any_tag(p)]

    return filtered


def select_proxy(proxies, username_filter):
    """
    根据过滤规则与粘性 Session 机制选择代理
    :param proxies: Proxy 对象列表
    :param username_filter: 用户名过滤与控制规则
    :return: Proxy 对象或 None
    """
    if not proxies:
        return None

    conditions, options = parse_username_options(username_filter)
    filtered = filter_proxies(proxies, conditions)

    if not filtered:
        log.warning("ProxyFilter: filter '%s' matched 0 proxies, fallback to all pool" % username_filter)
        candidates = proxies
    else:
        candidates = filtered

    # 固定 IP / 粘性 Session 模式
    session_id = options.get('session_id')
    if session_id:
        now = time.time()
        # 清理过期 session
        expired_keys = [k for k, v in SESSION_CACHE.items() if v[1] < now]
        for k in expired_keys:
            SESSION_CACHE.pop(k, None)

        if session_id in SESSION_CACHE:
            cached_proxy_str, expire_time = SESSION_CACHE[session_id]
            for p in candidates:
                if p.proxy == cached_proxy_str:
                    return p

        # 若无有效缓存，通过 hash 选择并缓存
        hash_idx = int(hashlib.md5(session_id.encode('utf-8')).hexdigest(), 16) % len(candidates)
        selected = candidates[hash_idx]
        SESSION_CACHE[session_id] = (selected.proxy, now + options.get('ttl', SESSION_TTL))
        return selected

    # 默认每次请求轮换选择 IP (防重复逻辑)
    with ROTATION_LOCK:
        unseen = [p for p in candidates if p.proxy not in ROTATION_HISTORY]
        if unseen:
            selected = random.choice(unseen)
        else:
            hist_list = list(ROTATION_HISTORY)
            selected = min(candidates, key=lambda p: hist_list.index(p.proxy) if p.proxy in hist_list else -1)

        try:
            ROTATION_HISTORY.remove(selected.proxy)
        except ValueError:
            pass
        ROTATION_HISTORY.append(selected.proxy)
        return selected
