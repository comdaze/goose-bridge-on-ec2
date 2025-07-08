# GOOSE Protocol Cloud Bridge Service

🚀 **GOOSE协议云端桥接服务** - 专为AWS环境优化的工业协议云端部署解决方案

[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](./VERSION)
[![License](https://img.shields.io/badge/license-Industrial-green.svg)](#)
[![AWS](https://img.shields.io/badge/AWS-TGW%20Optimized-orange.svg)](#)

## 🎯 项目概述

这是一个完整的GOOSE协议云端桥接服务，支持libiec61850和其他IEC 61850应用在AWS云环境中的部署。通过透明的协议转换，实现工业设备软件系统在云端互联测试验证。可以了解方案的详细[架构和原理](docs/Solution-Architecture.md)。

### 核心特性

- ✅ **IGMP保活机制** - 防止AWS TGW 6分钟超时，基于官方文档优化
- ✅ **VLAN GOOSE帧支持** - 完全兼容libiec61850和工业标准
- ✅ **高性能异步处理** - 支持1000+ GOOSE帧/秒，生产级性能
- ✅ **智能监控重注册** - 自动检测和恢复注册状态
- ✅ **AWS TGW优化** - 基于官方文档的最佳实践配置


## 部署手册

### 系统要求

- **操作系统**: Amazon Linux 2023(推荐)，Amazon Linux 2，Centos 9/10（需验证）
- **Python**: 3.6+
- **Linux权限**: root权限
- **关键工具**: aws cli, git, gcc
- **AWS EC2 Role权限**: 临时赋予EC2，VPC 管理员

### AWS基础设施准备（在跳板机运行以下命令）
```bash
# 1.1 创建单个VPC和子网
aws ec2 create-vpc --cidr-block 10.0.0.0/16 --tag-specifications 'ResourceType=vpc,Tags=[{Key=Name,Value=GOOSE-VPC}]'
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=tag:Name,Values=GOOSE-VPC" --query 'Vpcs[0].VpcId' --output text)

# 创建单个子网（三个EC2在同一子网）
aws ec2 create-subnet --vpc-id $VPC_ID --cidr-block 10.0.1.0/24 --availability-zone cn-northweast-1a \
    --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=GOOSE-Subnet}]'
SUBNET_ID=$(aws ec2 describe-subnets --filters "Name=tag:Name,Values=GOOSE-Subnet" --query 'Subnets[0].SubnetId' --output text)

# 1.2 创建支持多播的TGW
aws ec2 create-transit-gateway --description "GOOSE Single VPC TGW" \
    --options MulticastSupport=enable,AutoAcceptSharedAssociations=enable \
    --tag-specifications 'ResourceType=transit-gateway,Tags=[{Key=Name,Value=GOOSE-TGW}]'
TGW_ID=$(aws ec2 describe-transit-gateways --filters "Name=tag:Name,Values=GOOSE-TGW" --query 'TransitGateways[0].TransitGatewayId' --output text)

# 1.3 创建IGMP多播域
aws ec2 create-transit-gateway-multicast-domain --transit-gateway-id $TGW_ID \
    --options Igmp=enable,AutoAcceptSharedAssociations=enable \
    --tag-specifications 'ResourceType=transit-gateway-multicast-domain,Tags=[{Key=Name,Value=GOOSE-MulticastDomain}]'
MCAST_DOMAIN_ID=$(aws ec2 describe-transit-gateway-multicast-domains --filters "Name=tag:Name,Values=GOOSE-MulticastDomain" --query 'TransitGatewayMulticastDomains[0].TransitGatewayMulticastDomainId' --output text)

# 1.4 关联VPC到TGW
aws ec2 create-transit-gateway-vpc-attachment --transit-gateway-id $TGW_ID --vpc-id $VPC_ID --subnet-ids $SUBNET_ID \
    --tag-specifications 'ResourceType=transit-gateway-attachment,Tags=[{Key=Name,Value=GOOSE-VPC-Attachment}]'
TGW_ATTACHMENT_ID=$(aws ec2 describe-transit-gateway-vpc-attachments --filters "Name=tag:Name,Values=GOOSE-VPC-Attachment" --query 'TransitGatewayVpcAttachments[0].TransitGatewayAttachmentId' --output text)

# 1.5 关联子网到多播域
aws ec2 associate-transit-gateway-multicast-domain \
    --transit-gateway-multicast-domain-id $MCAST_DOMAIN_ID \
    --transit-gateway-attachment-id $TGW_ATTACHMENT_ID \
    --subnet-ids $SUBNET_ID

# 1.6 配置安全组（VPC内通信）
aws ec2 create-security-group --group-name goose-single-vpc-sg --description "GOOSE Single VPC Security Group" --vpc-id $VPC_ID
SG_ID=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=goose-single-vpc-sg" --query 'SecurityGroups[0].GroupId' --output text)

# 允许VPC内UDP通信
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol udp --port 61850 --cidr 10.0.0.0/16 # 必须添加，非常重要
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol 2 --port -1 --cidr 0.0.0.0/32 # 必须添加，非常重要
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol all --source-group $SG_ID # 在安全组中的所有实例，所有流量互通，根据情况可选
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 22 --cidr 0.0.0.0/0  # SSH访问,根据情况设定源地址
```

### 步骤2: EC2实例部署（三个实例）
```bash
# 2.1 启动三个EC2实例在同一子网

# 获取 Amazon Linux 2023 的最新 AMI Id
AMI_ID=$(aws ec2 describe-images --region cn-northwest-1 --owners amazon --filters "Name=name,Values=al2023-ami-*" "Name=architecture,Values=x86_64"  "Name=virtualization-type,Values=hvm" "Name=state,Values=available"  --query 'Images | sort_by(@, &CreationDate) | [-1].ImageId'  --output text)

# 创建EC2 密钥对
aws ec2 create-key-pair \
    --region cn-northwest-1 \
    --key-name goose-bridge-key-nw \
    --query 'KeyMaterial' \
    --output text > ~/.ssh/goose-bridge-key-nw.pem
chmod 400 ~/.ssh/*.pem

# EC2-A (发布者)
aws ec2 run-instances --image-id $AMI_ID --instance-type t3.medium \
    --key-name goose-bridge-key-nw --security-group-ids $SG_ID --subnet-id $SUBNET_ID \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=GOOSE-Publisher-A}]' \
    --user-data '#!/bin/bash
yum update -y
yum install -y python3 python3-pip gcc make cmake git tcpdump
echo "GOOSE Publisher EC2-A ready" > /tmp/setup-complete'

# EC2-B (订阅者1)
aws ec2 run-instances --image-id $AMI_ID --instance-type t3.medium \
    --key-name goose-bridge-key-nw --security-group-ids $SG_ID --subnet-id $SUBNET_ID \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=GOOSE-Subscriber-B}]' \
    --user-data '#!/bin/bash
yum update -y
yum install -y python3 python3-pip gcc make cmake git tcpdump
echo "GOOSE Subscriber EC2-B ready" > /tmp/setup-complete'

# EC2-C (订阅者2)
aws ec2 run-instances --image-id $AMI_ID --instance-type t3.medium \
    --key-name goose-bridge-key-nw --security-group-ids $SG_ID --subnet-id $SUBNET_ID \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=GOOSE-Subscriber-C}]' \
    --user-data '#!/bin/bash
yum update -y
yum install -y python3 python3-pip gcc make cmake git tcpdump
echo "GOOSE Subscriber EC2-C ready" > /tmp/setup-complete'

# 2.2 获取实例IP地址
EC2_A_IP=$(aws ec2 describe-instances --filters "Name=tag:Name,Values=GOOSE-Publisher-A" "Name=instance-state-name,Values=running" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
EC2_B_IP=$(aws ec2 describe-instances --filters "Name=tag:Name,Values=GOOSE-Subscriber-B" "Name=instance-state-name,Values=running" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
EC2_C_IP=$(aws ec2 describe-instances --filters "Name=tag:Name,Values=GOOSE-Subscriber-C" "Name=instance-state-name,Values=running" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)

echo "EC2-A (Publisher): $EC2_A_IP"
echo "EC2-B (Subscriber): $EC2_B_IP"  
echo "EC2-C (Subscriber): $EC2_C_IP"

# 2.3 禁用源/目标流量检查
EC2_A_ID=$(aws ec2 describe-instances --filters "Name=tag:Name,Values=GOOSE-Publisher-A" --query 'Reservations[*].Instances[*].InstanceId' --output text)
aws ec2 modify-instance-attribute --instance-id $EC2_A_ID --no-source-dest-check

EC2_B_ID=$(aws ec2 describe-instances --filters "Name=tag:Name,Values=GOOSE-Publisher-B" --query 'Reservations[*].Instances[*].InstanceId' --output text)
aws ec2 modify-instance-attribute --instance-id $EC2_B_ID --no-source-dest-check

EC2_C_ID=$(aws ec2 describe-instances --filters "Name=tag:Name,Values=GOOSE-Publisher-C" --query 'Reservations[*].Instances[*].InstanceId' --output text)
aws ec2 modify-instance-attribute --instance-id $EC2_C_ID --no-source-dest-check

```

### 自动化快速部署

在每个实例上运行安装，或者在一个实例上运行安装后，创建自定义 AMI 系统镜像，然后利用这个系统镜像创建其他实例。

#### 1. 进入项目目录
```bash
ssh -i goose-bridge-key-nw.pem ec2-user@$EC2_A_IP
git clone https://github.com/comdaze/goose-bridge-on-ec2.git
cd goose-bridge-on-ec2
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

# 开机启动
sudo systemctl enable goose-bridge

# 检查状态
goose-bridge-ctl status
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

# 开机启动
sudo systemctl enable goose-bridge

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
# 发送端实例
git clone https://github.com/mz-automation/libiec61850.git
cd libiec61850
make examples
sudo ./examples/goose_publisher/goose_publisher_example goose0

# 接收端实例
git clone https://github.com/mz-automation/libiec61850.git
cd libiec61850
make examples
sudo ./examples/goose_subscriber/goose_subscriber_example goose0
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
# 1. 首先获取会话令牌：

TOKEN=curl -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600"

#这个命令会创建一个有效期为 6 小时（21600 秒）的令牌。

# 2. 使用令牌访问元数据：

curl -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/
#查看实例 ID：

curl -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/instance-id
```

### 诊断工具

- `goose-bridge-ctl status` - 服务状态
- `goose-bridge-security-check` - 安全组检查
- `tests/igmp_lifecycle_monitor_fixed.py` - IGMP生命周期监控
- `tests/aws_tgw_igmp_validator.py` - AWS TGW验证

