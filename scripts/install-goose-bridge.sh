#!/bin/bash
# GOOSE桥接服务安装脚本 - 支持新环境和重新安装
# 支持AWS TGW IGMP保活和自动重注册功能

set -e

# 解析命令行参数
FORCE_INSTALL=false
SKIP_CONFIG=false
QUIET=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --force|-f)
            FORCE_INSTALL=true
            shift
            ;;
        --skip-config|-s)
            SKIP_CONFIG=true
            shift
            ;;
        --quiet|-q)
            QUIET=true
            shift
            ;;
        --help|-h)
            echo "GOOSE桥接服务安装脚本"
            echo ""
            echo "用法: $0 [选项]"
            echo ""
            echo "选项:"
            echo "  -f, --force        强制安装，覆盖现有配置"
            echo "  -s, --skip-config  跳过配置文件更新"
            echo "  -q, --quiet        静默模式"
            echo "  -h, --help         显示帮助信息"
            echo ""
            echo "使用场景:"
            echo "  新环境安装:     $0"
            echo "  强制重新安装:   $0 --force"
            echo "  只更新程序:     $0 --skip-config"
            exit 0
            ;;
        *)
            echo "未知选项: $1"
            echo "使用 $0 --help 查看帮助"
            exit 1
            ;;
    esac
done

if [[ "$QUIET" != "true" ]]; then
    echo "🚀 安装GOOSE桥接服务"
    echo "=================================================="
    if [[ "$FORCE_INSTALL" == "true" ]]; then
        echo "⚠️  强制安装模式 - 将覆盖现有配置"
    fi
    if [[ "$SKIP_CONFIG" == "true" ]]; then
        echo "ℹ️  跳过配置文件更新"
    fi
    echo ""
fi

# 检查权限
if [[ $EUID -ne 0 ]]; then
   echo "❌ 此脚本需要root权限运行"
   exit 1
fi

# 检查是否为重新安装
REINSTALL=false
if [[ -f /usr/local/bin/goose-bridge ]] || [[ -f /etc/goose-bridge/goose-bridge.conf ]]; then
    REINSTALL=true
    if [[ "$QUIET" != "true" ]]; then
        echo "🔍 检测到现有安装"
    fi
    
    # 检查服务状态
    if systemctl is-active --quiet goose-bridge 2>/dev/null; then
        if [[ "$QUIET" != "true" ]]; then
            echo "🛑 停止正在运行的服务..."
        fi
        systemctl stop goose-bridge
        echo "   ✅ 服务已停止"
    fi
fi

# 获取当前脚本目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "📁 脚本目录: $SCRIPT_DIR"

