#!/bin/bash
#
# 独立双路径GOOSE桥接服务安装脚本
# 支持goose0/goose1双TAP接口独立运行
#

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# 检查root权限
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "此脚本需要root权限运行"
        log_info "请使用: sudo $0"
        exit 1
    fi
}

# 检查系统要求
check_system_requirements() {
    log_step "检查系统要求..."
    
    # 检查操作系统
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        log_info "检测到操作系统: $NAME $VERSION"
        
        case $ID in
            "amzn"|"centos"|"rhel"|"fedora")
                PACKAGE_MANAGER="yum"
                ;;
            "ubuntu"|"debian")
                PACKAGE_MANAGER="apt"
                ;;
            *)
                log_warn "未完全测试的操作系统: $ID"
                PACKAGE_MANAGER="yum"  # 默认使用yum
                ;;
        esac
    else
        log_warn "无法检测操作系统，假设使用yum"
        PACKAGE_MANAGER="yum"
    fi
    
    # 检查Python版本
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
        log_info "Python版本: $PYTHON_VERSION"
        
        # 检查Python版本是否满足要求 (>= 3.6)
        if python3 -c "import sys; exit(0 if sys.version_info >= (3, 6) else 1)"; then
            log_info "Python版本满足要求"
        else
            log_error "Python版本过低，需要Python 3.6或更高版本"
            exit 1
        fi
    else
        log_error "未找到Python3，请先安装Python3"
        exit 1
    fi
    
    # 检查必要的命令
    local required_commands=("ip" "iptables" "aws")
    for cmd in "${required_commands[@]}"; do
        if command -v "$cmd" &> /dev/null; then
            log_info "找到命令: $cmd"
        else
            log_warn "未找到命令: $cmd"
            case $cmd in
                "ip")
                    log_info "将安装iproute包（提供ip命令）"
                    ;;
                "iptables")
                    log_info "将安装iptables包"
                    ;;
                "aws")
                    log_warn "AWS CLI未安装，IGMP TGW监控功能将不可用"
                    ;;
            esac
        fi
    done
}

# 安装系统依赖
install_system_dependencies() {
    log_step "安装系统依赖..."
    
    case $PACKAGE_MANAGER in
        "yum")
            yum update -y
            # 注意：Amazon Linux/CentOS/RHEL使用iproute包名，不是iproute2
            yum install -y python3 python3-pip gcc make cmake git tcpdump \
                          iproute iptables net-tools procps-ng
            ;;
        "apt")
            apt update
            # Ubuntu/Debian使用iproute2包名
            apt install -y python3 python3-pip gcc make cmake git tcpdump \
                          iproute2 iptables net-tools procps
            ;;
    esac
    
    log_info "系统依赖安装完成"
}

# 优化系统网络参数
optimize_system_network() {
    log_step "优化系统网络参数..."
    
    # 创建sysctl配置文件
    cat > /etc/sysctl.d/99-goose-bridge-dual.conf << 'EOF'
# 独立双路径GOOSE桥接服务网络优化配置

# 网络缓冲区优化（核心参数，必需）
net.core.rmem_max = 134217728
net.core.wmem_max = 134217728
net.core.rmem_default = 262144
net.core.wmem_default = 262144

# UDP缓冲区优化（GOOSE协议必需）
net.core.netdev_max_backlog = 5000
net.core.netdev_budget = 600

# 多播优化（GOOSE多播必需）
net.ipv4.conf.all.force_igmp_version = 2
net.ipv4.conf.default.force_igmp_version = 2
net.ipv4.igmp_max_memberships = 20
net.ipv4.igmp_max_msf = 10

# TAP接口优化（TAP接口必需）
net.ipv4.conf.all.accept_local = 1
net.ipv4.conf.all.route_localnet = 1

# 内核优化（性能优化）
kernel.pid_max = 4194304
vm.max_map_count = 262144
EOF
    
    # 应用sysctl配置，忽略不存在的参数
    log_info "应用网络参数配置..."
    sysctl -p /etc/sysctl.d/99-goose-bridge-dual.conf 2>/dev/null || {
        log_warn "部分网络参数无法设置（这是正常的，不影响功能）"
        
        # 逐个应用关键参数，忽略错误
        log_info "应用关键网络参数..."
        sysctl -w net.core.rmem_max=134217728 2>/dev/null || true
        sysctl -w net.core.wmem_max=134217728 2>/dev/null || true
        sysctl -w net.core.rmem_default=262144 2>/dev/null || true
        sysctl -w net.core.wmem_default=262144 2>/dev/null || true
        sysctl -w net.core.netdev_max_backlog=5000 2>/dev/null || true
        sysctl -w net.ipv4.conf.all.force_igmp_version=2 2>/dev/null || true
        sysctl -w net.ipv4.conf.default.force_igmp_version=2 2>/dev/null || true
        sysctl -w net.ipv4.igmp_max_memberships=20 2>/dev/null || true
        sysctl -w net.ipv4.conf.all.accept_local=1 2>/dev/null || true
        sysctl -w net.ipv4.conf.all.route_localnet=1 2>/dev/null || true
    }
    
    log_info "系统网络参数优化完成"
}

