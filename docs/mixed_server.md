# Mixed 混合代理服务器使用指南

ProxyPool 内置了一个高效的高并发异步混合代理服务器 (`mixedServer`)，支持在**同一个端口**上同时处理 **HTTP / HTTPS (CONNECT)** 和 **SOCKS5** 协议的代理请求，并提供灵活的 **IP 轮换**、**地区过滤**及 **Session 粘性（固定 IP）** 控制。

---

## 核心特性

- **协议自适应**：端口（默认 `5011`）自动识别 HTTP 请求与 SOCKS5 握手，无需分设端口。
- **动态 IP 轮换**：默认每次请求自动从代理池轮换分配可用 IP。
- **Session 粘性（固定 IP）**：支持指定 Session ID，在设定时间内保持使用同一个代理 IP。
- **规则过滤**：支持按国家/地区（如 `us`、`hk`、`jp`）、协议类型（`https`）等条件精准筛选代理。
- **密码鉴权**：支持配置 API Key / 密码访问控制。

---

## 配置说明

在 `setting.py` 或环境变量中可配置以下相关选项：

```python
# Mixed 代理服务器绑定地址与端口
MIXED_HOST = "0.0.0.0"
MIXED_PORT = 5011

# 访问密码/API Key 列表（为空时不启用鉴权；配置后客户端需提供密码认证）
MIXED_AUTH_KEYS = ["your_secret_password"]
```

---

## 启动方式

### 1. 命令行启动
```bash
# 启动包含 HTTP API、Scheduler 与 Mixed 代理服务的全套进程
./proxy_pool.sh start

# 或单独启动混合代理服务器
python proxyPool.py server
```

### 2. 验证运行状态
```bash
./proxy_pool.sh status
```

---

## 用户名过滤与控制语法

客户端在连接 `mixedServer` 时，可以通过**代理用户名 (Username)** 传递控制规则与过滤条件，多个参数之间使用 `;` 或 `&` 分隔（在命令行使用 `curl` 时**务必加双引号**）。

### 1. 控制语法格式

```
[过滤条件/国家/标签];[session=ID];[mode=sticky|rotate];[ttl=秒数]
```

### 2. 常用参数说明

| 参数 | 说明 | 示例 |
|---|---|---|
| `us` / `cn` / `hk` / `jp` / `kr` | 按国家/地区缩写过滤代理 IP | `us` |
| `region=us` / `country=hk` | 显式指定地区 | `region=us` |
| `https` / `ssl` / `type=https` | 仅使用支持 HTTPS 的代理 | `https` |
| `session=ID` / `sticky=ID` / `sid=ID` | 开启 Session 粘性（固定 IP） | `session=user_1001` |
| `mode=sticky` / `mode=rotate` | 强制切换为固定 IP 模式或每次轮换模式 | `mode=sticky` |
| `ttl=秒数` / `expire=秒数` | 设置 Session 粘性 IP 的有效期（默认 600 秒） | `ttl=300` |

---

## 使用示例

### 1. cURL 命令行使用

#### 基础 HTTP 代理（每次请求自动轮换 IP）
```bash
curl -x "http://127.0.0.1:5011" https://httpbin.org/ip
```

#### SOCKS5 代理
```bash
curl -x "socks5://127.0.0.1:5011" https://httpbin.org/ip
```

#### 按地区过滤（获取美国/香港 IP）
```bash
# 获取美国 (US) 代理 IP
curl -x "http://us@127.0.0.1:5011" https://httpbin.org/ip

# 获取香港 (HK) 支持 HTTPS 的代理 IP
curl -x "http://hk;https@127.0.0.1:5011" https://httpbin.org/ip
```

#### 带密码认证 + Session 粘性（固定 IP 10 分钟）
```bash
# 用户名为 us;session=sess_001，密码为 setting.py 中配置的 your_secret_password
curl -x "http://us;session=sess_001:your_secret_password@127.0.0.1:5011" https://httpbin.org/ip
```

---

### 2. Python 代码使用

#### 使用 `requests`
```python
import requests

# 1. 基础轮换代理
proxies = {
    "http": "http://127.0.0.1:5011",
    "https": "http://127.0.0.1:5011",
}
resp = requests.get("https://httpbin.org/ip", proxies=proxies)
print(resp.json())

# 2. 地区筛选 + Session 粘性固定 IP
proxies_sticky = {
    "http": "http://us;session=spider_task_01:your_pwd@127.0.0.1:5011",
    "https": "http://us;session=spider_task_01:your_pwd@127.0.0.1:5011",
}
resp_sticky = requests.get("https://httpbin.org/ip", proxies=proxies_sticky)
print(resp_sticky.json())
```

#### 使用 `httpx` (支持 SOCKS5 与 HTTP)
```python
import httpx

# SOCKS5 混合代理连接
with httpx.Client(proxies="socks5://us;session=task_02@127.0.0.1:5011") as client:
    r = client.get("https://httpbin.org/ip")
    print(r.json())
```

---

### 3. 浏览器 / SwitchyOmega 插件设置

在浏览器代理管理插件（如 SwitchyOmega）中添加代理服务器：

- **代理协议**：`HTTP` 或 `SOCKS5`
- **代理服务器**：`127.0.0.1`
- **代理端口**：`5011`
- **用户名**：填入过滤与 Session 规则（例如 `us;session=my_browser`）
- **密码**：填入配置的密码（若未启用鉴权可随心填写）

---

## 常见问题与注意事项

1. **命令行 `curl` 参数加引号**：
   在终端使用包含 `;` 或 `&` 的用户名规则时，**必须给 URL 加上双引号**（如 `curl -x "http://us;session=1@127.0.0.1:5011"`），否则 Shell 会将 `;` 识别为命令分隔符。

2. **返回 502 Bad Gateway 报错**：
   若收到 `Received HTTP code 502 from proxy after CONNECT`，说明当前代理池中符合筛选条件的上游免费代理不可用或尝试超时，等待调度器抓取新代理或调宽过滤限制即可。