# 检查必需文件
echo "🔍 检查必需文件..."
REQUIRED_FILES=(
    "../src/goose-bridge.py"
    "../config/goose-bridge.conf"
    "../config/goose-bridge.service"
    "goose-bridge-monitor.py"
    "goose-bridge-benchmark.py"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [[ ! -f "$SCRIPT_DIR/$file" ]]; then
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
cp "$SCRIPT_DIR/../src/goose-bridge.py" /usr/local/bin/goose-bridge
chmod +x /usr/local/bin/goose-bridge
echo "   ✅ 主程序: /usr/local/bin/goose-bridge"

# 复制监控工具
cp "$SCRIPT_DIR/goose-bridge-monitor.py" /usr/local/bin/goose-bridge-monitor
chmod +x /usr/local/bin/goose-bridge-monitor
echo "   ✅ 监控工具: /usr/local/bin/goose-bridge-monitor"

# 复制基准测试工具
cp "$SCRIPT_DIR/goose-bridge-benchmark.py" /usr/local/bin/goose-bridge-benchmark
chmod +x /usr/local/bin/goose-bridge-benchmark
echo "   ✅ 基准测试工具: /usr/local/bin/goose-bridge-benchmark"

# 复制配置文件
echo "⚙️  安装配置文件..."
CONFIG_ACTION=""

if [[ "$SKIP_CONFIG" == "true" ]]; then
    echo "   ⏭️  跳过配置文件更新"
    CONFIG_ACTION="skipped"
elif [[ ! -f /etc/goose-bridge/goose-bridge.conf ]]; then
    # 新安装
    cp "$SCRIPT_DIR/../config/goose-bridge.conf" /etc/goose-bridge/goose-bridge.conf
    chmod 644 /etc/goose-bridge/goose-bridge.conf
    echo "   ✅ 新配置文件: /etc/goose-bridge/goose-bridge.conf"
    CONFIG_ACTION="new"
elif [[ "$FORCE_INSTALL" == "true" ]]; then
    # 强制覆盖
    cp /etc/goose-bridge/goose-bridge.conf /etc/goose-bridge/goose-bridge.conf.backup.$(date +%Y%m%d_%H%M%S)
    cp "$SCRIPT_DIR/../config/goose-bridge.conf" /etc/goose-bridge/goose-bridge.conf
    chmod 644 /etc/goose-bridge/goose-bridge.conf
    echo "   ✅ 配置文件已更新 (旧配置已备份)"
    CONFIG_ACTION="updated"
else
    # 保留现有配置，创建新配置供参考
    cp "$SCRIPT_DIR/../config/goose-bridge.conf" /etc/goose-bridge/goose-bridge.conf.new
    echo "   ⚠️  配置文件已存在，新配置保存为: /etc/goose-bridge/goose-bridge.conf.new"
    echo "   💡 使用 --force 选项可强制更新配置文件"
    echo "   💡 使用以下命令比较配置差异:"
    echo "      diff /etc/goose-bridge/goose-bridge.conf /etc/goose-bridge/goose-bridge.conf.new"
    CONFIG_ACTION="preserved"
fi

# 安装systemd服务
echo "🔧 安装systemd服务..."
cp "$SCRIPT_DIR/../config/goose-bridge.service" /etc/systemd/system/
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
    INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null || echo "")
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

# 根据配置文件处理情况选择检查的文件
CONFIG_FILE_TO_CHECK="/etc/goose-bridge/goose-bridge.conf"
if [[ "$CONFIG_ACTION" == "preserved" ]] && [[ -f /etc/goose-bridge/goose-bridge.conf.new ]]; then
    # 如果保留了旧配置，检查新配置文件中的TGW设置
    TGW_DOMAIN_ID=$(grep 'tgw_multicast_domain_id' /etc/goose-bridge/goose-bridge.conf.new 2>/dev/null | cut -d'=' -f2 | tr -d ' ' || echo "")
    if [[ -n "$TGW_DOMAIN_ID" ]]; then
        echo "   💡 新配置文件中包含TGW多播域ID: $TGW_DOMAIN_ID"
        echo "   💡 当前使用的配置文件可能缺少TGW配置"
        echo "   💡 建议使用 --force 选项更新配置，或手动合并配置"
    fi
    # 同时检查当前配置文件
    TGW_DOMAIN_ID_CURRENT=$(grep 'tgw_multicast_domain_id' /etc/goose-bridge/goose-bridge.conf 2>/dev/null | cut -d'=' -f2 | tr -d ' ' || echo "")
    if [[ -n "$TGW_DOMAIN_ID_CURRENT" ]]; then
        TGW_DOMAIN_ID="$TGW_DOMAIN_ID_CURRENT"
        echo "   ✅ 当前配置中的TGW多播域ID: $TGW_DOMAIN_ID"
    else
        echo "   ⚠️  当前配置文件中未找到TGW多播域ID"
    fi
else
    # 检查当前配置文件
    TGW_DOMAIN_ID=$(grep 'tgw_multicast_domain_id' /etc/goose-bridge/goose-bridge.conf 2>/dev/null | cut -d'=' -f2 | tr -d ' ' || echo "")
fi

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
    if [[ "$CONFIG_ACTION" == "preserved" ]]; then
        echo "   ⚠️  当前配置文件中未找到TGW多播域ID"
        echo "   💡 新配置文件可能包含TGW配置，建议使用 --force 选项更新"
    else
        echo "   ⚠️  配置文件中未找到TGW多播域ID"
        echo "   💡 请编辑配置文件添加TGW多播域ID"
    fi
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
        netstat -ulnp | grep python3 | grep -E ':(61850|61860)' || echo "  无相关端口监听"
        echo ""
        echo "安全组配置建议:"
        echo "  类型: Custom UDP"
        echo "  端口: 61850"
        echo "  来源: 0.0.0.0/0 (或指定IP范围)"
        echo "  描述: GOOSE Protocol Bridge Service"
        ;;
    benchmark)
        echo "🏃 运行GOOSE桥接服务基准测试:"
        shift
        goose-bridge-benchmark "$@"
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
        ;;
    *)
        echo "GOOSE桥接服务管理工具"
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
        echo "  benchmark - 运行基准测试"
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
# GOOSE桥接服务安全组配置检查脚本 - 支持IMDSv2