# 创建目录结构
create_directories() {
    log_step "创建目录结构..."
    
    # 创建必要的目录
    mkdir -p /etc/goose-bridge
    mkdir -p /var/lib/goose-bridge
    mkdir -p /var/log
    mkdir -p /usr/local/bin
    
    # 设置权限
    chmod 755 /etc/goose-bridge
    chmod 755 /var/lib/goose-bridge
    chmod 755 /usr/local/bin
    
    log_info "目录结构创建完成"
}

# 安装程序文件
install_program_files() {
    log_step "安装程序文件..."
    
    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local project_root="$(dirname "$script_dir")"
    
    # 复制主程序
    cp "$project_root/src/goose-bridge-dual.py" /usr/local/bin/goose-bridge-dual
    chmod +x /usr/local/bin/goose-bridge-dual
    
    # 复制依赖模块
    cp "$project_root/src/dual_igmp_keepalive.py" /usr/local/bin/
    cp "$project_root/src/dual_path_processor.py" /usr/local/bin/
    
    # 复制配置文件
    cp "$project_root/config/goose-bridge-dual.conf" /etc/goose-bridge/
    
    # 复制systemd服务文件
    cp "$project_root/config/goose-bridge-dual.service" /etc/systemd/system/
    
    log_info "程序文件安装完成"
}

