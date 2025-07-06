#!/bin/bash
# GOOSE桥接服务安装脚本 - 优化单端口版本
# 支持AWS TGW IGMP保活和自动重注册功能（单端口设计）

set -e

# AWS实例元数据获取函数 (支持IMDSv1和IMDSv2)
get_instance_metadata() {
    local path="$1"
    local result=""
    
    # 尝试IMDSv2 (推荐方式)
    local token=$(curl -s --connect-timeout 3 -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" 2>/dev/null)
    if [[ -n "$token" ]]; then
        result=$(curl -s --connect-timeout 3 -H "X-aws-ec2-metadata-token: $token" "http://169.254.169.254/latest/meta-data/$path" 2>/dev/null)
    fi
    
    # 如果IMDSv2失败，尝试IMDSv1
    if [[ -z "$result" ]]; then
        result=$(curl -s --connect-timeout 3 "http://169.254.169.254/latest/meta-data/$path" 2>/dev/null)
    fi
    
    echo "$result"
}



echo "🚀 安装生产级GOOSE桥接服务 (优化单端口版)"
echo "=================================================="

# 检查权限
if [[ $EUID -ne 0 ]]; then
   echo "❌ 此脚本需要root权限运行"
   exit 1
fi

# 获取项目根目录（脚本在scripts子目录中）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
echo "📁 项目目录: $PROJECT_DIR"
echo "📁 脚本目录: $SCRIPT_DIR"

# 检查必需文件
echo "🔍 检查必需文件..."
REQUIRED_FILES=(
    "src/goose-bridge.py"
    "config/goose-bridge.conf"
    "config/goose-bridge.service"
    "scripts/goose-bridge-monitor.py"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [[ ! -f "$PROJECT_DIR/$file" ]]; then
        echo "❌ 缺少必需文件: $file"
        exit 1
    fi
    echo "   ✅ $file"
done

# 创建必要的目录
echo "📁 创建目录结构..."
mkdir -p /etc/goose-bridge
mkdir -p /var/lib/goose-bridge
mkdir -p /var/log
mkdir -p /usr/local/bin

# 复制程序文件
echo "📋 安装程序文件..."
cp "$PROJECT_DIR/src/goose-bridge.py" /usr/local/bin/goose-bridge
chmod +x /usr/local/bin/goose-bridge
echo "   ✅ 主程序: /usr/local/bin/goose-bridge (优化单端口版)"

# 复制监控工具
cp "$PROJECT_DIR/scripts/goose-bridge-monitor.py" /usr/local/bin/goose-bridge-monitor
chmod +x /usr/local/bin/goose-bridge-monitor
echo "   ✅ 监控工具: /usr/local/bin/goose-bridge-monitor"

# 复制基准测试工具
cp "$PROJECT_DIR/scripts/goose-bridge-benchmark.py" /usr/local/bin/goose-bridge-benchmark
chmod +x /usr/local/bin/goose-bridge-benchmark
echo "   ✅ 基准测试工具: /usr/local/bin/goose-bridge-benchmark"

# 复制配置文件
echo "⚙️  安装配置文件..."
if [[ ! -f /etc/goose-bridge/goose-bridge.conf ]]; then
    cp "$PROJECT_DIR/config/goose-bridge.conf" /etc/goose-bridge/goose-bridge.conf
    chmod 644 /etc/goose-bridge/goose-bridge.conf
    echo "   ✅ 新配置文件: /etc/goose-bridge/goose-bridge.conf"
else
    cp "$PROJECT_DIR/config/goose-bridge.conf" /etc/goose-bridge/goose-bridge.conf.new
    echo "   ⚠️  配置文件已存在，新配置保存为: /etc/goose-bridge/goose-bridge.conf.new"
    echo "   请手动比较和合并配置差异"
fi

# 安装systemd服务
echo "🔧 安装systemd服务..."
cp "$PROJECT_DIR/config/goose-bridge.service" /etc/systemd/system/
chmod 644 /etc/systemd/system/goose-bridge.service

# 更新服务文件中的程序路径
sed -i 's|ExecStart=.*|ExecStart=/usr/local/bin/goose-bridge -c /etc/goose-bridge/goose-bridge.conf|' /etc/systemd/system/goose-bridge.service

# 重新加载systemd
echo "🔄 重新加载systemd..."
systemctl daemon-reload

# 检查Python依赖
echo "🐍 检查Python依赖..."
python3 -c "
import socket, struct, select, threading, time, signal, fcntl, subprocess, logging, json, configparser
print('✅ 基础依赖检查通过')
" || {
    echo "❌ Python依赖检查失败，请确保Python3已安装"
    exit 1
}

# 检查AWS CLI
echo "☁️  检查AWS CLI..."
if command -v aws &> /dev/null; then
    echo "   ✅ AWS CLI 已安装"
    
    # 检查AWS凭证
    if aws sts get-caller-identity &> /dev/null; then
        echo "   ✅ AWS凭证配置正常"
    else
        echo "   ⚠️  AWS凭证未配置或无效"
        echo "   请运行: aws configure"
    fi
else
    echo "   ❌ AWS CLI 未安装"
    echo "   请安装AWS CLI: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
fi

# 禁用源/目标检查（如果在AWS EC2上）
echo "🔧 配置AWS EC2网络..."
if command -v aws &> /dev/null; then
    # 获取当前实例的网络接口
    INSTANCE_ID=$(get_instance_metadata "instance-id")
    if [[ -n "$INSTANCE_ID" ]]; then
        echo "   检测到AWS EC2实例: $INSTANCE_ID"
        
        # 获取网络接口ID
        ENI_ID=$(aws ec2 describe-instances --instance-ids $INSTANCE_ID --query 'Reservations[*].Instances[*].NetworkInterfaces[0].NetworkInterfaceId' --output text 2>/dev/null || echo "")
        
        if [[ -n "$ENI_ID" && "$ENI_ID" != "None" ]]; then
            echo "   网络接口: $ENI_ID"
            
            # 检查当前源/目标检查状态
            CURRENT_CHECK=$(aws ec2 describe-network-interface-attribute --network-interface-id $ENI_ID --attribute sourceDestCheck --query 'SourceDestCheck.Value' --output text 2>/dev/null || echo "")
            
            if [[ "$CURRENT_CHECK" == "True" ]]; then
                echo "   正在禁用源/目标检查..."
                if aws ec2 modify-network-interface-attribute --network-interface-id $ENI_ID --no-source-dest-check; then
                    echo "   ✅ 源/目标检查已禁用"
                else
                    echo "   ⚠️  警告: 无法禁用源/目标检查，可能需要手动配置"
                fi
            else
                echo "   ✅ 源/目标检查已禁用"
            fi
        else
            echo "   ⚠️  无法获取网络接口ID"
        fi
    else
        echo "   ℹ️  非AWS EC2环境或无法获取实例信息"
    fi
fi

# 检查TGW多播域配置
echo "🌐 检查TGW多播域配置..."
TGW_DOMAIN_ID=$(grep 'tgw_multicast_domain_id' /etc/goose-bridge/goose-bridge.conf 2>/dev/null | cut -d'=' -f2 | tr -d ' ' || echo "")
if [[ -n "$TGW_DOMAIN_ID" ]]; then
    echo "   TGW多播域ID: $TGW_DOMAIN_ID"
    
    if command -v aws &> /dev/null; then
        # 检查多播域是否存在
        if aws ec2 describe-transit-gateway-multicast-domains --transit-gateway-multicast-domain-ids $TGW_DOMAIN_ID &> /dev/null; then
            echo "   ✅ TGW多播域配置正确"
            
            # 检查当前多播组成员
            MEMBER_COUNT=$(aws ec2 search-transit-gateway-multicast-groups --transit-gateway-multicast-domain-id $TGW_DOMAIN_ID --query 'length(MulticastGroups)' --output text 2>/dev/null || echo "0")
            echo "   当前多播组成员: $MEMBER_COUNT 个"
        else
            echo "   ⚠️  TGW多播域不存在或无访问权限"
        fi
    fi
else
    echo "   ⚠️  配置文件中未找到TGW多播域ID"
fi

# 设置IGMP系统参数
echo "🔧 优化IGMP系统参数..."
cat > /etc/sysctl.d/99-goose-igmp.conf << 'EOF'
# GOOSE桥接服务IGMP优化参数
# 强制使用IGMPv2
net.ipv4.conf.all.force_igmp_version = 2
net.ipv4.conf.default.force_igmp_version = 2

# 优化IGMP报告间隔
net.ipv4.conf.all.igmpv2_unsolicited_report_interval = 5000
net.ipv4.conf.default.igmpv2_unsolicited_report_interval = 5000

# 增加多播组成员数限制
net.ipv4.igmp_max_memberships = 50

# 优化网络缓冲区
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.netdev_max_backlog = 5000
EOF

# 应用系统参数
sysctl -p /etc/sysctl.d/99-goose-igmp.conf
echo "   ✅ IGMP系统参数已优化"

# 创建日志轮转配置
echo "📝 配置日志轮转..."
cat > /etc/logrotate.d/goose-bridge << 'EOF'
/var/log/goose-bridge.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 644 root root
    postrotate
        systemctl reload goose-bridge 2>/dev/null || true
    endscript
}
EOF
echo "   ✅ 日志轮转配置已创建"