echo "🔒 GOOSE桥接服务安全组配置检查"
echo "=================================="

# 获取IMDSv2 token
get_imds_token() {
    curl -s -X PUT "http://169.254.169.254/latest/api/token" \
         -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" \
         --connect-timeout 5 2>/dev/null
}

# 使用token获取元数据
get_metadata() {
    local token="$1"
    local path="$2"
    if [[ -n "$token" ]]; then
        curl -s -H "X-aws-ec2-metadata-token: $token" \
             "http://169.254.169.254/latest/meta-data/$path" \
             --connect-timeout 5 2>/dev/null
    else
        # 回退到IMDSv1
        curl -s "http://169.254.169.254/latest/meta-data/$path" \
             --connect-timeout 5 2>/dev/null
    fi
}

# 检查当前实例的安全组
if command -v aws &> /dev/null; then
    echo "🔍 检查AWS环境..."
    
    # 获取IMDSv2 token
    TOKEN=$(get_imds_token)
    if [[ -n "$TOKEN" ]]; then
        echo "   ✅ 获取到IMDSv2 token"
    else
        echo "   ⚠️  使用IMDSv1模式"
    fi
    
    # 获取实例ID
    INSTANCE_ID=$(get_metadata "$TOKEN" "instance-id")
    
    if [[ -n "$INSTANCE_ID" && "$INSTANCE_ID" != "404" ]]; then
        echo "   ✅ 实例ID: $INSTANCE_ID"
        
        # 获取安全组ID
        SECURITY_GROUPS=$(aws ec2 describe-instances --instance-ids $INSTANCE_ID --query 'Reservations[*].Instances[*].SecurityGroups[*].GroupId' --output text 2>/dev/null || echo "")
        
        if [[ -n "$SECURITY_GROUPS" ]]; then
            echo "   ✅ 安全组: $SECURITY_GROUPS"
            
            for SG_ID in $SECURITY_GROUPS; do
                echo ""
                echo "🔍 检查安全组 $SG_ID 的UDP 61850端口配置:"
                
                # 获取安全组名称
                SG_NAME=$(aws ec2 describe-security-groups --group-ids $SG_ID --query 'SecurityGroups[0].GroupName' --output text 2>/dev/null || echo "Unknown")
                echo "   安全组名称: $SG_NAME"
                
                # 检查入站规则
                RULE_CHECK=$(aws ec2 describe-security-groups --group-ids $SG_ID --query "SecurityGroups[0].IpPermissions[?IpProtocol=='udp' && (FromPort<=\`61850\` && ToPort>=\`61850\`)]" --output json 2>/dev/null)
                
                if [[ -n "$RULE_CHECK" && "$RULE_CHECK" != "[]" && "$RULE_CHECK" != "null" ]]; then
                    echo "   ✅ UDP 61850端口规则已配置"
                    echo "   规则详情:"
                    aws ec2 describe-security-groups --group-ids $SG_ID --query "SecurityGroups[0].IpPermissions[?IpProtocol=='udp' && (FromPort<=\`61850\` && ToPort>=\`61850\`)]" --output table 2>/dev/null || echo "   详细信息获取失败"
                else
                    echo "   ❌ UDP 61850端口规则未配置"
                    echo "   建议添加规则:"
                    echo "     aws ec2 authorize-security-group-ingress \\"
                    echo "       --group-id $SG_ID \\"
                    echo "       --protocol udp \\"
                    echo "       --port 61850 \\"
                    echo "       --cidr 0.0.0.0/0"
                    echo ""
                    echo "   或者使用AWS控制台添加规则:"
                    echo "     类型: 自定义UDP"
                    echo "     端口范围: 61850"
                    echo "     来源: 0.0.0.0/0 (或指定IP范围)"
                    echo "     描述: GOOSE Protocol Bridge Service"
                fi
            done
            
            echo ""
            echo "🔍 检查出站规则..."
            # 检查出站规则（通常默认允许所有出站流量）
            for SG_ID in $SECURITY_GROUPS; do
                EGRESS_RULES=$(aws ec2 describe-security-groups --group-ids $SG_ID --query 'SecurityGroups[0].IpPermissionsEgress' --output json 2>/dev/null)
                if [[ -n "$EGRESS_RULES" && "$EGRESS_RULES" != "[]" ]]; then
                    echo "   ✅ 安全组 $SG_ID 有出站规则配置"
                else
                    echo "   ⚠️  安全组 $SG_ID 出站规则检查失败"
                fi
            done
            
        else
            echo "   ❌ 无法获取安全组信息"
            echo "   可能原因:"
            echo "   1. AWS CLI权限不足"
            echo "   2. 实例角色缺少EC2描述权限"
            echo "   3. AWS CLI配置问题"
        fi
        
        # 检查网络接口配置
        echo ""
        echo "🔍 检查网络接口配置..."
        ENI_ID=$(aws ec2 describe-instances --instance-ids $INSTANCE_ID --query 'Reservations[*].Instances[*].NetworkInterfaces[0].NetworkInterfaceId' --output text 2>/dev/null || echo "")
        
        if [[ -n "$ENI_ID" && "$ENI_ID" != "None" ]]; then
            echo "   ✅ 网络接口: $ENI_ID"
            
            # 检查源/目标检查状态
            SOURCE_DEST_CHECK=$(aws ec2 describe-network-interface-attribute --network-interface-id $ENI_ID --attribute sourceDestCheck --query 'SourceDestCheck.Value' --output text 2>/dev/null || echo "Unknown")
            if [[ "$SOURCE_DEST_CHECK" == "False" ]]; then
                echo "   ✅ 源/目标检查已禁用 (适合多播)"
            elif [[ "$SOURCE_DEST_CHECK" == "True" ]]; then
                echo "   ⚠️  源/目标检查已启用，建议禁用以支持多播"
                echo "   禁用命令:"
                echo "     aws ec2 modify-network-interface-attribute --network-interface-id $ENI_ID --no-source-dest-check"
            else
                echo "   ❓ 源/目标检查状态: $SOURCE_DEST_CHECK"
            fi
        else
            echo "   ❌ 无法获取网络接口ID"
        fi
        
    else
        echo "   ❌ 无法获取实例ID"
        echo "   可能原因:"
        echo "   1. 不在AWS EC2环境中运行"
        echo "   2. IMDSv2配置问题"
        echo "   3. 网络连接问题"
        echo "   4. 实例元数据服务被禁用"
        
        # 提供诊断信息
        echo ""
        echo "🔧 诊断信息:"
        echo "   检查IMDS配置:"
        echo "     curl -s http://169.254.169.254/latest/meta-data/"
        echo "   检查IMDSv2:"
        echo "     TOKEN=\$(curl -X PUT \"http://169.254.169.254/latest/api/token\" -H \"X-aws-ec2-metadata-token-ttl-seconds: 21600\")"
        echo "     curl -H \"X-aws-ec2-metadata-token: \$TOKEN\" http://169.254.169.254/latest/meta-data/instance-id"
    fi