# 创建管理脚本
create_management_script() {
    log_step "创建管理脚本..."
    
    cat > /usr/local/bin/goose-bridge-dual-ctl << 'EOF'
#!/bin/bash
#
# 独立双路径GOOSE桥接服务管理脚本
#

SERVICE_NAME="goose-bridge-dual"
CONFIG_FILE="/etc/goose-bridge/goose-bridge-dual.conf"
LOG_FILE="/var/log/goose-bridge-dual.log"
STATS_FILE="/var/lib/goose-bridge/dual-path-stats.json"

case "$1" in
    start)
        echo "启动独立双路径GOOSE桥接服务..."
        systemctl start $SERVICE_NAME
        ;;
    stop)
        echo "停止独立双路径GOOSE桥接服务..."
        systemctl stop $SERVICE_NAME
        ;;
    restart)
        echo "重启独立双路径GOOSE桥接服务..."
        systemctl restart $SERVICE_NAME
        ;;
    reload)
        echo "重新加载配置..."
        systemctl reload $SERVICE_NAME
        ;;
    status)
        systemctl status $SERVICE_NAME
        ;;
    enable)
        echo "启用开机自启动..."
        systemctl enable $SERVICE_NAME
        ;;
    disable)
        echo "禁用开机自启动..."
        systemctl disable $SERVICE_NAME
        ;;
    logs)
        if [[ "$2" == "-f" ]]; then
            journalctl -u $SERVICE_NAME -f
        else
            journalctl -u $SERVICE_NAME -n 50
        fi
        ;;
    config)
        if [[ -n "$2" ]]; then
            case "$2" in
                edit)
                    ${EDITOR:-nano} $CONFIG_FILE
                    ;;
                show)
                    cat $CONFIG_FILE
                    ;;
                test)
                    echo "测试配置文件语法..."
                    python3 -c "import configparser; c=configparser.ConfigParser(); c.read('$CONFIG_FILE'); print('配置文件语法正确')"
                    ;;
                *)
                    echo "用法: $0 config {edit|show|test}"
                    ;;
            esac
        else
            echo "用法: $0 config {edit|show|test}"
        fi
        ;;
    stats)
        if [[ -f "$STATS_FILE" ]]; then
            if command -v jq &> /dev/null; then
                jq . "$STATS_FILE"
            else
                cat "$STATS_FILE"
            fi
        else
            echo "统计文件不存在: $STATS_FILE"
        fi
        ;;
    interfaces)
        echo "TAP接口状态:"
        ip link show goose0 2>/dev/null || echo "goose0: 不存在"
        ip link show goose1 2>/dev/null || echo "goose1: 不存在"
        ;;
    multicast)
        echo "多播组成员状态:"
        cat /proc/net/igmp | grep -E "(224\.0\.1\.100|224\.0\.1\.101)" || echo "未找到多播组成员"
        ;;
    test)
        echo "执行服务测试..."
        echo "1. 检查TAP接口..."
        ip link show goose0 && echo "goose0: OK" || echo "goose0: FAIL"
        ip link show goose1 && echo "goose1: OK" || echo "goose1: FAIL"
        
        echo "2. 检查多播组..."
        cat /proc/net/igmp | grep -E "(224\.0\.1\.100|224\.0\.1\.101)" && echo "多播组: OK" || echo "多播组: FAIL"
        
        echo "3. 检查服务状态..."
        systemctl is-active $SERVICE_NAME && echo "服务: OK" || echo "服务: FAIL"
        ;;
    *)
        echo "独立双路径GOOSE桥接服务管理工具"
        echo ""
        echo "用法: $0 {start|stop|restart|reload|status|enable|disable|logs|config|stats|interfaces|multicast|test}"
        echo ""
        echo "命令说明:"
        echo "  start      - 启动服务"
        echo "  stop       - 停止服务"
        echo "  restart    - 重启服务"
        echo "  reload     - 重新加载配置"
        echo "  status     - 查看服务状态"
        echo "  enable     - 启用开机自启动"
        echo "  disable    - 禁用开机自启动"
        echo "  logs [-f]  - 查看日志 (-f 实时跟踪)"
        echo "  config     - 配置管理 {edit|show|test}"
        echo "  stats      - 查看统计信息"
        echo "  interfaces - 查看TAP接口状态"
        echo "  multicast  - 查看多播组状态"
        echo "  test       - 执行服务测试"
        echo ""
        echo "libiec61850使用示例:"
        echo "  发送端: sudo ./goose_publisher_example goose0 & sudo ./goose_publisher_example goose1 &"
        echo "  接收端: sudo ./goose_subscriber_example goose0 & sudo ./goose_subscriber_example goose1 &"
        exit 1
        ;;
esac
EOF
    
    chmod +x /usr/local/bin/goose-bridge-dual-ctl
    
    log_info "管理脚本创建完成"
}

# 配置systemd服务
configure_systemd_service() {
    log_step "配置systemd服务..."
    
    # 重新加载systemd配置
    systemctl daemon-reload
    
    # 不自动启动服务，让用户手动启动
    log_info "systemd服务配置完成"
    log_info "使用以下命令管理服务:"
    log_info "  启动服务: sudo systemctl start goose-bridge-dual"
    log_info "  开机自启: sudo systemctl enable goose-bridge-dual"
    log_info "  查看状态: sudo systemctl status goose-bridge-dual"
}

