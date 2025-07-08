#!/usr/bin/env python3
"""
独立双路径GOOSE协议云端桥接服务
实现goose0/goose1双TAP接口独立运行，支持libiec61850双路径容错

特性：
- 双TAP接口独立管理 (goose0 + goose1)
- 双多播组独立处理 (224.0.1.100 + 224.0.1.101)
- 完整数据传输，无去重处理
- 双IGMP保活机制
- 零侵入libiec61850兼容
"""

import os
import sys
import json
import struct
import socket
import select
import threading
import time
import signal
import fcntl
import subprocess
import logging
import logging.handlers
import argparse
import configparser
from datetime import datetime, timedelta
from pathlib import Path
import queue
import traceback

# TUN接口相关常量
TUNSETIFF = 0x400454ca
IFF_TUN = 0x0001
IFF_TAP = 0x0002
IFF_NO_PI = 0x1000

# 协议常量
GOOSE_ETHERTYPE = 0x88B8
VLAN_ETHERTYPE = 0x8100
GOOSE_MULTICAST_MAC = bytes.fromhex('01:0C:CD:01:00:01'.replace(':', ''))

class DualTAPManager:
    """双TAP接口管理器"""
    
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        
        # TAP接口配置
        self.primary_interface = config.get('primary_interface', 'goose0')
        self.backup_interface = config.get('backup_interface', 'goose1')
        self.primary_ip = config.get('primary_tun_ip', '192.168.100.1/24')
        self.backup_ip = config.get('backup_tun_ip', '192.168.101.1/24')
        
        # TAP接口文件描述符
        self.primary_fd = None
        self.backup_fd = None
        
        # 本机IP（用于生成唯一IP）
        self.local_ip = self.get_local_ip()
        
    def get_local_ip(self):
        """获取本机IP地址"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception as e:
            self.logger.error(f"获取本机IP失败: {e}")
            return "10.0.1.100"  # 默认值
    
    def generate_unique_ip(self, base_network, interface_name):
        """根据本机IP生成唯一的TAP接口IP"""
        try:
            ip_parts = self.local_ip.split('.')
            if len(ip_parts) == 4:
                last_octet = int(ip_parts[3])
                if interface_name == self.primary_interface:
                    return f"192.168.100.{last_octet}/24"
                else:
                    return f"192.168.101.{last_octet}/24"
        except Exception as e:
            self.logger.error(f"生成唯一IP失败: {e}")
        
        # 默认值
        if interface_name == self.primary_interface:
            return "192.168.100.1/24"
        else:
            return "192.168.101.1/24"
    
    def create_dual_taps(self):
        """创建双TAP接口"""
        try:
            # 生成唯一IP地址
            self.primary_ip = self.generate_unique_ip("192.168.100", self.primary_interface)
            self.backup_ip = self.generate_unique_ip("192.168.101", self.backup_interface)
            
            # 创建主TAP接口
            self.primary_fd = self.create_tap_interface(self.primary_interface, self.primary_ip)
            if not self.primary_fd:
                return False
                
            # 创建备TAP接口
            self.backup_fd = self.create_tap_interface(self.backup_interface, self.backup_ip)
            if not self.backup_fd:
                return False
            
            self.logger.info(f"✅ 双TAP接口创建成功:")
            self.logger.info(f"   {self.primary_interface}: {self.primary_ip}")
            self.logger.info(f"   {self.backup_interface}: {self.backup_ip}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"创建双TAP接口失败: {e}")
            return False
    
    def create_tap_interface(self, interface_name, ip_addr):
        """创建单个TAP接口"""
        try:
            # 创建TAP设备
            tun_fd = os.open('/dev/net/tun', os.O_RDWR | os.O_NONBLOCK)
            ifr = struct.pack('16sH', interface_name.encode('utf-8'), IFF_TAP | IFF_NO_PI)
            fcntl.ioctl(tun_fd, TUNSETIFF, ifr)
            
            self.logger.info(f"TAP接口 {interface_name} 创建成功")
            
            # 配置接口
            self.configure_tap_interface(interface_name, ip_addr)
            
            return tun_fd
            
        except Exception as e:
            self.logger.error(f"创建TAP接口 {interface_name} 失败: {e}")
            return None
    
    def configure_tap_interface(self, interface_name, ip_addr):
        """配置TAP接口"""
        try:
            commands = [
                f"ip addr add {ip_addr} dev {interface_name}",
                f"ip link set {interface_name} up",
                f"ip link set {interface_name} multicast on",
                f"ip link set {interface_name} promisc on",
                f"ip link set {interface_name} mtu 1500",
                f"ip link set {interface_name} txqueuelen 1000"
            ]
            
            for cmd in commands:
                result = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=10)
                if result.returncode != 0:
                    self.logger.warning(f"命令执行警告: {cmd} - {result.stderr}")
                else:
                    self.logger.debug(f"执行成功: {cmd}")
            
            self.logger.info(f"TAP接口 {interface_name} 配置完成")
            
        except Exception as e:
            self.logger.error(f"配置TAP接口 {interface_name} 失败: {e}")
            raise
    
    def cleanup(self):
        """清理TAP接口"""
        try:
            # 关闭文件描述符
            if self.primary_fd:
                os.close(self.primary_fd)
                self.logger.info(f"TAP接口 {self.primary_interface} 已关闭")
                
            if self.backup_fd:
                os.close(self.backup_fd)
                self.logger.info(f"TAP接口 {self.backup_interface} 已关闭")
            
            # 删除TAP接口
            for interface in [self.primary_interface, self.backup_interface]:
                try:
                    subprocess.run(f"ip link delete {interface}".split(), 
                                 capture_output=True, text=True, timeout=10)
                    self.logger.info(f"TAP接口 {interface} 已删除")
                except Exception as e:
                    self.logger.warning(f"删除TAP接口 {interface} 失败: {e}")
                    
        except Exception as e:
            self.logger.error(f"清理TAP接口失败: {e}")

class DualMulticastManager:
    """双多播组管理器"""
    
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        
        # 多播配置
        self.primary_multicast_ip = config.get('primary_multicast_ip', '224.0.1.100')
        self.backup_multicast_ip = config.get('backup_multicast_ip', '224.0.1.101')
        self.multicast_port = config.getint('multicast_port', 61850)
        
        # 多播套接字
        self.primary_sock = None
        self.backup_sock = None
        
        # 本机IP
        self.local_ip = self.get_local_ip()
        
    def get_local_ip(self):
        """获取本机IP地址"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception as e:
            self.logger.error(f"获取本机IP失败: {e}")
            return "unknown"
    
    def create_dual_multicast_sockets(self):
        """创建双多播套接字"""
        try:
            # 创建主多播套接字
            self.primary_sock = self.create_multicast_socket(
                self.primary_multicast_ip, self.multicast_port, "primary"
            )
            if not self.primary_sock:
                return False
                
            # 创建备多播套接字
            self.backup_sock = self.create_multicast_socket(
                self.backup_multicast_ip, self.multicast_port, "backup"
            )
            if not self.backup_sock:
                return False
            
            self.logger.info(f"✅ 双多播套接字创建成功:")
            self.logger.info(f"   主多播组: {self.primary_multicast_ip}:{self.multicast_port}")
            self.logger.info(f"   备多播组: {self.backup_multicast_ip}:{self.multicast_port}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"创建双多播套接字失败: {e}")
            return False
    
    def create_multicast_socket(self, multicast_ip, port, name):
        """创建单个多播套接字"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            
            # 优化套接字选项
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024*1024)  # 1MB接收缓冲区
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024*1024)  # 1MB发送缓冲区
            
            sock.bind(('', port))
            
            # 加入多播组
            mreq = struct.pack('4sl', socket.inet_aton(multicast_ip), socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 10)
            
            # 设置非阻塞
            sock.setblocking(False)
            
            self.logger.info(f"{name}多播套接字创建成功: {multicast_ip}:{port}")
            return sock
            
        except Exception as e:
            self.logger.error(f"创建{name}多播套接字失败: {e}")
            return None
    
    def cleanup(self):
        """清理多播套接字"""
        try:
            if self.primary_sock:
                try:
                    mreq = struct.pack('4sl', socket.inet_aton(self.primary_multicast_ip), socket.INADDR_ANY)
                    self.primary_sock.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
                    self.primary_sock.close()
                    self.logger.info("主多播套接字已关闭")
                except Exception as e:
                    self.logger.warning(f"关闭主多播套接字失败: {e}")
            
            if self.backup_sock:
                try:
                    mreq = struct.pack('4sl', socket.inet_aton(self.backup_multicast_ip), socket.INADDR_ANY)
                    self.backup_sock.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
                    self.backup_sock.close()
                    self.logger.info("备多播套接字已关闭")
                except Exception as e:
                    self.logger.warning(f"关闭备多播套接字失败: {e}")
                    
        except Exception as e:
            self.logger.error(f"清理多播套接字失败: {e}")

# 导入其他组件
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from dual_igmp_keepalive import DualIGMPKeepaliveManager
from dual_path_processor import DualPathProcessor

class IndependentDualPathBridge:
    """独立双路径GOOSE桥接服务"""
    
    def __init__(self, config_file=None):
        # 加载配置
        self.config = self.load_config(config_file)
        self.config_file = config_file
        
        # 设置日志
        self.setup_logging()
        
        # 运行状态
        self.running = False
        
        # 组件管理器
        self.tap_manager = DualTAPManager(self.config, self.logger)
        self.multicast_manager = DualMulticastManager(self.config, self.logger)
        self.processor = None
        self.igmp_keepalive = None
        
        # 统计信息
        self.stats = {
            'start_time': time.time(),
            'uptime': 0,
            'primary_path': {},
            'backup_path': {},
            'igmp_stats': {}
        }
        
        # 监控线程
        self.monitor_thread = None
        
        # 设置信号处理
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGHUP, self.reload_config_handler)
        
        self.logger.info("独立双路径GOOSE桥接服务初始化完成")
    
    def load_config(self, config_file):
        """加载配置文件"""
        config = configparser.ConfigParser()
        
        # 默认配置
        defaults = {
            'debug': 'false',
            'log_level': 'INFO',
            'log_file': '/var/log/goose-bridge-dual.log',
            'pid_file': '/var/run/goose-bridge-dual.pid',
            'primary_interface': 'goose0',
            'backup_interface': 'goose1',
            'primary_tun_ip': '192.168.100.1/24',
            'backup_tun_ip': '192.168.101.1/24',
            'primary_multicast_ip': '224.0.1.100',
            'backup_multicast_ip': '224.0.1.101',
            'multicast_port': '61850',
            'dual_path_mode': 'independent',
            'enable_dual_path': 'true',
            'buffer_size': '2048',
            'batch_size': '10',
            'worker_threads': '4',
            'max_errors': '100',
            'error_reset_interval': '300',
            'reconnect_delay': '5',
            'health_check_interval': '30',
            'enable_igmp_keepalive': 'true',
            'igmp_keepalive_interval': '90',
            'igmp_monitor_interval': '120',
            'igmp_reregister_threshold': '2',
            'enable_tgw_monitoring': 'true',
            'primary_tgw_multicast_domain_id': 'tgw-mcast-domain-01d79015018690cef',
            'backup_tgw_multicast_domain_id': 'tgw-mcast-domain-01d79015018690cef',
            'enable_stats_export': 'true',
            'stats_file': '/var/lib/goose-bridge/dual-path-stats.json',
            'stats_export_interval': '60'
        }
        
        # 设置默认值
        config.read_dict({'DEFAULT': defaults})
        
        # 读取配置文件
        if config_file and os.path.exists(config_file):
            config.read(config_file)
        
        return config['DEFAULT']
    
    def setup_logging(self):
        """设置日志系统"""
        self.logger = logging.getLogger('goose-bridge-dual')
        self.logger.setLevel(getattr(logging, self.config.get('log_level', 'INFO')))
        
        # 清除现有处理器
        self.logger.handlers.clear()
        
        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
        
        # 文件处理器（轮转日志）
        log_file = self.config.get('log_file', '/var/log/goose-bridge-dual.log')
        try:
            # 确保日志目录存在
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            
            file_handler = logging.handlers.RotatingFileHandler(
                log_file, maxBytes=10*1024*1024, backupCount=5
            )
            file_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
            )
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)
        except Exception as e:
            self.logger.warning(f"无法设置文件日志: {e}")
    
    def signal_handler(self, signum, frame):
        """信号处理器"""
        self.logger.info(f"收到信号 {signum}，正在优雅停止服务...")
        self.running = False
    
    def reload_config_handler(self, signum, frame):
        """重新加载配置"""
        self.logger.info("收到SIGHUP信号，重新加载配置...")
        try:
            old_config = dict(self.config)
            self.config = self.load_config(self.config_file)
            
            # 比较配置变化
            changed_keys = []
            for key in self.config:
                if key not in old_config or old_config[key] != self.config[key]:
                    changed_keys.append(key)
            
            if changed_keys:
                self.logger.info(f"配置已更新: {changed_keys}")
                # 重新设置日志（如果日志配置改变）
                if any(key.startswith('log_') for key in changed_keys):
                    self.setup_logging()
            else:
                self.logger.info("配置无变化")
                
        except Exception as e:
            self.logger.error(f"重新加载配置失败: {e}")
    
    def create_pid_file(self):
        """创建PID文件"""
        try:
            pid_file = self.config.get('pid_file', '/var/run/goose-bridge-dual.pid')
            os.makedirs(os.path.dirname(pid_file), exist_ok=True)
            
            with open(pid_file, 'w') as f:
                f.write(str(os.getpid()))
            
            self.logger.info(f"PID文件已创建: {pid_file}")
            return pid_file
            
        except Exception as e:
            self.logger.warning(f"创建PID文件失败: {e}")
            return None
    
    def remove_pid_file(self):
        """删除PID文件"""
        try:
            pid_file = self.config.get('pid_file', '/var/run/goose-bridge-dual.pid')
            if os.path.exists(pid_file):
                os.remove(pid_file)
                self.logger.info("PID文件已删除")
        except Exception as e:
            self.logger.warning(f"删除PID文件失败: {e}")
    
    def start_monitoring_thread(self):
        """启动监控线程"""
        self.monitor_thread = threading.Thread(
            target=self.monitor_worker,
            name="Dual-Path-Monitor",
            daemon=True
        )
        self.monitor_thread.start()
        self.logger.info("监控线程已启动")
    
    def monitor_worker(self):
        """监控工作线程"""
        self.logger.info("🔍 双路径监控线程启动")
        
        last_stats_time = time.time()
        stats_interval = self.config.getint('stats_export_interval', 60)
        
        while self.running:
            try:
                time.sleep(10)  # 每10秒检查一次
                
                # 更新运行时间
                self.stats['uptime'] = time.time() - self.stats['start_time']
                
                # 收集统计信息
                if self.processor:
                    processor_stats = self.processor.get_stats()
                    self.stats['primary_path'] = processor_stats.get('primary', {})
                    self.stats['backup_path'] = processor_stats.get('backup', {})
                
                if self.igmp_keepalive:
                    self.stats['igmp_stats'] = self.igmp_keepalive.get_stats()
                
                # 定期导出统计信息
                if time.time() - last_stats_time >= stats_interval:
                    self.export_stats()
                    self.print_stats()
                    last_stats_time = time.time()
                
            except Exception as e:
                self.logger.error(f"监控线程错误: {e}")
                time.sleep(5)
        
        self.logger.info("双路径监控线程结束")
    
    def export_stats(self):
        """导出统计信息到文件"""
        try:
            stats_file = self.config.get('stats_file', '/var/lib/goose-bridge/dual-path-stats.json')
            
            # 确保目录存在
            os.makedirs(os.path.dirname(stats_file), exist_ok=True)
            
            # 准备统计数据
            export_data = {
                'timestamp': datetime.now().isoformat(),
                'service_info': {
                    'primary_interface': self.config.get('primary_interface'),
                    'backup_interface': self.config.get('backup_interface'),
                    'primary_multicast': f"{self.config.get('primary_multicast_ip')}:{self.config.get('multicast_port')}",
                    'backup_multicast': f"{self.config.get('backup_multicast_ip')}:{self.config.get('multicast_port')}",
                    'dual_path_mode': self.config.get('dual_path_mode')
                },
                'statistics': dict(self.stats),
                'health': {
                    'running': self.running,
                    'primary_active': bool(self.tap_manager.primary_fd),
                    'backup_active': bool(self.tap_manager.backup_fd)
                }
            }
            
            # 写入文件
            with open(stats_file, 'w') as f:
                json.dump(export_data, f, indent=2, default=str)
                
        except Exception as e:
            self.logger.warning(f"导出统计信息失败: {e}")
    
    def print_stats(self):
        """打印统计信息"""
        uptime_str = str(timedelta(seconds=int(self.stats['uptime'])))
        
        print(f"\n📊 独立双路径GOOSE桥接服务统计:")
        print(f"   服务运行时间: {uptime_str}")
        print(f"   双路径模式: {self.config.get('dual_path_mode')}")
        
        # 主路径统计
        primary_stats = self.stats.get('primary_path', {})
        print(f"\n🔵 主路径统计 ({self.config.get('primary_interface')} ↔ {self.config.get('primary_multicast_ip')}):")
        print(f"   GOOSE接收: {primary_stats.get('goose_received', 0)}")
        print(f"   VLAN GOOSE接收: {primary_stats.get('vlan_goose_received', 0)}")
        print(f"   GOOSE→IP转换: {primary_stats.get('goose_to_ip', 0)}")
        print(f"   IP→GOOSE转换: {primary_stats.get('ip_to_goose', 0)}")
        print(f"   错误次数: {primary_stats.get('errors', 0)}")
        
        # 备路径统计
        backup_stats = self.stats.get('backup_path', {})
        print(f"\n🟡 备路径统计 ({self.config.get('backup_interface')} ↔ {self.config.get('backup_multicast_ip')}):")
        print(f"   GOOSE接收: {backup_stats.get('goose_received', 0)}")
        print(f"   VLAN GOOSE接收: {backup_stats.get('vlan_goose_received', 0)}")
        print(f"   GOOSE→IP转换: {backup_stats.get('goose_to_ip', 0)}")
        print(f"   IP→GOOSE转换: {backup_stats.get('ip_to_goose', 0)}")
        print(f"   错误次数: {backup_stats.get('errors', 0)}")
        
        # IGMP保活统计
        igmp_stats = self.stats.get('igmp_stats', {})
        if igmp_stats:
            print(f"\n🔄 IGMP保活统计:")
            primary_igmp = igmp_stats.get('primary', {})
            backup_igmp = igmp_stats.get('backup', {})
            print(f"   主路径保活: {primary_igmp.get('keepalive_count', 0)}次")
            print(f"   备路径保活: {backup_igmp.get('keepalive_count', 0)}次")
            print(f"   主路径重注册: {primary_igmp.get('reregister_count', 0)}次")
            print(f"   备路径重注册: {backup_igmp.get('reregister_count', 0)}次")
    
    def start(self):
        """启动独立双路径桥接服务"""
        self.logger.info("🚀 启动独立双路径GOOSE桥接服务")
        
        # 检查权限
        if os.geteuid() != 0:
            self.logger.error("需要root权限来创建TAP接口")
            return False
        
        # 创建PID文件
        pid_file = self.create_pid_file()
        
        try:
            # 1. 创建双TAP接口
            if not self.tap_manager.create_dual_taps():
                self.logger.error("创建双TAP接口失败")
                return False
            
            # 2. 创建双多播套接字
            if not self.multicast_manager.create_dual_multicast_sockets():
                self.logger.error("创建双多播套接字失败")
                return False
            
            # 3. 创建双路径数据处理器
            self.processor = DualPathProcessor(
                self.tap_manager,
                self.multicast_manager,
                self.config,
                self.logger
            )
            
            if not self.processor.start():
                self.logger.error("启动双路径数据处理器失败")
                return False
            
            # 4. 启动双IGMP保活管理器
            if self.config.getboolean('enable_igmp_keepalive', True):
                self.igmp_keepalive = DualIGMPKeepaliveManager(self.config, self.logger)
                if self.igmp_keepalive.start():
                    self.logger.info("🔄 双IGMP保活管理器已启动")
                else:
                    self.logger.warning("⚠️  双IGMP保活管理器启动失败")
            
            # 5. 启动监控线程
            self.start_monitoring_thread()
            
            self.running = True
            
            self.logger.info("✅ 独立双路径GOOSE桥接服务启动成功")
            self.logger.info(f"   主路径: {self.config.get('primary_interface')} ↔ {self.config.get('primary_multicast_ip')}:{self.config.get('multicast_port')}")
            self.logger.info(f"   备路径: {self.config.get('backup_interface')} ↔ {self.config.get('backup_multicast_ip')}:{self.config.get('multicast_port')}")
            self.logger.info(f"   libiec61850使用方法:")
            self.logger.info(f"     发送端: sudo ./goose_publisher_example {self.config.get('primary_interface')} & sudo ./goose_publisher_example {self.config.get('backup_interface')} &")
            self.logger.info(f"     接收端: sudo ./goose_subscriber_example {self.config.get('primary_interface')} & sudo ./goose_subscriber_example {self.config.get('backup_interface')} &")
            
            # 主循环
            try:
                while self.running:
                    time.sleep(1)
            
            except KeyboardInterrupt:
                self.logger.info("收到中断信号")
            
            finally:
                self.stop()
                if pid_file:
                    self.remove_pid_file()
            
            return True
            
        except Exception as e:
            self.logger.error(f"服务启动失败: {e}")
            if pid_file:
                self.remove_pid_file()
            return False
    
    def stop(self):
        """停止独立双路径桥接服务"""
        self.logger.info("正在停止独立双路径GOOSE桥接服务...")
        
        self.running = False
        
        # 停止双路径数据处理器
        if self.processor:
            self.processor.stop()
        
        # 停止双IGMP保活管理器
        if self.igmp_keepalive:
            self.igmp_keepalive.stop()
        
        # 清理双多播套接字
        self.multicast_manager.cleanup()
        
        # 清理双TAP接口
        self.tap_manager.cleanup()
        
        # 导出最终统计信息
        if self.config.getboolean('enable_stats_export', True):
            self.export_stats()
        
        self.print_stats()
        self.logger.info("✅ 独立双路径GOOSE桥接服务已停止")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='独立双路径GOOSE协议云端桥接服务')
    parser.add_argument('-c', '--config', help='配置文件路径', 
                       default='/home/ec2-user/efs/goose/goose-bridge-on-ec2/config/goose-bridge-dual.conf')
    parser.add_argument('--debug', action='store_true', help='启用调试模式')
    
    args = parser.parse_args()
    
    # 创建桥接服务
    bridge = IndependentDualPathBridge(config_file=args.config)
    
    # 覆盖命令行参数
    if args.debug:
        bridge.config['debug'] = 'true'
        bridge.logger.setLevel(logging.DEBUG)
    
    # 启动服务
    success = bridge.start()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    sys.exit(main())