else
    echo "   ❌ AWS CLI未安装"
    echo "   请安装AWS CLI: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
fi

echo ""
echo "📋 手动配置说明:"
echo "在AWS控制台 > EC2 > 安全组中添加入站规则:"
echo "  类型: 自定义UDP"
echo "  端口范围: 61850"
echo "  来源: 0.0.0.0/0 (或指定IP范围)"
echo "  描述: GOOSE Protocol Bridge Service"
echo ""
echo "🔧 网络配置建议:"
echo "  1. 禁用源/目标检查 (支持多播转发)"
echo "  2. 确保VPC启用多播支持"
echo "  3. 配置Transit Gateway多播域"
echo "  4. 检查路由表配置"
echo ""
echo "🧪 测试连接:"
echo "  本地测试: nc -u -l 61850"
echo "  发送测试: echo 'test' | nc -u <target-ip> 61850"
echo "  多播测试: 运行 goose-bridge-ctl test"
EOF

chmod +x /usr/local/bin/goose-bridge-security-check
echo "   ✅ 安全组检查脚本: /usr/local/bin/goose-bridge-security-check"

echo ""
echo "✅ GOOSE桥接服务安装完成！"
echo ""

# 根据安装类型显示不同信息
if [[ "$REINSTALL" == "true" ]]; then
    echo "🔄 重新安装完成"
    if [[ "$CONFIG_ACTION" == "updated" ]]; then
        echo "   ✅ 配置文件已更新"
    elif [[ "$CONFIG_ACTION" == "preserved" ]]; then
        echo "   ⚠️  配置文件已保留，新配置可在 .new 文件中查看"
    fi