# 创建便捷脚本
echo "🛠️  创建便捷管理脚本..."
cat > /usr/local/bin/goose-bridge-ctl << 'EOF'
#!/bin/bash
# GOOSE桥接服务便捷管理脚本

case "$1" in
    start)
        echo "🚀 启动GOOSE桥接服务..."
        systemctl start goose-bridge
        ;;
    stop)
        echo "🛑 停止GOOSE桥接服务..."
        systemctl stop goose-bridge
        ;;
    restart)
        echo "🔄 重启GOOSE桥接服务..."
        systemctl restart goose-bridge
        ;;
    status)
        echo "📊 GOOSE桥接服务状态:"
        systemctl status goose-bridge
        echo ""
        goose-bridge-monitor status
        ;;
    logs)
        echo "📋 GOOSE桥接服务日志:"
        journalctl -u goose-bridge -f
        ;;
    monitor)
        echo "🔍 实时监控GOOSE桥接服务:"
        goose-bridge-monitor monitor
        ;;
    ports)
        echo "🔌 检查端口使用情况:"
        echo "GOOSE桥接服务端口:"
        sudo netstat -ulnp | grep python3 | grep -E ':(61850|61860)' || echo "  无相关端口监听"
        echo ""
        echo "安全组配置建议:"
        echo "  类型: Custom UDP"
        echo "  端口: 61850"
        echo "  来源: 0.0.0.0/0 (或指定IP范围)"
        echo "  描述: GOOSE Protocol Bridge Service"
        ;;
    benchmark)
        echo "📊 运行性能基准测试:"
        if [[ -n "$2" ]]; then
            goose-bridge-benchmark "$2" "${@:3}"
        else
            echo "用法: $0 benchmark {throughput|latency} [选项]"
            echo "示例: $0 benchmark throughput --rate 1000"
            echo "示例: $0 benchmark latency --count 5000"
        fi
        ;;
    test)
        echo "🧪 测试GOOSE桥接服务:"
        echo "请在另一个终端运行以下命令测试:"
        echo "发送端: sudo ./goose_publisher_example goose0"
        echo "接收端: sudo ./goose_subscriber_example goose0"
        echo ""
        echo "监控命令:"
        echo "实时监控: goose-bridge-ctl monitor"
        echo "查看日志: goose-bridge-ctl logs"
        echo "性能测试: goose-bridge-ctl benchmark throughput --rate 500"
        ;;
    *)
        echo "GOOSE桥接服务管理工具 (优化单端口版)"
        echo "用法: $0 {start|stop|restart|status|logs|monitor|ports|benchmark|test}"
        echo ""
        echo "命令说明:"
        echo "  start     - 启动服务"
        echo "  stop      - 停止服务"
        echo "  restart   - 重启服务"
        echo "  status    - 查看状态"
        echo "  logs      - 查看日志"
        echo "  monitor   - 实时监控"
        echo "  ports     - 检查端口和安全组配置"
        echo "  benchmark - 运行性能基准测试"
        echo "  test      - 测试说明"
        exit 1
        ;;
