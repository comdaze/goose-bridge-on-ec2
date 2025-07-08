# 独立双路径GOOSE协议云端桥接服务

🚀 **双路径容错GOOSE协议云端部署解决方案** - 支持goose0/goose1双TAP接口独立运行

[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](./VERSION)
[![License](https://img.shields.io/badge/license-Industrial-green.svg)](#)
[![AWS](https://img.shields.io/badge/AWS-TGW%20Dual%20Path-orange.svg)](#)

## 🎯 项目概述

这是一个完整的双路径GOOSE协议云端桥接服务，实现真正的双网卡容错发送。通过创建两个独立的TAP接口(goose0/goose1)和对应的多播组，实现libiec61850应用的双路径容错通信。

### 核心特性

- ✅ **双TAP接口独立运行** - goose0 + goose1完全独立，无单点故障
- ✅ **双多播组容错** - 224.0.1.100 + 224.0.1.101独立传输
- ✅ **零侵入libiec61850兼容** - 无需修改任何现有代码
- ✅ **完整数据传输** - 不进行去重，保持原始GOOSE帧完整性
- ✅ **双IGMP保活机制** - 针对AWS TGW优化的独立保活
- ✅ **高性能异步处理** - 支持1000+ GOOSE帧/秒

## 🏗️ 架构设计

### 发送端架构
```
libiec61850应用:
├── goose_publisher → goose0 → 224.0.1.100:61850 (主路径)
└── goose_publisher → goose1 → 224.0.1.101:61850 (备路径)
```

### 接收端架构
```
libiec61850应用:
├── 224.0.1.100:61850 → goose0 → goose_subscriber (主路径)
└── 224.0.1.101:61850 → goose1 → goose_subscriber (备路径)
```

### 最终使用效果

**发送端（EC2-A）**：
```bash
# 同时运行两个发布者，使用不同的TAP接口
sudo ./goose_publisher_example goose0 &
sudo ./goose_publisher_example goose1 &
```

**接收端（EC2-B）**：
```bash
# 同时运行两个订阅者，监听不同的TAP接口
sudo ./goose_subscriber_example goose0 &
sudo ./goose_subscriber_example goose1 &
```

**预期结果**：两个订阅者都能同时接收到消息，实现真正的双路径容错。

### 成功验证示例

当双路径通信正常工作时，您应该看到：

**服务状态检查**：
```bash
$ goose-bridge-dual-ctl test
执行服务测试...
1. 检查TAP接口...
goose0: OK
goose1: OK
2. 检查多播组...
多播组: OK
3. 检查服务状态...
服务: OK
```

**多播组状态**：
```bash
$ goose-bridge-dual-ctl multicast
多播组成员状态:
✅ 主多播组 224.0.1.100 已加入
✅ 备多播组 224.0.1.101 已加入
```

**接收端输出示例**：
```bash
# 终端1 (goose0订阅者)
GOOSE event:
  stNum: 1 sqNum: 1
  timeToLive: 2000
  timestamp: 1625097600.123
[1234, false, 5678]

# 终端2 (goose1订阅者)  
GOOSE event:
  stNum: 1 sqNum: 1
  timeToLive: 2000
  timestamp: 1625097600.123
[1234, false, 5678]
```

## 🚀 快速部署

### 系统要求

- **操作系统**: Amazon Linux 2023(推荐)，Amazon Linux 2，CentOS 9/10
- **Python**: 3.6+
- **Linux权限**: root权限
- **关键工具**: aws cli, git, gcc
- **AWS EC2 Role权限**: EC2，VPC 管理员

### 一键安装

```bash
# 1. 进入项目目录
ssh -i goose-bridge-key-nw.pem ec2-user@$EC2_A_IP
git clone https://github.com/comdaze/goose-bridge-on-ec2.git
cd goose-bridge-on-ec2

# 2. 运行安装脚本（需要root权限）
sudo ./scripts/install-goose-bridge-dual.sh

# 3. 启动服务
sudo systemctl start goose-bridge-dual
sudo systemctl enable goose-bridge-dual

# 4. 验证安装
goose-bridge-dual-ctl status
goose-bridge-dual-ctl test
```

### 安装过程常见问题

#### 问题1: `iproute2`包找不到
```bash
# 错误信息: Error: Unable to find a match: iproute2
# 解决方案: 不同Linux发行版包名不同
# Amazon Linux/CentOS: 使用 iproute
# Ubuntu/Debian: 使用 iproute2
# 安装脚本已自动处理此问题
```

#### 问题2: sysctl参数设置失败
```bash
# 错误信息: sysctl: cannot stat /proc/sys/net/netfilter/nf_conntrack_max
# 解决方案: 这些错误不影响GOOSE功能，可以忽略
# 原因: 某些内核模块未加载，但GOOSE协议不需要这些参数
```

#### 问题3: 权限不足
```bash
# 确保使用root权限运行安装脚本
sudo ./scripts/install-goose-bridge-dual.sh

# 检查/dev/net/tun权限
ls -la /dev/net/tun
```

## 🔧 服务管理

### 基本管理命令

```bash
# 服务控制
goose-bridge-dual-ctl start      # 启动服务
goose-bridge-dual-ctl stop       # 停止服务
goose-bridge-dual-ctl restart    # 重启服务
goose-bridge-dual-ctl status     # 查看状态
goose-bridge-dual-ctl logs -f    # 查看实时日志

# 配置管理
goose-bridge-dual-ctl config edit    # 编辑配置
goose-bridge-dual-ctl config show    # 显示配置
goose-bridge-dual-ctl config test    # 测试配置

# 监控和诊断
goose-bridge-dual-ctl stats          # 查看统计信息
goose-bridge-dual-ctl interfaces     # 查看TAP接口状态
goose-bridge-dual-ctl multicast      # 查看多播组状态
goose-bridge-dual-ctl test           # 执行服务测试
```

### 传统systemctl命令

```bash
sudo systemctl start goose-bridge-dual    # 启动服务
sudo systemctl stop goose-bridge-dual     # 停止服务
sudo systemctl status goose-bridge-dual   # 查看状态
sudo systemctl enable goose-bridge-dual   # 开机启动
sudo journalctl -u goose-bridge-dual -f   # 查看日志
```

## ⚙️ 配置说明

### 主配置文件: `/etc/goose-bridge/goose-bridge-dual.conf`

```ini
# 双TAP接口配置
primary_interface = goose0
backup_interface = goose1
primary_tun_ip = 192.168.100.1/24
backup_tun_ip = 192.168.101.1/24

# 双多播组配置
primary_multicast_ip = 224.0.1.100
backup_multicast_ip = 224.0.1.101
multicast_port = 61850

# 双路径模式
dual_path_mode = independent  # 独立模式，两个路径完全独立

# 双IGMP保活配置
enable_igmp_keepalive = true
igmp_keepalive_interval = 90
igmp_monitor_interval = 120
igmp_reregister_threshold = 2

# TGW多播域配置
primary_tgw_multicast_domain_id = tgw-mcast-domain-01d79015018690cef
backup_tgw_multicast_domain_id = tgw-mcast-domain-01d79015018690cef
```

## 🧪 libiec61850使用方法

### 编译libiec61850示例

```bash
# 进入libiec61850目录
git clone https://github.com/mz-automation/libiec61850
cd libiec61850

# 编译示例程序
make examples
```

### 发送端使用

```bash
# 启动双路径发布者
sudo ./examples/goose_publisher/goose_publisher_example goose0 &
sudo ./examples/goose_publisher/goose_publisher_example goose1 &

# 查看进程
ps aux | grep goose_publisher
```

### 接收端使用

```bash
# 启动双路径订阅者
sudo ./examples/goose_subscriber/goose_subscriber_example goose0 &
sudo ./examples/goose_subscriber/goose_subscriber_example goose1 &

# 查看进程
ps aux | grep goose_subscriber
```

### 预期输出

接收端应该看到类似输出：

**终端1 (goose0订阅者)**:
```
GOOSE event:
  stNum: 1 sqNum: 1
  timeToLive: 2000
  timestamp: 1625097600.123
[1234, false, 5678]
```

**终端2 (goose1订阅者)**:
```
GOOSE event:
  stNum: 1 sqNum: 1
  timeToLive: 2000
  timestamp: 1625097600.123
[1234, false, 5678]
```

## 📊 监控和诊断

### 实时监控

```bash
# 查看服务状态
goose-bridge-dual-ctl status

# 查看实时日志
goose-bridge-dual-ctl logs -f

# 查看统计信息
goose-bridge-dual-ctl stats
```

### 接口状态检查

```bash
# 检查TAP接口
ip link show goose0
ip link show goose1

# 检查IP配置
ip addr show goose0
ip addr show goose1

# 检查多播组成员（正确方法）
# 注意：IGMP状态以十六进制显示，需要正确解析
cat /proc/net/igmp | grep -E "(goose0|goose1)"

# 验证多播组注册状态
goose-bridge-dual-ctl multicast  # 使用管理脚本检查

# 手动验证多播组（高级用户）
# 224.0.1.100 = 640100E0 (十六进制)
# 224.0.1.101 = 650100E0 (十六进制)
cat /proc/net/igmp | grep -E "(640100E0|650100E0)"
```

### 网络连通性测试

```bash
# 测试多播发送（在发送端）
echo "test" | nc -u 224.0.1.100 61850
echo "test" | nc -u 224.0.1.101 61850

# 监听多播（在接收端）
tcpdump -i any host 224.0.1.100 or host 224.0.1.101
```

## 🔍 故障排除

### 常见问题

#### 1. 服务启动失败
```bash
# 检查服务状态
sudo systemctl status goose-bridge-dual

# 查看详细日志
sudo journalctl -u goose-bridge-dual -n 50

# 检查配置文件语法
goose-bridge-dual-ctl config test
```

#### 2. TAP接口创建失败
```bash
# 检查权限
sudo ls -la /dev/net/tun

# 检查内核模块
lsmod | grep tun

# 手动加载模块
sudo modprobe tun

# 检查接口状态
goose-bridge-dual-ctl interfaces
```

#### 3. 多播通信失败
```bash
# 使用管理脚本检查
goose-bridge-dual-ctl test
goose-bridge-dual-ctl multicast

# 检查IGMP状态（正确方法）
cat /proc/net/igmp | grep -E "(goose0|goose1)"

# 检查路由
ip route show

# 检查防火墙
sudo iptables -L | grep -E "(224\.0\.1\.100|224\.0\.1\.101)"
```

#### 4. libiec61850无法通信
```bash
# 检查TAP接口状态
goose-bridge-dual-ctl interfaces

# 检查进程
ps aux | grep goose

# 检查网络流量
sudo tcpdump -i goose0 -n
sudo tcpdump -i goose1 -n

# 检查多播组注册
goose-bridge-dual-ctl multicast
```

#### 5. 多播组显示问题
```bash
# 问题：管理脚本显示"未找到多播组成员"
# 原因：IGMP状态以十六进制显示，需要正确解析
# 解决：使用更新后的管理脚本

# 手动验证（高级用户）
# 224.0.1.100 对应十六进制 640100E0
# 224.0.1.101 对应十六进制 650100E0
cat /proc/net/igmp | grep -E "(640100E0|650100E0)"
```

#### 6. 安装过程中的警告信息
```bash
# 警告：sysctl参数设置失败
# 解决：这些警告不影响GOOSE功能，可以安全忽略
# 原因：某些内核模块未加载，但GOOSE协议不依赖这些参数

# 警告：iproute2包找不到
# 解决：安装脚本已自动处理不同发行版的包名差异
```

## 📈 性能优化

### 预期性能指标

- **吞吐量**: 2000+ GOOSE帧/秒（双路径总和）
- **延迟**: < 1ms (局域网)
- **可靠性**: 99.9%+ 可用性（双路径容错）
- **资源使用**: < 200MB内存，< 10% CPU

### 性能调优

#### 高负载环境
```ini
buffer_size = 4096
batch_size = 20
worker_threads = 8
igmp_keepalive_interval = 60
```

#### 高可靠性环境
```ini
igmp_reregister_threshold = 1
igmp_keepalive_interval = 60
igmp_monitor_interval = 90
```

## 🔒 安全配置

### AWS安全组配置

```bash
# 允许UDP 61850端口
aws ec2 authorize-security-group-ingress --group-id $SG_ID \
    --protocol udp --port 61850 --cidr 10.0.0.0/16

# 允许IGMP协议
aws ec2 authorize-security-group-ingress --group-id $SG_ID \
    --protocol 2 --port -1 --cidr 0.0.0.0/32
```

### 防火墙配置

```bash
# 允许多播流量
sudo iptables -A INPUT -d 224.0.1.100 -j ACCEPT
sudo iptables -A INPUT -d 224.0.1.101 -j ACCEPT

# 允许IGMP
sudo iptables -A INPUT -p igmp -j ACCEPT
```

## 📁 重要文件位置

- **主程序**: `/usr/local/bin/goose-bridge-dual`
- **配置文件**: `/etc/goose-bridge/goose-bridge-dual.conf`
- **日志文件**: `/var/log/goose-bridge-dual.log`
- **统计文件**: `/var/lib/goose-bridge/dual-path-stats.json`
- **管理脚本**: `/usr/local/bin/goose-bridge-dual-ctl`
- **测试脚本**: `/usr/local/bin/test-dual-path-basic`

## 🆚 与单路径版本对比

| 特性 | 单路径版本 | 双路径版本 |
|------|------------|------------|
| TAP接口 | goose0 | goose0 + goose1 |
| 多播组 | 224.0.1.100 | 224.0.1.100 + 224.0.1.101 |
| 容错能力 | 单点故障 | 双路径容错 |
| libiec61850使用 | 单个进程 | 双个进程并行 |
| 性能 | 1000帧/秒 | 2000帧/秒 |
| 资源使用 | 100MB内存 | 200MB内存 |

## 🤝 技术支持

### 日志分析

```bash
# 查看错误日志
sudo journalctl -u goose-bridge-dual | grep ERROR

# 查看IGMP保活日志
sudo journalctl -u goose-bridge-dual | grep IGMP

# 查看实时日志
goose-bridge-dual-ctl logs -f

# 查看统计信息（如果可用）
goose-bridge-dual-ctl stats
```

### 性能分析

```bash
# 查看CPU使用
top -p $(pgrep goose-bridge-dual)

# 查看内存使用
ps aux | grep goose-bridge-dual

# 查看网络流量
iftop -i goose0
iftop -i goose1

# 查看网络统计
cat /proc/net/dev | grep -E "(goose0|goose1)"
```

### 诊断工具

```bash
# 完整系统检查
goose-bridge-dual-ctl test

# 接口状态检查
goose-bridge-dual-ctl interfaces

# 多播组状态检查
goose-bridge-dual-ctl multicast

# 基础测试脚本
test-dual-path-basic

# 手动IGMP状态检查
cat /proc/net/igmp | grep -A 5 -E "(goose0|goose1)"
```

### 问题报告

如果遇到问题，请收集以下信息：

```bash
# 1. 系统信息
uname -a
cat /etc/os-release

# 2. 服务状态
goose-bridge-dual-ctl status
goose-bridge-dual-ctl test

# 3. 网络状态
goose-bridge-dual-ctl interfaces
goose-bridge-dual-ctl multicast

# 4. 日志信息
sudo journalctl -u goose-bridge-dual -n 100

# 5. 配置信息
goose-bridge-dual-ctl config show
```

## 📝 更新日志

### v1.0.0 (2025-07-08)
- ✅ 实现双TAP接口独立管理 (goose0 + goose1)
- ✅ 实现双多播组独立处理 (224.0.1.100 + 224.0.1.101)
- ✅ 实现双IGMP保活机制，针对AWS TGW优化
- ✅ 完整的libiec61850兼容性，零代码修改
- ✅ 生产级服务管理功能
- ✅ 完整的监控和诊断工具
- ✅ 修复安装脚本中的包依赖问题 (iproute vs iproute2)
- ✅ 优化sysctl参数设置，忽略不必要的错误
- ✅ 修复多播组状态检查，正确解析IGMP十六进制格式
- ✅ 实际测试验证：双路径发送和接收功能完全正常

### 已验证的功能
- ✅ 双路径发送：同时运行两个publisher
- ✅ 双路径接收：同时运行两个subscriber  
- ✅ 真正容错：任一路径故障不影响通信
- ✅ 完整数据传输：不去重，保持原始GOOSE帧
- ✅ AWS TGW兼容：IGMP保活机制正常工作
- ✅ 生产环境就绪：完整的服务管理和监控

---

**注意**: 这是一个独立的双路径版本，与原始单路径版本并行存在，可以根据需要选择使用。经过实际测试验证，双路径通信功能完全正常，可以在生产环境中使用。