else
    echo "🆕 新环境安装完成"
fi

# 启动服务（如果不是跳过配置模式）
if [[ "$SKIP_CONFIG" != "true" ]]; then
    echo ""
    echo "🚀 启动服务..."
    if systemctl start goose-bridge; then
        echo "   ✅ 服务启动成功"
        
        # 启用开机自启动
        if systemctl enable goose-bridge; then
            echo "   ✅ 已设置开机自启动"
        fi
        
        # 显示服务状态
        echo ""
        echo "📊 服务状态:"
        systemctl status goose-bridge --no-pager -l || true
    else
        echo "   ❌ 服务启动失败"
        echo "   💡 请检查配置文件和日志:"
        echo "      sudo journalctl -u goose-bridge -n 20"
    fi
else
    echo ""
    echo "⏭️  跳过了服务启动（--skip-config 模式）"
    echo "   手动启动: sudo systemctl start goose-bridge"
fi
echo ""
echo "🎯 特性说明:"
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
echo "  基准测试: goose-bridge-ctl benchmark"
echo "  安全组检查: goose-bridge-security-check"
echo ""
echo "🔧 重新安装选项:"
echo "  强制重新安装: sudo $0 --force"
echo "  只更新程序: sudo $0 --skip-config"
echo "  查看帮助: $0 --help"
echo ""
echo "📋 传统systemctl命令:"
echo "  启动服务: sudo systemctl start goose-bridge"
echo "  停止服务: sudo systemctl stop goose-bridge"
echo "  查看状态: sudo systemctl status goose-bridge"
echo "  开机启动: sudo systemctl enable goose-bridge"
echo "  查看日志: sudo journalctl -u goose-bridge -f"
echo ""
echo "📁 重要文件位置:"
echo "  主程序: /usr/local/bin/goose-bridge"
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
if [[ "$CONFIG_ACTION" == "preserved" ]]; then
    echo "  ⚠️  当前使用旧配置文件，建议更新:"
    echo "     比较配置: diff /etc/goose-bridge/goose-bridge.conf /etc/goose-bridge/goose-bridge.conf.new"
    echo "     强制更新: sudo $0 --force"
    echo "     手动编辑: sudo nano /etc/goose-bridge/goose-bridge.conf"
elif [[ "$CONFIG_ACTION" == "updated" ]] || [[ "$CONFIG_ACTION" == "new" ]]; then
    echo "  ✅ 使用最新配置文件"
    echo "     编辑配置: sudo nano /etc/goose-bridge/goose-bridge.conf"
fi
echo "  重载配置: sudo systemctl reload goose-bridge"
echo "  高负载环境: 调整 igmp_keepalive_interval = 60"
echo "  高可靠环境: 调整 igmp_reregister_threshold = 1"
echo ""
echo "🧪 测试GOOSE通信:"
echo "  1. 检查安全组: goose-bridge-security-check"
echo "  2. 启动服务: sudo goose-bridge-ctl start"
echo "  3. 检查状态: goose-bridge-ctl status"
echo "  4. 检查端口: goose-bridge-ctl ports"
echo "  5. 发送端: sudo ./goose_publisher_example goose0"
echo "  6. 接收端: sudo ./goose_subscriber_example goose0"
echo ""
echo "🎯 现在可以启动服务了:"
echo "  sudo systemctl start goose-bridge 或者 sudo goose-bridge-ctl start"
echo "  开机启动: sudo systemctl enable goose-bridge"
echo "  goose-bridge-ctl status"
echo "  goose-bridge-security-check"
