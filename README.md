# GOOSE Protocol Cloud Bridge Service

🚀 **生产级GOOSE协议云端桥接服务** - 专为AWS环境优化的工业协议云端部署解决方案

[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](./VERSION)
[![License](https://img.shields.io/badge/license-Industrial-green.svg)](#)
[![AWS](https://img.shields.io/badge/AWS-TGW%20Optimized-orange.svg)](#)

## 📋 目录

### 基础使用
- [项目概述](#-项目概述)
- [核心特性](#-核心特性)
- [项目结构](#-项目结构)
- [快速开始](#-快速开始)
- [安装指南](#-安装指南)
- [配置说明](#️-配置说明)
- [使用方法](#-使用方法)

### 测试和监控
- [测试工具](#-测试工具)
- [监控和诊断](#-监控和诊断)
- [性能优化](#-性能优化)
- [故障排除](#-故障排除)

### 技术架构深度解析
- [整体架构图](#️-整体架构图)
- [数据流原理图](#-数据流原理图)
- [GOOSE协议详解](#-goose协议详解)
- [AWS TGW多播原理](#-aws-transit-gateway多播架构)
- [TGW vs 传统多播对比](#-tgw多播-vs-传统局域网多播对比)
- [桥接解决方案原理](#-桥接解决方案原理)

### 项目信息
- [架构说明](#️-架构说明)
- [版本历史](#-版本历史)
- [安全考虑](#-安全考虑)
- [贡献指南](#-贡献指南)

## 🎯 项目概述

这是一个完整的GOOSE协议云端桥接服务，支持libiec61850和其他IEC 61850应用在AWS云环境中的部署。通过透明的协议转换，实现工业设备的云端互联。

### 核心特性

- ✅ **优化单端口设计** - 只需开放UDP 61850端口，简化安全组配置
- ✅ **IGMP保活机制** - 防止AWS TGW 6分钟超时，基于官方文档优化
- ✅ **VLAN GOOSE帧支持** - 完全兼容libiec61850和工业标准
- ✅ **高性能异步处理** - 支持1000+ GOOSE帧/秒，生产级性能
- ✅ **智能监控重注册** - 自动检测和恢复注册状态
- ✅ **AWS TGW优化** - 基于官方文档的最佳实践配置

## 📁 项目结构

```
goose-bridge/                           # 232KB 完整项目
├── src/                               # 源代码
│   └── goose-bridge.py               # 主程序（优化单端口版）
├── config/                           # 配置文件
│   ├── goose-bridge.conf            # 服务配置
│   └── goose-bridge.service         # systemd服务文件
├── scripts/                          # 脚本和工具
│   ├── install-goose-bridge.sh      # 安装脚本
│   ├── goose-bridge-monitor.py      # 监控工具
│   └── goose-bridge-benchmark.py    # 性能测试工具
├── tests/                            # 测试文件
│   ├── basic_ip_multicast_test.py    # 基础多播测试
│   ├── igmp_multicast_test.py        # IGMP多播测试
│   ├── aws_tgw_igmp_validator.py     # AWS TGW IGMP验证
│   └── igmp_lifecycle_monitor_fixed.py # IGMP生命周期监控
├── docs/                             # 文档
│   └── PRODUCTION_DEPLOYMENT_GUIDE.md # 生产部署指南
└── README.md                         # 项目说明（本文件）
```

## 🚀 快速开始

### 系统要求

- **操作系统**: Linux (Amazon Linux 2, Ubuntu 18.04+, CentOS 7+)
- **Python**: 3.6+
- **权限**: root权限（用于创建TUN接口）
- **AWS**: EC2实例，配置TGW多播域

### 5分钟快速部署

#### 1. 进入项目目录
```bash
cd goose-bridge
```

#### 2. 检查项目结构
```bash
ls -la
# 应该看到：src/, config/, scripts/, tests/, docs/
```

#### 3. 一键安装
```bash
# 需要root权限
sudo ./scripts/install-goose-bridge.sh
```

#### 4. 启动服务
```bash
# 启动服务
sudo goose-bridge-ctl start

# 检查状态
goose-bridge-ctl status
```

#### 5. 配置AWS安全组
只需开放一个端口：
```
类型: Custom UDP
端口: 61850
来源: 0.0.0.0/0 (或指定IP范围)
描述: GOOSE Protocol Bridge Service
```

#### 6. 验证安装
```bash
# 检查端口
goose-bridge-ctl ports

# 检查安全组
goose-bridge-security-check

# 实时监控
goose-bridge-ctl monitor
```

## 📦 安装指南

### 自动安装（推荐）

安装脚本会自动完成以下操作：

1. **文件部署**
   - 复制主程序到 `/usr/local/bin/goose-bridge`
   - 复制配置文件到 `/etc/goose-bridge/`
   - 安装systemd服务文件
   - 创建管理脚本

2. **系统配置**
   - 优化IGMP系统参数
   - 配置日志轮转
   - 设置网络缓冲区

3. **AWS配置**
   - 检查EC2实例配置
   - 禁用源/目标检查
   - 验证TGW多播域

### 手动安装

如果需要手动安装：

```bash
# 1. 复制程序文件
sudo cp src/goose-bridge.py /usr/local/bin/goose-bridge
sudo chmod +x /usr/local/bin/goose-bridge

# 2. 复制配置文件
sudo mkdir -p /etc/goose-bridge
sudo cp config/goose-bridge.conf /etc/goose-bridge/

# 3. 安装systemd服务
sudo cp config/goose-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload

# 4. 安装管理工具
sudo cp scripts/goose-bridge-monitor.py /usr/local/bin/goose-bridge-monitor
sudo chmod +x /usr/local/bin/goose-bridge-monitor
```

### 安装验证

```bash
# 检查服务状态
sudo systemctl status goose-bridge

# 启动服务
sudo goose-bridge-ctl start

# 验证端口
goose-bridge-ctl ports

# 检查安全组
goose-bridge-security-check
```

## ⚙️ 配置说明

### 主配置文件: `config/goose-bridge.conf`

```ini
# 基本配置
interface = goose0
multicast_ip = 224.0.1.100
multicast_port = 61850

# IGMP保活配置（基于AWS TGW机制优化）
enable_igmp_keepalive = true
igmp_keepalive_interval = 90    # 90秒保活间隔
igmp_monitor_interval = 120     # 120秒监控间隔
igmp_reregister_threshold = 2   # 2次失败后重注册
enable_tgw_monitoring = true    # 启用TGW监控
tgw_multicast_domain_id = tgw-mcast-domain-01d79015018690cef

# 性能配置
buffer_size = 2048
batch_size = 10
worker_threads = 2
```

### 环境优化配置

#### 高负载环境
```ini
buffer_size = 4096
batch_size = 20
worker_threads = 4
igmp_keepalive_interval = 60
```

#### 高可靠性环境
```ini
igmp_reregister_threshold = 1
igmp_keepalive_interval = 60
igmp_monitor_interval = 90
```

#### 低延迟环境
```ini
buffer_size = 1024
batch_size = 5
worker_threads = 1
igmp_keepalive_interval = 60
```

## 🔧 使用方法

### 管理命令

```bash
# 服务管理
goose-bridge-ctl start      # 启动服务
goose-bridge-ctl stop       # 停止服务
goose-bridge-ctl restart    # 重启服务
goose-bridge-ctl status     # 查看状态
goose-bridge-ctl logs       # 查看日志
goose-bridge-ctl monitor    # 实时监控

# 诊断和测试
goose-bridge-ctl ports      # 检查端口使用
goose-bridge-ctl benchmark  # 性能基准测试
goose-bridge-ctl test       # 测试说明

# 安全组检查
goose-bridge-security-check # 检查AWS安全组配置
```

### 传统systemctl命令

```bash
sudo systemctl start goose-bridge    # 启动服务
sudo systemctl stop goose-bridge     # 停止服务
sudo systemctl status goose-bridge   # 查看状态
sudo systemctl enable goose-bridge   # 开机启动
sudo journalctl -u goose-bridge -f   # 查看日志
```

### 重要文件位置

- **主程序**: `/usr/local/bin/goose-bridge`
- **监控工具**: `/usr/local/bin/goose-bridge-monitor`
- **基准测试**: `/usr/local/bin/goose-bridge-benchmark`
- **管理脚本**: `/usr/local/bin/goose-bridge-ctl`
- **安全组检查**: `/usr/local/bin/goose-bridge-security-check`
- **配置文件**: `/etc/goose-bridge/goose-bridge.conf`
- **日志文件**: `/var/log/goose-bridge.log`
- **统计文件**: `/var/lib/goose-bridge/stats.json`

## 🧪 测试工具

### 基础功能测试

```bash
# 进入测试目录
cd tests

# 基础多播测试
python3 basic_ip_multicast_test.py

# IGMP功能测试
python3 igmp_multicast_test.py

# AWS TGW IGMP验证
python3 aws_tgw_igmp_validator.py status
```

### libiec61850测试

```bash
# 发送端（终端1）
sudo ./goose_publisher_example goose0

# 接收端（终端2）
sudo ./goose_subscriber_example goose0
```

### 性能基准测试

```bash
# 吞吐量测试
goose-bridge-ctl benchmark throughput --rate 1000 --duration 60

# 延迟测试
goose-bridge-ctl benchmark latency --count 10000

# 压力测试
goose-bridge-ctl benchmark throughput --rate 2000 --packet-size 1000
```

### IGMP生命周期测试

```bash
cd tests

# 监控IGMP生命周期
python3 igmp_lifecycle_monitor_fixed.py monitor --duration 300

# AWS TGW超时机制测试
python3 aws_tgw_igmp_validator.py timeout
```

## 📊 监控和诊断

### 实时监控

```bash
# 实时服务监控
goose-bridge-ctl monitor

# 实时日志
goose-bridge-ctl logs

# 端口状态检查
goose-bridge-ctl ports
```

### 统计信息

服务提供详细的统计信息：
- GOOSE帧处理统计
- IGMP保活统计
- 错误和重注册统计
- 性能吞吐量统计

### 日志文件

- **服务日志**: `/var/log/goose-bridge.log`
- **统计文件**: `/var/lib/goose-bridge/stats.json`
- **系统日志**: `journalctl -u goose-bridge`

### 健康检查

```bash
# 服务状态
goose-bridge-ctl status

# 安全组配置
goose-bridge-security-check

# IGMP状态验证
cd tests && python3 aws_tgw_igmp_validator.py status
```

## 📈 性能优化

### 预期性能指标

- **吞吐量**: 1000+ GOOSE帧/秒
- **延迟**: < 1ms (局域网)
- **可靠性**: 99.9%+ 可用性
- **资源使用**: < 100MB内存，< 5% CPU

### 性能调优

#### 编辑配置文件
```bash
sudo nano /etc/goose-bridge/goose-bridge.conf
sudo systemctl reload goose-bridge
```

#### 系统级优化
```bash
# 网络缓冲区优化（安装脚本自动配置）
sysctl net.core.rmem_max
sysctl net.core.wmem_max

# IGMP参数优化
sysctl net.ipv4.conf.all.force_igmp_version
```

## 🚨 故障排除

### 常见问题

#### 1. 服务启动失败
```bash
sudo systemctl status goose-bridge
journalctl -u goose-bridge -n 50
```

#### 2. GOOSE帧无法检测
```bash
goose-bridge-security-check
goose-bridge-ctl ports
```

#### 3. 跨实例通信失败
```bash
cd tests
python3 aws_tgw_igmp_validator.py status
```

#### 4. 权限问题
```bash
# 确保以root权限运行安装脚本
sudo ./scripts/install-goose-bridge.sh
```

#### 5. Python依赖问题
```bash
# 检查Python版本
python3 --version

# 检查依赖
python3 -c "import socket, struct, select, threading"
```

#### 6. AWS配置问题
```bash
# 检查AWS CLI
aws --version
aws sts get-caller-identity

# 检查实例元数据
curl http://169.254.169.254/latest/meta-data/instance-id
```

### 诊断工具

- `goose-bridge-ctl status` - 服务状态
- `goose-bridge-security-check` - 安全组检查
- `tests/igmp_lifecycle_monitor_fixed.py` - IGMP生命周期监控
- `tests/aws_tgw_igmp_validator.py` - AWS TGW验证

## 🏗️ 架构说明

### IGMP保活机制

基于AWS官方文档的TGW IGMP机制：
- **TGW查询周期**: 每2分钟发送IGMPv2 QUERY
- **临时移除**: 连续3次未响应（6分钟）
- **保活策略**: 每90秒刷新IGMP注册
- **监控策略**: 每120秒检查注册状态
- **自动重注册**: 连续2次检查失败时自动重新注册

### 单端口优化

- **优化前**: 需要开放61850 + 61860两个端口
- **优化后**: 只需开放61850一个端口
- **IGMP保活**: 纯IGMP操作，无端口占用
- **安全组简化**: 减少50%的安全组规则

### 网络架构

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   libiec61850   │    │  GOOSE Bridge    │    │   AWS TGW       │
│   Application   │◄──►│     Service      │◄──►│ Multicast Domain│
│                 │    │                  │    │                 │
│ goose_publisher │    │ ┌──────────────┐ │    │ ┌─────────────┐ │
│ goose_subscriber│    │ │ TAP Interface│ │    │ │IGMP Keepalive│ │
└─────────────────┘    │ │   (goose0)   │ │    │ │  Management │ │
                       │ └──────────────┘ │    │ └─────────────┘ │
                       │ ┌──────────────┐ │    └─────────────────┘
                       │ │UDP Multicast │ │
                       │ │  (224.0.1.100│ │
                       │ │    :61850)   │ │
                       │ └──────────────┘ │
                       └──────────────────┘
```