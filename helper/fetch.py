# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     fetch.py
   Description :   代理采集
   Author :        JHao
   date：          2019/8/6
-------------------------------------------------
   Change Activity:
                   2019/08/06: 多线程采集
                   2026/05/31: 重构为动态加载 fetcher 插件
-------------------------------------------------
"""
__author__ = 'JHao'

import os
import sys
import time
import importlib
from threading import Thread

from helper.proxy import Proxy
from helper.check import DoValidator
from handler.logHandler import LogHandler
from handler.configHandler import ConfigHandler
from fetcher.baseFetcher import BaseFetcher

_logger = LogHandler("fetch")

# 模块缓存: {module_name: (mtime, module)}
_module_cache = {}


def _get_sources_dir():
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..', 'fetcher', 'sources')


def _load_module(module_name, filepath):
    """加载或 reload 模块，仅在文件 mtime 变化时 reload"""
    global _module_cache
    mtime = os.path.getmtime(filepath)
    cached = _module_cache.get(module_name)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        if module_name in sys.modules:
            module = importlib.reload(sys.modules[module_name])
        else:
            module = importlib.import_module(module_name)
        _module_cache[module_name] = (mtime, module)
        return module
    except Exception as e:
        _logger.warning("ProxyFetch : load %s error - %s" % (module_name, e))
        return None


def _discover_fetchers(exclude_list):
    """
    自动扫描 sources/ 目录，返回所有 enabled=True 且不在黑名单中的 fetcher 类列表。
    仅在文件 mtime 变化时重新加载模块，支持运行时热更新。
    """
    global _module_cache
    sources_dir = _get_sources_dir()
    fetcher_classes = []
    seen_modules = set()

    for filename in os.listdir(sources_dir):
        if not filename.endswith('.py') or filename.startswith('_'):
            continue
        module_name = "fetcher.sources.%s" % filename[:-3]
        seen_modules.add(module_name)
        filepath = os.path.join(sources_dir, filename)
        module = _load_module(module_name, filepath)
        if module is None:
            continue
        for attr_name in dir(module):
            attr = getattr(module, attr_name, None)
            if (attr and isinstance(attr, type)
                    and issubclass(attr, BaseFetcher)
                    and attr is not BaseFetcher
                    and attr.name
                    and attr.enabled
                    and attr.__name__ not in exclude_list):
                fetcher_classes.append(attr)

    # 清理已删除文件的缓存
    for name in list(_module_cache):
        if name not in seen_modules:
            del _module_cache[name]

    return sorted(fetcher_classes, key=lambda c: c.name)


class FetcherHealth(object):
    """ 代理源健康度统计与自动熔断 (Circuit Breaker) """
    _stats = {}
    MAX_CONSECUTIVE_FAILURES = 3
    COOLDOWN_SECONDS = 1800  # 30 分钟

    @classmethod
    def is_circuit_open(cls, fetcher_name):
        stat = cls._stats.get(fetcher_name)
        if not stat:
            return False
        until = stat.get("circuit_open_until", 0)
        if until and time.time() < until:
            return True
        return False

    @classmethod
    def record_success(cls, fetcher_name):
        stat = cls._stats.setdefault(fetcher_name, {
            "fail_count": 0,
            "success_count": 0,
            "circuit_open_until": 0
        })
        stat["fail_count"] = 0
        stat["success_count"] += 1
        stat["circuit_open_until"] = 0

    @classmethod
    def record_failure(cls, fetcher_name):
        stat = cls._stats.setdefault(fetcher_name, {
            "fail_count": 0,
            "success_count": 0,
            "circuit_open_until": 0
        })
        stat["fail_count"] += 1
        if stat["fail_count"] >= cls.MAX_CONSECUTIVE_FAILURES:
            stat["circuit_open_until"] = time.time() + cls.COOLDOWN_SECONDS

    @classmethod
    def get_stats(cls):
        return cls._stats

    @classmethod
    def reset(cls):
        cls._stats.clear()


class _ThreadFetcher(Thread):

    def __init__(self, fetcher_class, proxy_dict):
        Thread.__init__(self)
        self.fetcher_class = fetcher_class
        self.proxy_dict = proxy_dict
        self.log = LogHandler("fetcher")

    def run(self):
        fetcher_name = self.fetcher_class.name
        if FetcherHealth.is_circuit_open(fetcher_name):
            self.log.warning("ProxyFetch - {func}: circuit open (cooldown), skipping".format(func=fetcher_name))
            return
        self.log.info("ProxyFetch - {func}: start".format(func=fetcher_name))
        try:
            for proxy in self.fetcher_class().fetch():
                self.log.info('ProxyFetch - %s: %s ok' % (fetcher_name, proxy.ljust(23)))
                proxy = proxy.strip()
                if proxy in self.proxy_dict:
                    self.proxy_dict[proxy].add_source(fetcher_name)
                else:
                    self.proxy_dict[proxy] = Proxy(
                        proxy, source=fetcher_name)
            FetcherHealth.record_success(fetcher_name)
        except Exception as e:
            self.log.error("ProxyFetch - {func}: error".format(func=fetcher_name))
            self.log.error(str(e))
            FetcherHealth.record_failure(fetcher_name)


class Fetcher(object):
    name = "fetcher"

    def __init__(self):
        self.log = LogHandler(self.name)
        self.conf = ConfigHandler()

    def run(self):
        """
        fetch proxy with fetcher plugins
        :return:
        """
        proxy_dict = dict()
        thread_list = list()
        self.log.info("ProxyFetch : start")

        exclude_list = self.conf.fetcherExclude
        fetcher_classes = _discover_fetchers(exclude_list)
        self.log.info("ProxyFetch : active fetchers [%s]" % ", ".join(c.name for c in fetcher_classes))

        for fetcher_class in fetcher_classes:
            thread_list.append(_ThreadFetcher(fetcher_class, proxy_dict))

        for thread in thread_list:
            thread.setDaemon(True)
            thread.start()

        for thread in thread_list:
            thread.join()

        self.log.info("ProxyFetch - all complete!")
        for _ in proxy_dict.values():
            if DoValidator.preValidator(_.proxy):
                yield _
