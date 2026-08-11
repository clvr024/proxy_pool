# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     check
   Description :   执行代理校验
   Author :        JHao
   date：          2019/8/6
-------------------------------------------------
   Change Activity:
                   2019/08/06: 执行代理校验
                   2021/05/25: 分别校验http和https
                   2022/08/16: 获取代理Region信息
-------------------------------------------------
"""
__author__ = 'JHao'

import time
import ipaddress
from util.six import Empty
from threading import Thread
from datetime import datetime
from util.webRequest import WebRequest
from handler.logHandler import LogHandler
from helper.validator import ProxyValidator
from handler.proxyHandler import ProxyHandler
from handler.configHandler import ConfigHandler

_REGION_CACHE = {}
_CACHE_MAX_SIZE = 5000


class DoValidator(object):
    """ 执行校验 """

    conf = ConfigHandler()

    @classmethod
    def validator(cls, proxy, work_type):
        """
        校验入口
        Args:
            proxy: Proxy Object
            work_type: raw/use
        Returns:
            Proxy Object
        """
        start_time = time.time()
        http_r = cls.httpValidator(proxy)
        elapsed = round(time.time() - start_time, 2)
        https_r = False if not http_r else cls.httpsValidator(proxy)

        proxy.check_count += 1
        proxy.last_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        proxy.last_status = True if http_r else False
        if http_r:
            proxy.latency = elapsed
            if proxy.fail_count > 0:
                proxy.fail_count -= 1
            proxy.https = True if https_r else False
            if work_type == "raw":
                proxy.region = cls.regionGetter(proxy) if cls.conf.proxyRegion else ""
        else:
            proxy.fail_count += 1
        return proxy

    @classmethod
    def httpValidator(cls, proxy):
        for func in ProxyValidator.http_validator:
            if not func(proxy.proxy):
                return False
        return True

    @classmethod
    def httpsValidator(cls, proxy):
        for func in ProxyValidator.https_validator:
            if not func(proxy.proxy):
                return False
        return True

    @classmethod
    def preValidator(cls, proxy):
        for func in ProxyValidator.pre_validator:
            if not func(proxy):
                return False
        return True

    @classmethod
    def clearRegionCache(cls):
        _REGION_CACHE.clear()

    @classmethod
    def regionGetter(cls, proxy):
        raw_ip = proxy.proxy.split(':')[0]
        if '@' in raw_ip:
            raw_ip = raw_ip.split('@')[-1]

        # 1. 检查私有/保留 IP
        try:
            ip_obj = ipaddress.ip_address(raw_ip)
            if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved:
                return 'INT'
        except ValueError:
            pass

        # 2. 检查缓存
        if raw_ip in _REGION_CACHE:
            return _REGION_CACHE[raw_ip]

        country_code = None

        # 3. 主源 api.ip.sb
        try:
            url = 'https://api.ip.sb/geoip/%s' % raw_ip
            r = WebRequest().get(url=url, retry_time=1, timeout=2).json
            if isinstance(r, dict):
                country_code = r.get('country_code')
        except Exception:
            pass

        # 4. 降级源 1: ip-api.com
        if not country_code:
            try:
                url = 'http://ip-api.com/json/%s?fields=countryCode' % raw_ip
                r = WebRequest().get(url=url, retry_time=1, timeout=2).json
                if isinstance(r, dict):
                    country_code = r.get('countryCode')
            except Exception:
                pass

        # 5. 降级源 2: ipwho.is
        if not country_code:
            try:
                url = 'https://ipwho.is/%s' % raw_ip
                r = WebRequest().get(url=url, retry_time=1, timeout=2).json
                if isinstance(r, dict):
                    country_code = r.get('country_code')
            except Exception:
                pass

        final_region = country_code if country_code else 'error'

        if final_region != 'error':
            if len(_REGION_CACHE) >= _CACHE_MAX_SIZE:
                _REGION_CACHE.clear()
            _REGION_CACHE[raw_ip] = final_region

        return final_region


class _ThreadChecker(Thread):
    """ 多线程检测 """

    def __init__(self, work_type, target_queue, thread_name):
        Thread.__init__(self, name=thread_name)
        self.work_type = work_type
        self.log = LogHandler("checker")
        self.proxy_handler = ProxyHandler()
        self.target_queue = target_queue
        self.conf = ConfigHandler()

    def run(self):
        self.log.info("{}ProxyCheck - {}: start".format(self.work_type.title(), self.name))
        while True:
            try:
                proxy = self.target_queue.get(block=False)
            except Empty:
                self.log.info("{}ProxyCheck - {}: complete".format(self.work_type.title(), self.name))
                break
            proxy = DoValidator.validator(proxy, self.work_type)
            if self.work_type == "raw":
                self.__ifRaw(proxy)
            else:
                self.__ifUse(proxy)
            self.target_queue.task_done()

    def __ifRaw(self, proxy):
        if proxy.last_status:
            if self.proxy_handler.exists(proxy):
                self.log.info('RawProxyCheck - {}: {} exist'.format(self.name, proxy.proxy.ljust(23)))
            else:
                self.log.info('RawProxyCheck - {}: {} pass'.format(self.name, proxy.proxy.ljust(23)))
                self.proxy_handler.put(proxy)
        else:
            self.log.info('RawProxyCheck - {}: {} fail'.format(self.name, proxy.proxy.ljust(23)))

    def __ifUse(self, proxy):
        if proxy.last_status:
            self.log.info('UseProxyCheck - {}: {} pass'.format(self.name, proxy.proxy.ljust(23)))
            self.proxy_handler.put(proxy)
        else:
            if proxy.fail_count > self.conf.maxFailCount:
                self.log.info('UseProxyCheck - {}: {} fail, count {} delete'.format(self.name,
                                                                                    proxy.proxy.ljust(23),
                                                                                    proxy.fail_count))
                self.proxy_handler.delete(proxy)
            else:
                self.log.info('UseProxyCheck - {}: {} fail, count {} keep'.format(self.name,
                                                                                  proxy.proxy.ljust(23),
                                                                                  proxy.fail_count))
                self.proxy_handler.put(proxy)


def Checker(tp, queue, thread_num=20):
    """
    run Proxy ThreadChecker
    :param tp: raw/use
    :param queue: Proxy Queue
    :param thread_num: 并发线程数量 (默认 20)
    :return:
    """
    thread_list = list()
    for index in range(thread_num):
        thread_list.append(_ThreadChecker(tp, queue, "thread_%s" % str(index).zfill(2)))

    for thread in thread_list:
        thread.setDaemon(True)
        thread.start()

    for thread in thread_list:
        thread.join()