esac
EOF

chmod +x /usr/local/bin/goose-bridge-ctl
echo "   ✅ 管理脚本: /usr/local/bin/goose-bridge-ctl"

# 创建安全组配置检查脚本
echo "🔒 创建安全组配置检查脚本..."
cat > /usr/local/bin/goose-bridge-security-check << 'EOF'
#!/bin/bash
# GOOSE桥接服务安全组配置检查脚本

# AWS实例元数据获取函数 (支持IMDSv1和IMDSv2)
get_instance_metadata() {
    local path="$1"
    local result=""
    
    # 尝试IMDSv2 (推荐方式)
    local token=$(curl -s --connect-timeout 3 -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" 2>/dev/null)
    if [[ -n "$token" ]]; then
        result=$(curl -s --connect-timeout 3 -H "X-aws-ec2-metadata-token: $token" "http://169.254.169.254/latest/meta-data/$path" 2>/dev/null)
    fi
    
    # 如果IMDSv2失败，尝试IMDSv1
    if [[ -z "$result" ]]; then
        result=$(curl -s --connect-timeout 3 "http://169.254.169.254/latest/meta-data/$path" 2>/dev/null)
    fi
    
    echo "$result"
}

echo "🔒 GOOSE桥接服务安全组配置检查"
echo "=================================="

# 检查当前实例的安全组
if command -v aws &> /dev/null; then
    INSTANCE_ID=$(get_instance_metadata "instance-id")
    if [[ -n "$INSTANCE_ID" ]]; then
        echo "实例ID: $INSTANCE_ID"
        
        # 获取安全组ID
        SECURITY_GROUPS=$(aws ec2 describe-instances --instance-ids $INSTANCE_ID --query 'Reservations[*].Instances[*].SecurityGroups[*].GroupId' --output text 2>/dev/null || echo "")
        
        if [[ -n "$SECURITY_GROUPS" ]]; then
            echo "安全组: $SECURITY_GROUPS"
            
            for SG_ID in $SECURITY_GROUPS; do
                echo ""
                echo "检查安全组 $SG_ID 的UDP 61850端口配置:"
                
                # 检查入站规则
                RULE_EXISTS=$(aws ec2 describe-security-groups --group-ids $SG_ID --query "SecurityGroups[0].IpPermissions[?IpProtocol=='udp' && FromPort<=\`61850\` && ToPort>=\`61850\`]" --output text 2>/dev/null || echo "")
                
                if [[ -n "$RULE_EXISTS" && "$RULE_EXISTS" != "None" ]]; then
                    echo "  ✅ UDP 61850端口规则已配置"
                    aws ec2 describe-security-groups --group-ids $SG_ID --query "SecurityGroups[0].IpPermissions[?IpProtocol=='udp' && FromPort<=\`61850\` && ToPort>=\`61850\`]" --output table 2>/dev/null || echo "  详细信息获取失败"
                else
                    echo "  ❌ UDP 61850端口规则未配置"
                    echo "  建议添加规则:"
                    echo "    aws ec2 authorize-security-group-ingress \\"
                    echo "      --group-id $SG_ID \\"
                    echo "      --protocol udp \\"
                    echo "      --port 61850 \\"
                    echo "      --cidr 0.0.0.0/0"
                fi
            done
        else
            echo "❌ 无法获取安全组信息"
        fi
    else
        echo "❌ 无法获取实例ID"
    fi
else
    echo "❌ AWS CLI未安装"
fi

echo ""
echo "📋 手动配置说明:"
echo "在AWS控制台 > EC2 > 安全组中添加入站规则:"
echo "  类型: 自定义UDP"
echo "  端口范围: 61850"
echo "  来源: 0.0.0.0/0 (或指定IP范围)"
echo "  描述: GOOSE Protocol Bridge Service"
EOF

chmod +x /usr/local/bin/goose-bridge-security-check
echo "   ✅ 安全组检查脚本: /usr/local/bin/goose-bridge-security-check"

echo ""
echo "✅ GOOSE桥接服务安装完成！"
echo ""
echo "🎯 优化单端口版本特性:"
echo "  ✅ 单端口设计 - 只需开放UDP 61850端口"
echo "  ✅ 集成IGMP保活机制 - 防止AWS TGW 6分钟超时"
echo "  ✅ 智能监控和重注册 - 自动检测和恢复注册状态"
echo "  ✅ AWS TGW优化配置 - 基于官方文档的最佳实践"
echo "  ✅ VLAN GOOSE帧支持 - 完全兼容libiec61850"
echo "  ✅ 高性能异步处理 - 生产级性能和可靠性"
echo ""
echo "📋 使用方法:"
echo "  启动服务: goose-bridge-ctl start"
echo "  停止服务: goose-bridge-ctl stop"
echo "  查看状态: goose-bridge-ctl status"
echo "  实时监控: goose-bridge-ctl monitor"
echo "  查看日志: goose-bridge-ctl logs"
echo "  端口检查: goose-bridge-ctl ports"
echo "  性能测试: goose-bridge-ctl benchmark throughput --rate 1000"
echo "  安全组检查: goose-bridge-security-check"
echo ""
echo "📋 传统systemctl命令:"
echo "  启动服务: sudo systemctl start goose-bridge"
echo "  停止服务: sudo systemctl stop goose-bridge"
echo "  查看状态: sudo systemctl status goose-bridge"
echo "  开机启动: sudo systemctl enable goose-bridge"
echo "  查看日志: sudo journalctl -u goose-bridge -f"
echo ""
echo "📁 重要文件位置:"
echo "  主程序: /usr/local/bin/goose-bridge (优化单端口版)"
echo "  监控工具: /usr/local/bin/goose-bridge-monitor"
echo "  基准测试: /usr/local/bin/goose-bridge-benchmark"
echo "  管理脚本: /usr/local/bin/goose-bridge-ctl"
echo "  安全组检查: /usr/local/bin/goose-bridge-security-check"
echo "  配置文件: /etc/goose-bridge/goose-bridge.conf"
echo "  日志文件: /var/log/goose-bridge.log"
echo "  统计文件: /var/lib/goose-bridge/stats.json"
echo "  PID文件:  /var/run/goose-bridge.pid"
echo ""
echo "⚙️  IGMP保活配置说明:"
echo "  保活间隔: 90秒 (基于AWS TGW 2分钟查询周期优化)"
echo "  监控间隔: 120秒 (与TGW查询周期同步)"
echo "  重注册阈值: 2次连续失败 (在6分钟超时前重新注册)"
echo "  TGW监控: 启用 (实时监控AWS多播域状态)"
echo "  端口设计: 单端口 (纯IGMP操作，无额外端口占用)"
echo ""
echo "🔒 安全组配置 (简化版):"
echo "  只需开放一个端口: UDP 61850"
echo "  检查配置: goose-bridge-security-check"
echo "  自动配置: 脚本会尝试检测和提示配置"
echo ""
echo "🔧 配置优化建议:"
echo "  编辑配置: sudo nano /etc/goose-bridge/goose-bridge.conf"
echo "  重载配置: sudo systemctl reload goose-bridge"
echo "  高负载环境: 调整 igmp_keepalive_interval = 60"
echo "  高可靠环境: 调整 igmp_reregister_threshold = 1"
echo ""
echo "🧪 测试GOOSE通信:"
echo "  1. 检查安全组: goose-bridge-security-check"
echo "  2. 启动服务: sudo goose-bridge-ctl start"
echo "  3. 检查状态: sudo goose-bridge-ctl status"
echo "  4. 检查端口: sudo goose-bridge-ctl ports"
echo "  5. 性能测试: goose-bridge-ctl benchmark throughput --rate 500"
echo "  6. 发送端: sudo ./goose_publisher_example goose0"
echo "  7. 接收端: sudo ./goose_subscriber_example goose0"
echo ""
echo "🎯 现在可以启动服务了:"
echo "  sudo systemctl start goose-bridge 或者 sudo goose-bridge-ctl start" 
echo "  sudo systemctl status goose-bridge 或者 sudo goose-bridge-ctl status"

