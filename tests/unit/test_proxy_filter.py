# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     test_proxy_filter.py
   Description :   代理过滤器与 Session 规则测试
   Author :        JHao
   date：          2026/08/11
-------------------------------------------------
"""
import pytest
from helper.proxy import Proxy
from helper.proxyFilter import filter_proxies, select_proxy, parse_username_options, SESSION_CACHE, ROTATION_HISTORY


@pytest.fixture
def sample_proxies():
    return [
        Proxy("1.1.1.1:8080", region="US", source="sourceA", https=True, anonymous="high"),
        Proxy("2.2.2.2:8080", region="HK", source="sourceB", https=False, anonymous="low"),
        Proxy("3.3.3.3:8080", region="JP", source="sourceA", https=True, anonymous="high"),
        Proxy("4.4.4.4:8080", region="CN", source="sourceC", https=False, anonymous="normal"),
    ]


def test_parse_username_options():
    conds, opts = parse_username_options("US;session=sess_01;ttl=300")
    assert conds == ["US"]
    assert opts['session_id'] == "sess_01"
    assert opts['ttl'] == 300
    assert opts['mode'] == "sticky"


def test_filter_positive_and_negative(sample_proxies):
    # 正选 US
    conds, _ = parse_username_options("US")
    res = filter_proxies(sample_proxies, conds)
    assert len(res) == 1
    assert res[0].proxy == "1.1.1.1:8080"

    # 反选 CN
    conds, _ = parse_username_options("!CN")
    res = filter_proxies(sample_proxies, conds)
    assert len(res) == 3
    assert not any(p.region == "CN" for p in res)

    # 多选 US,HK
    conds, _ = parse_username_options("US,HK")
    res = filter_proxies(sample_proxies, conds)
    assert len(res) == 2


def test_filter_key_value(sample_proxies):
    # https=1
    conds, _ = parse_username_options("https=1")
    res = filter_proxies(sample_proxies, conds)
    assert len(res) == 2
    assert all(p.https for p in res)

    # region!=CN
    conds, _ = parse_username_options("region!=CN")
    res = filter_proxies(sample_proxies, conds)
    assert len(res) == 3


def test_sticky_session(sample_proxies):
    SESSION_CACHE.clear()
    p1 = select_proxy(sample_proxies, "session=user_test_100")
    p2 = select_proxy(sample_proxies, "session=user_test_100")
    assert p1.proxy == p2.proxy


def test_rotation_anti_repeat(sample_proxies):
    ROTATION_HISTORY.clear()
    selected_proxies = []
    for _ in range(len(sample_proxies)):
        p = select_proxy(sample_proxies, "")
        selected_proxies.append(p.proxy)
    # 4 次连续提取，由于防重复逻辑，每个代理应当正好出现一次且无重复
    assert len(set(selected_proxies)) == len(sample_proxies)

    # 第 5 次提取，循环最久未使用的代理，且不抛异常
    p_5th = select_proxy(sample_proxies, "")
    assert p_5th is not None