# 创建测试脚本
create_test_scripts() {
    log_step "创建测试脚本..."
    
    # 创建基础测试脚本
    cat > /usr/local/bin/test-dual-path-basic << 'EOF'
#!/bin/bash
#
# 独立双路径GOOSE桥接服务基础测试
#

echo "=== 独立双路径GOOSE桥接服务基础测试 ==="

echo "1. 检查服务状态..."
systemctl is-active goose-bridge-dual && echo "✅ 服务运行正常" || echo "❌ 服务未运行"

echo "2. 检查TAP接口..."
ip link show goose0 &>/dev/null && echo "✅ goose0接口存在" || echo "❌ goose0接口不存在"
ip link show goose1 &>/dev/null && echo "✅ goose1接口存在" || echo "❌ goose1接口不存在"

echo "3. 检查多播组成员..."
if cat /proc/net/igmp | grep -q "224.0.1.100"; then
    echo "✅ 主多播组(224.0.1.100)已加入"
else
    echo "❌ 主多播组(224.0.1.100)未加入"
fi

if cat /proc/net/igmp | grep -q "224.0.1.101"; then
    echo "✅ 备多播组(224.0.1.101)已加入"
else
    echo "❌ 备多播组(224.0.1.101)未加入"
fi

echo "4. 检查端口监听..."
ss -ulnp | grep ":61850" && echo "✅ 端口61850正在监听" || echo "❌ 端口61850未监听"

echo "5. 检查统计文件..."
if [[ -f "/var/lib/goose-bridge/dual-path-stats.json" ]]; then
    echo "✅ 统计文件存在"
    if command -v jq &>/dev/null; then
        echo "最近统计信息:"
        jq '.statistics' /var/lib/goose-bridge/dual-path-stats.json 2>/dev/null || echo "统计文件格式错误"
    fi
else
    echo "❌ 统计文件不存在"
fi

echo "=== 测试完成 ==="
EOF
    
    chmod +x /usr/local/bin/test-dual-path-basic
    
    log_info "测试脚本创建完成"
}

# 显示安装完成信息
show_completion_info() {
    log_step "安装完成!"
    
    echo ""
    log_info "🎉 独立双路径GOOSE桥接服务安装成功!"
    echo ""
    log_info "📁 重要文件位置:"
    log_info "   主程序: /usr/local/bin/goose-bridge-dual"
    log_info "   配置文件: /etc/goose-bridge/goose-bridge-dual.conf"
    log_info "   日志文件: /var/log/goose-bridge-dual.log"
    log_info "   统计文件: /var/lib/goose-bridge/dual-path-stats.json"
    log_info "   管理脚本: /usr/local/bin/goose-bridge-dual-ctl"
    echo ""
    log_info "🚀 启动服务:"
    log_info "   sudo systemctl start goose-bridge-dual"
    log_info "   sudo systemctl enable goose-bridge-dual  # 开机自启"
    echo ""
    log_info "🔧 管理命令:"
    log_info "   goose-bridge-dual-ctl status    # 查看状态"
    log_info "   goose-bridge-dual-ctl logs -f   # 查看实时日志"
    log_info "   goose-bridge-dual-ctl stats     # 查看统计信息"
    log_info "   goose-bridge-dual-ctl test      # 执行测试"
    echo ""
    log_info "🧪 libiec61850使用方法:"
    log_info "   发送端: sudo ./goose_publisher_example goose0 & sudo ./goose_publisher_example goose1 &"
    log_info "   接收端: sudo ./goose_subscriber_example goose0 & sudo ./goose_subscriber_example goose1 &"
    echo ""
    log_info "📊 基础测试:"
    log_info "   test-dual-path-basic"
    echo ""
    log_warn "⚠️  注意事项:"
    log_warn "   1. 服务需要root权限运行"
    log_warn "   2. 确保AWS TGW多播域配置正确"
    log_warn "   3. 检查安全组允许UDP 61850端口和IGMP协议"
    log_warn "   4. 两个路径完全独立，无故障切换逻辑"
    echo ""
}

# 主安装流程
main() {
    echo "========================================"
    echo "独立双路径GOOSE桥接服务安装程序"
    echo "版本: 1.0.0"
    echo "========================================"
    echo ""
    
    check_root
    check_system_requirements
    install_system_dependencies
    optimize_system_network
    create_directories
    install_program_files
    create_management_script
    configure_systemd_service
    create_test_scripts
    show_completion_info
}

# 执行主安装流程
main "$@"
