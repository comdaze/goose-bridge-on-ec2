#!/usr/bin/env python3
"""
生产级GOOSE协议云端桥接服务
优化性能、容错性和可靠性，支持作为Linux系统服务运行

特性：
- 高性能异步I/O处理
- 完整的错误恢复机制
- 详细的日志记录
- 健康检查和监控
- 优雅的服务启停
- 配置文件支持
- 统计信息导出
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
class IGMPKeepaliveManager:
    """优化IGMP保活管理器 - 单端口设计，纯IGMP操作"""
    
    def __init__(self, multicast_ip, multicast_port, tgw_domain_id, logger, config):
        self.multicast_ip = multicast_ip
        self.multicast_port = multicast_port
        self.tgw_domain_id = tgw_domain_id
        self.logger = logger
        self.config = config
        
        # 配置参数
        self.keepalive_interval = config.getint('igmp_keepalive_interval', 90)
        self.monitor_interval = config.getint('igmp_monitor_interval', 120)
        self.reregister_threshold = config.getint('igmp_reregister_threshold', 2)
        self.enable_tgw_monitoring = config.getboolean('enable_tgw_monitoring', True)
        
        # 运行状态
        self.running = False
        self.keepalive_sock = None
        self.keepalive_thread = None
        self.monitor_thread = None
        
        # 统计信息
        self.stats = {
            'keepalive_count': 0,
            'reregister_count': 0,
            'monitor_checks': 0,
            'tgw_missing_count': 0,
            'local_missing_count': 0,
            'last_keepalive': None,
            'last_monitor_check': None
        }
        
        # 状态跟踪
        self.consecutive_missing = 0
        self.last_tgw_check_success = True
        
    def start(self):
        """启动IGMP保活管理"""
        if self.running:
            return True
        
        try:
            # 创建保活套接字
            self.keepalive_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.keepalive_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # 优化：不绑定端口，只进行纯IGMP操作
            
            # 加入多播组
            mreq = struct.pack('4sl', socket.inet_aton(self.multicast_ip), socket.INADDR_ANY)
            self.keepalive_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            
            self.running = True
            
            # 启动保活线程
            self.keepalive_thread = threading.Thread(target=self._keepalive_worker, 
                                                   name="IGMP-Keepalive", daemon=True)
            self.keepalive_thread.start()
            
            # 启动监控线程
            if self.enable_tgw_monitoring:
                self.monitor_thread = threading.Thread(target=self._monitor_worker, 
                                                     name="IGMP-Monitor", daemon=True)
                self.monitor_thread.start()
            
            self.logger.info(f"🔄 优化IGMP保活管理器启动成功 (单端口设计)")
            self.logger.info(f"   多播地址: {self.multicast_ip} (纯IGMP注册，无端口占用)")
            self.logger.info(f"   保活间隔: {self.keepalive_interval}秒")
            self.logger.info(f"   监控间隔: {self.monitor_interval}秒")
            self.logger.info(f"   TGW监控: {'启用' if self.enable_tgw_monitoring else '禁用'}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"启动IGMP保活管理器失败: {e}")
            return False
    
    def stop(self):
        """停止IGMP保活管理"""
        self.logger.info("正在停止IGMP保活管理器...")
        self.running = False
        
        # 关闭套接字
        if self.keepalive_sock:
            try:
                mreq = struct.pack('4sl', socket.inet_aton(self.multicast_ip), socket.INADDR_ANY)
                self.keepalive_sock.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
                self.keepalive_sock.close()
            except Exception as e:
                self.logger.warning(f"关闭保活套接字失败: {e}")
        
        # 等待线程结束
        if self.keepalive_thread and self.keepalive_thread.is_alive():
            self.keepalive_thread.join(timeout=5)
        
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=5)
        
        self.logger.info("IGMP保活管理器已停止")
    
    def _keepalive_worker(self):
        """IGMP保活工作线程"""
        self.logger.info("🔄 IGMP保活线程启动")
        
        while self.running:
            try:
                # 执行保活操作
                self._perform_keepalive()
                
                # 等待下次保活
                for _ in range(self.keepalive_interval):
                    if not self.running:
                        break
                    time.sleep(1)
                
            except Exception as e:
                self.logger.error(f"IGMP保活线程错误: {e}")
                time.sleep(5)
        
        self.logger.info("IGMP保活线程结束")
    
    def _monitor_worker(self):
        """IGMP监控工作线程"""
        self.logger.info("🔍 IGMP监控线程启动")
        
        while self.running:
            try:
                # 执行监控检查
                self._perform_monitoring()
                
                # 等待下次监控
                for _ in range(self.monitor_interval):
                    if not self.running:
                        break
                    time.sleep(1)
                
            except Exception as e:
                self.logger.error(f"IGMP监控线程错误: {e}")
                time.sleep(10)
        
        self.logger.info("IGMP监控线程结束")
    
    def _perform_keepalive(self):
        """执行IGMP保活操作"""
        try:
            # 重新加入多播组以刷新IGMP注册
            mreq = struct.pack('4sl', socket.inet_aton(self.multicast_ip), socket.INADDR_ANY)
            
            # 先离开再加入 (刷新IGMP注册)
            self.keepalive_sock.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
            time.sleep(0.1)
            self.keepalive_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            
            self.stats['keepalive_count'] += 1
            self.stats['last_keepalive'] = datetime.now()
            
            self.logger.debug(f"IGMP保活完成: {self.multicast_ip} (第{self.stats['keepalive_count']}次)")
            
        except Exception as e:
            self.logger.warning(f"IGMP保活失败: {e}")
    
    def _perform_monitoring(self):
        """执行IGMP监控检查"""
        try:
            self.stats['monitor_checks'] += 1
            self.stats['last_monitor_check'] = datetime.now()
            
            # 检查本地IGMP状态
            local_registered = self._check_local_igmp_registration()
            
            # 检查TGW多播域状态
            tgw_registered = self._check_tgw_multicast_registration()
            
            # 分析状态并采取行动
            self._analyze_and_act(local_registered, tgw_registered)
            
        except Exception as e:
            self.logger.error(f"IGMP监控检查失败: {e}")
    
    def _check_local_igmp_registration(self):
        """检查本地IGMP注册状态"""
        try:
            with open('/proc/net/igmp', 'r') as f:
                content = f.read()
            
            # 查找目标多播地址
            target_hex = '640100E0'  # 224.0.1.100的十六进制
            
            if target_hex in content:
                self.logger.debug(f"本地IGMP注册正常: {self.multicast_ip}")
                return True
            else:
                self.logger.warning(f"⚠️  本地IGMP注册缺失: {self.multicast_ip}")
                self.stats['local_missing_count'] += 1
                return False
                
        except Exception as e:
            self.logger.error(f"检查本地IGMP注册失败: {e}")
            return False
    
    def _check_tgw_multicast_registration(self):
        """检查TGW多播域注册状态"""
        try:
            result = subprocess.run([
                'aws', 'ec2', 'search-transit-gateway-multicast-groups',
                '--transit-gateway-multicast-domain-id', self.tgw_domain_id,
                '--filters', f'Name=group-ip-address,Values={self.multicast_ip}',
                '--output', 'json'
            ], capture_output=True, text=True, timeout=15)
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                groups = data.get('MulticastGroups', [])
                
                if groups:
                    self.logger.debug(f"TGW多播域注册正常: {self.multicast_ip} ({len(groups)}个)")
                    self.last_tgw_check_success = True
                    return True
                else:
                    self.logger.warning(f"⚠️  TGW多播域注册缺失: {self.multicast_ip}")
                    self.stats['tgw_missing_count'] += 1
                    self.last_tgw_check_success = False
                    return False
            else:
                self.logger.error(f"查询TGW多播域失败: {result.stderr}")
                return self.last_tgw_check_success
                
        except Exception as e:
            self.logger.error(f"检查TGW多播域注册失败: {e}")
            return self.last_tgw_check_success
    
    def _analyze_and_act(self, local_registered, tgw_registered):
        """分析状态并采取相应行动"""
        if not local_registered or not tgw_registered:
            self.consecutive_missing += 1
            
            if self.consecutive_missing >= self.reregister_threshold:
                self.logger.warning(f"🚨 连续{self.consecutive_missing}次检查发现注册缺失，执行重新注册")
                self._force_reregister()
                self.consecutive_missing = 0
        else:
            # 状态正常，重置计数器
            if self.consecutive_missing > 0:
                self.logger.info(f"✅ IGMP注册状态已恢复正常")
                self.consecutive_missing = 0
    
    def _force_reregister(self):
        """强制重新注册IGMP组成员"""
        try:
            self.logger.info(f"🔄 强制重新注册IGMP组成员: {self.multicast_ip}")
            
            # 重新创建套接字
            old_sock = self.keepalive_sock
            
            # 创建新套接字
            new_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            new_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # 优化：不绑定端口，直接进行IGMP操作
            
            # 加入多播组
            mreq = struct.pack('4sl', socket.inet_aton(self.multicast_ip), socket.INADDR_ANY)
            new_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            
            # 替换套接字
            self.keepalive_sock = new_sock
            
            # 关闭旧套接字
            if old_sock:
                try:
                    old_sock.close()
                except:
                    pass
            
            self.stats['reregister_count'] += 1
            self.logger.info(f"✅ IGMP重新注册完成 (第{self.stats['reregister_count']}次)")
            
        except Exception as e:
            self.logger.error(f"强制重新注册失败: {e}")
    
    def get_stats(self):
        """获取统计信息"""
        return dict(self.stats)



class ProductionGOOSEBridge:
    """生产级GOOSE桥接服务"""
    
    def __init__(self, config_file=None):
        # 加载配置
        self.config = self.load_config(config_file)
        
        # 基本属性
        self.tun_name = self.config.get('interface', 'goose0')
        self.multicast_ip = self.config.get('multicast_ip', '224.0.1.100')
        self.multicast_port = self.config.getint('multicast_port', 61850)
        self.debug = self.config.getboolean('debug', False)
        
        # 运行状态
        self.running = False
        self.tun_fd = None
        self.multicast_sock = None
        self.local_ip = self.get_local_ip()
        self.tun_ip = self.generate_tun_ip()
        
        # 性能优化配置
        self.buffer_size = self.config.getint('buffer_size', 2048)
        self.batch_size = self.config.getint('batch_size', 10)
        self.worker_threads = self.config.getint('worker_threads', 2)
        
        # 容错配置
        self.max_errors = self.config.getint('max_errors', 100)
        self.error_reset_interval = self.config.getint('error_reset_interval', 300)
        self.reconnect_delay = self.config.getint('reconnect_delay', 5)
        self.health_check_interval = self.config.getint('health_check_interval', 30)
        
        # 统计信息
        self.stats = {
            'start_time': time.time(),
            'goose_to_ip': 0,
            'ip_to_goose': 0,
            'goose_received': 0,
            'vlan_goose_received': 0,
            'goose_sent': 0,
            'errors': 0,
            'raw_frames': 0,
            'last_error_reset': time.time(),
            'uptime': 0,
            'throughput_goose_per_sec': 0,
            'throughput_multicast_per_sec': 0
        }
        
        # 错误跟踪
        self.error_count = 0
        self.last_error_time = 0
        self.consecutive_errors = 0
        
        # 线程和队列
        self.frame_queue = queue.Queue(maxsize=1000)
        self.multicast_queue = queue.Queue(maxsize=1000)
        self.worker_threads_list = []
        
        # 设置日志
        self.setup_logging()
        
        # IGMP保活管理器
        if self.config.getboolean('enable_igmp_keepalive', True):
            self.igmp_keepalive = IGMPKeepaliveManager(
                multicast_ip=self.multicast_ip,
                multicast_port=self.multicast_port,
                tgw_domain_id=self.config.get('tgw_multicast_domain_id', 'tgw-mcast-domain-01d79015018690cef'),
                logger=self.logger,
                config=self.config
            )
        else:
            self.igmp_keepalive = None
        
        # 设置信号处理
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGHUP, self.reload_config_handler)
        
        self.logger.info("生产级GOOSE桥接服务初始化完成")
        if self.igmp_keepalive:
            self.logger.info("🔄 优化IGMP保活功能已启用 (单端口设计)")
    
    def load_config(self, config_file):
        """加载配置文件"""
        config = configparser.ConfigParser()
        
        # 默认配置
        defaults = {
            'interface': 'goose0',
            'multicast_ip': '224.0.1.100',
            'multicast_port': '61850',
            'debug': 'false',
            'log_level': 'INFO',
            'log_file': '/var/log/goose-bridge.log',
            'pid_file': '/var/run/goose-bridge.pid',
            'buffer_size': '2048',
            'batch_size': '10',
            'worker_threads': '2',
            'max_errors': '100',
            'error_reset_interval': '300',
            'reconnect_delay': '5',
            'health_check_interval': '30',
            'stats_file': '/var/lib/goose-bridge/stats.json',
            'enable_stats_export': 'true',
            # IGMP保活配置
            'enable_igmp_keepalive': 'true',
            'igmp_keepalive_interval': '90',
            'igmp_monitor_interval': '120',
            'igmp_reregister_threshold': '2',
            'enable_tgw_monitoring': 'true',
            'tgw_multicast_domain_id': 'tgw-mcast-domain-01d79015018690cef'
        }
        
        # 设置默认值
        config.read_dict({'DEFAULT': defaults})
        
        # 读取配置文件
        if config_file and os.path.exists(config_file):
            config.read(config_file)
        
        return config['DEFAULT']
    
    def setup_logging(self):
        """设置日志系统"""
        self.logger = logging.getLogger('goose-bridge')
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
        log_file = self.config.get('log_file', '/var/log/goose-bridge.log')
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
    
    def generate_tun_ip(self):
        """根据本机IP生成唯一的TUN接口IP"""
        try:
            ip_parts = self.local_ip.split('.')
            if len(ip_parts) == 4:
                last_octet = int(ip_parts[3])
                return f"192.168.100.{last_octet}/24"
        except Exception as e:
            self.logger.error(f"生成TUN IP失败: {e}")
        return "192.168.100.1/24"
    
    def signal_handler(self, signum, frame):
        """信号处理器"""
        self.logger.info(f"收到信号 {signum}，正在优雅停止服务...")
        self.running = False
    
    def reload_config_handler(self, signum, frame):
        """重新加载配置"""
        self.logger.info("收到SIGHUP信号，重新加载配置...")
        try:
            old_config = dict(self.config)
            self.config = self.load_config(getattr(self, 'config_file', None))
            
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
    
    def create_tun_interface(self):
        """创建TAP接口（优化版）"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.tun_fd = os.open('/dev/net/tun', os.O_RDWR | os.O_NONBLOCK)
                ifr = struct.pack('16sH', self.tun_name.encode('utf-8'), IFF_TAP | IFF_NO_PI)
                fcntl.ioctl(self.tun_fd, TUNSETIFF, ifr)
                
                self.logger.info(f"TAP接口 {self.tun_name} 创建成功")
                self.configure_tun_interface()
                return True
                
            except Exception as e:
                self.logger.error(f"创建TAP接口失败 (尝试 {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(self.reconnect_delay)
                else:
                    return False
        
        return False
    
    def configure_tun_interface(self):
        """配置TAP接口（优化版）"""
        try:
            commands = [
                f"ip addr add {self.tun_ip} dev {self.tun_name}",
                f"ip link set {self.tun_name} up",
                f"ip link set {self.tun_name} multicast on",
                f"ip link set {self.tun_name} promisc on",
                f"ip link set {self.tun_name} mtu 1500",
                f"ip link set {self.tun_name} txqueuelen 1000"
            ]
            
            for cmd in commands:
                result = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=10)
                if result.returncode != 0:
                    self.logger.warning(f"命令执行警告: {cmd} - {result.stderr}")
                else:
                    self.logger.debug(f"执行成功: {cmd}")
            
            # 设置接口缓冲区大小
            try:
                with open(f'/sys/class/net/{self.tun_name}/tx_queue_len', 'w') as f:
                    f.write('1000')
            except:
                pass
            
            self.logger.info(f"TAP接口 {self.tun_name} 配置完成")
            
        except Exception as e:
            self.logger.error(f"配置TAP接口失败: {e}")
            raise
    
    def create_multicast_socket(self):
        """创建多播套接字（优化版）"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.multicast_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                
                # 优化套接字选项
                self.multicast_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.multicast_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024*1024)  # 1MB接收缓冲区
                self.multicast_sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024*1024)  # 1MB发送缓冲区
                
                self.multicast_sock.bind(('', self.multicast_port))
                
                # 加入多播组
                mreq = struct.pack('4sl', socket.inet_aton(self.multicast_ip), socket.INADDR_ANY)
                self.multicast_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                self.multicast_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 10)
                
                # 设置非阻塞
                self.multicast_sock.setblocking(False)
                
                self.logger.info(f"多播套接字创建成功: {self.multicast_ip}:{self.multicast_port}")
                return True
                
            except Exception as e:
                self.logger.error(f"创建多播套接字失败 (尝试 {attempt+1}/{max_retries}): {e}")
                if self.multicast_sock:
                    try:
                        self.multicast_sock.close()
                    except:
                        pass
                    self.multicast_sock = None
                
                if attempt < max_retries - 1:
                    time.sleep(self.reconnect_delay)
                else:
                    return False
        
        return False
    
    def parse_ethernet_frame_with_vlan(self, frame_data):
        """解析支持VLAN标签的以太网帧（优化版）"""
        try:
            if len(frame_data) < 14:
                return None
            
            dst_mac = frame_data[0:6]
            src_mac = frame_data[6:12]
            ethertype_or_vlan = struct.unpack('!H', frame_data[12:14])[0]
            
            # 检查是否有VLAN标签
            if ethertype_or_vlan == VLAN_ETHERTYPE:  # 0x8100
                if len(frame_data) < 18:
                    return None
                
                # 解析VLAN标签
                vlan_tci = struct.unpack('!H', frame_data[14:16])[0]
                vlan_id = vlan_tci & 0x0FFF
                vlan_priority = (vlan_tci >> 13) & 0x07
                
                # 真正的EtherType在VLAN标签之后
                ethertype = struct.unpack('!H', frame_data[16:18])[0]
                payload = frame_data[18:]
                
                return {
                    'dst_mac': dst_mac,
                    'src_mac': src_mac,
                    'has_vlan': True,
                    'vlan_id': vlan_id,
                    'vlan_priority': vlan_priority,
                    'ethertype': ethertype,
                    'payload': payload,
                    'raw': frame_data,
                    'header_length': 18
                }
            else:
                # 没有VLAN标签的普通帧
                ethertype = ethertype_or_vlan
                payload = frame_data[14:]
                
                return {
                    'dst_mac': dst_mac,
                    'src_mac': src_mac,
                    'has_vlan': False,
                    'vlan_id': None,
                    'vlan_priority': None,
                    'ethertype': ethertype,
                    'payload': payload,
                    'raw': frame_data,
                    'header_length': 14
                }
        except Exception as e:
            self.logger.debug(f"解析以太网帧失败: {e}")
            return None
    
    def is_goose_frame(self, frame):
        """检查是否为GOOSE帧（优化版）"""
        return (frame and 
                frame['ethertype'] == GOOSE_ETHERTYPE and 
                frame['dst_mac'] == GOOSE_MULTICAST_MAC)
    
    def record_error(self, error_msg, exception=None):
        """记录错误（容错处理）"""
        self.error_count += 1
        self.stats['errors'] += 1
        self.last_error_time = time.time()
        self.consecutive_errors += 1
        
        if exception:
            self.logger.error(f"{error_msg}: {exception}")
            if self.debug:
                self.logger.debug(traceback.format_exc())
        else:
            self.logger.error(error_msg)
        
        # 检查是否需要重置错误计数
        if time.time() - self.stats['last_error_reset'] > self.error_reset_interval:
            self.error_count = 0
            self.consecutive_errors = 0
            self.stats['last_error_reset'] = time.time()
            self.logger.info("错误计数已重置")
        
        # 检查是否达到最大错误数
        if self.error_count > self.max_errors:
            self.logger.critical(f"错误数量超过阈值 ({self.max_errors})，服务将停止")
            self.running = False
    
    def reset_error_count(self):
        """重置错误计数"""
        if self.consecutive_errors > 0:
            self.consecutive_errors = 0
            self.logger.debug("连续错误计数已重置")
    def goose_to_multicast(self, goose_frame):
        """将GOOSE帧转换为IP多播（优化版）"""
        try:
            timestamp = struct.pack('!Q', int(time.time() * 1000000))
            
            # 封装数据：源MAC + 时间戳 + VLAN信息 + GOOSE载荷
            vlan_info = struct.pack('!HH', 
                                   1 if goose_frame['has_vlan'] else 0,
                                   goose_frame['vlan_id'] or 0)
            
            packet_data = (
                goose_frame['src_mac'] +
                timestamp +
                vlan_info +
                goose_frame['payload']
            )
            
            self.multicast_sock.sendto(packet_data, (self.multicast_ip, self.multicast_port))
            self.stats['goose_to_ip'] += 1
            self.reset_error_count()  # 成功操作重置错误计数
            
            if self.debug:
                src_mac_str = ':'.join(f'{b:02x}' for b in goose_frame['src_mac'])
                vlan_str = f"VLAN {goose_frame['vlan_id']}" if goose_frame['has_vlan'] else "无VLAN"
                self.logger.debug(f"GOOSE→IP: {src_mac_str} → {self.multicast_ip}:{self.multicast_port} ({vlan_str})")
            
            return True
            
        except Exception as e:
            self.record_error("GOOSE转多播失败", e)
            return False
    
    def multicast_to_goose(self, packet_data, sender_addr):
        """将IP多播转换为GOOSE帧（优化版）"""
        try:
            if len(packet_data) < 18:
                return False
            
            # 解析封装的数据包
            src_mac = packet_data[0:6]
            timestamp = struct.unpack('!Q', packet_data[6:14])[0]
            vlan_flag, vlan_id = struct.unpack('!HH', packet_data[14:18])
            goose_payload = packet_data[18:]
            
            # 重构以太网帧
            if vlan_flag:
                # 带VLAN标签的帧
                vlan_tci = (4 << 13) | (vlan_id & 0x0FFF)
                ethernet_frame = (
                    GOOSE_MULTICAST_MAC +
                    src_mac +
                    struct.pack('!H', VLAN_ETHERTYPE) +
                    struct.pack('!H', vlan_tci) +
                    struct.pack('!H', GOOSE_ETHERTYPE) +
                    goose_payload
                )
            else:
                # 无VLAN标签的帧
                ethernet_frame = (
                    GOOSE_MULTICAST_MAC +
                    src_mac +
                    struct.pack('!H', GOOSE_ETHERTYPE) +
                    goose_payload
                )
            
            # 写入TUN接口
            os.write(self.tun_fd, ethernet_frame)
            self.stats['ip_to_goose'] += 1
            self.reset_error_count()
            
            if self.debug:
                src_mac_str = ':'.join(f'{b:02x}' for b in src_mac)
                age_ms = (int(time.time() * 1000000) - timestamp) // 1000
                vlan_str = f"VLAN {vlan_id}" if vlan_flag else "无VLAN"
                self.logger.debug(f"IP→GOOSE: {sender_addr[0]} → {src_mac_str} (延迟: {age_ms}ms, {vlan_str})")
            
            return True
            
        except Exception as e:
            self.record_error("多播转GOOSE失败", e)
            return False
    
    def tun_reader_thread(self):
        """TAP接口读取线程（高性能版）"""
        self.logger.info("TAP接口读取线程启动")
        
        consecutive_timeouts = 0
        max_consecutive_timeouts = 100
        
        while self.running:
            try:
                # 使用select进行非阻塞I/O
                ready, _, _ = select.select([self.tun_fd], [], [], 1.0)
                
                if ready:
                    consecutive_timeouts = 0
                    
                    # 批量读取帧以提高性能
                    frames_processed = 0
                    while frames_processed < self.batch_size and self.running:
                        try:
                            frame_data = os.read(self.tun_fd, self.buffer_size)
                            if not frame_data:
                                break
                            
                            self.stats['raw_frames'] += 1
                            
                            # 解析帧
                            frame = self.parse_ethernet_frame_with_vlan(frame_data)
                            
                            if frame and self.is_goose_frame(frame):
                                if frame['has_vlan']:
                                    self.stats['vlan_goose_received'] += 1
                                else:
                                    self.stats['goose_received'] += 1
                                
                                # 转换为IP多播
                                self.goose_to_multicast(frame)
                            
                            frames_processed += 1
                            
                        except BlockingIOError:
                            # 没有更多数据可读
                            break
                        except Exception as e:
                            self.record_error("TAP读取帧处理失败", e)
                            break
                else:
                    consecutive_timeouts += 1
                    if consecutive_timeouts > max_consecutive_timeouts:
                        self.logger.warning("TAP接口长时间无数据，检查接口状态")
                        consecutive_timeouts = 0
                        if not self.health_check_tun_interface():
                            self.logger.error("TAP接口健康检查失败")
                            break
                
            except Exception as e:
                self.record_error("TAP读取线程错误", e)
                if self.consecutive_errors > 10:
                    self.logger.error("TAP读取连续错误过多，线程退出")
                    break
                time.sleep(self.reconnect_delay)
        
        self.logger.info("TAP接口读取线程结束")
    
    def multicast_reader_thread(self):
        """多播接收线程（高性能版）"""
        self.logger.info("多播接收线程启动")
        
        consecutive_timeouts = 0
        max_consecutive_timeouts = 100
        
        while self.running:
            try:
                ready, _, _ = select.select([self.multicast_sock], [], [], 1.0)
                
                if ready:
                    consecutive_timeouts = 0
                    
                    # 批量处理多播数据
                    packets_processed = 0
                    while packets_processed < self.batch_size and self.running:
                        try:
                            packet_data, sender_addr = self.multicast_sock.recvfrom(self.buffer_size)
                            
                            # 过滤本机发送的数据
                            if sender_addr[0] != self.local_ip:
                                self.multicast_to_goose(packet_data, sender_addr)
                            
                            packets_processed += 1
                            
                        except BlockingIOError:
                            # 没有更多数据可读
                            break
                        except Exception as e:
                            self.record_error("多播数据处理失败", e)
                            break
                else:
                    consecutive_timeouts += 1
                    if consecutive_timeouts > max_consecutive_timeouts:
                        self.logger.warning("多播套接字长时间无数据")
                        consecutive_timeouts = 0
                        if not self.health_check_multicast_socket():
                            self.logger.error("多播套接字健康检查失败")
                            break
                
            except Exception as e:
                self.record_error("多播接收线程错误", e)
                if self.consecutive_errors > 10:
                    self.logger.error("多播接收连续错误过多，线程退出")
                    break
                time.sleep(self.reconnect_delay)
        
        self.logger.info("多播接收线程结束")
    
    def health_check_tun_interface(self):
        """TAP接口健康检查"""
        try:
            # 检查接口是否存在且启用
            result = subprocess.run(['ip', 'link', 'show', self.tun_name], 
                                  capture_output=True, text=True, timeout=5)
            
            if result.returncode != 0:
                self.logger.error(f"TAP接口 {self.tun_name} 不存在")
                return False
            
            # 检查接口状态
            if 'UP' not in result.stdout:
                self.logger.warning(f"TAP接口 {self.tun_name} 未启用，尝试启用")
                subprocess.run(['ip', 'link', 'set', self.tun_name, 'up'], 
                             capture_output=True, text=True, timeout=5)
            
            return True
            
        except Exception as e:
            self.logger.error(f"TAP接口健康检查失败: {e}")
            return False
    
    def health_check_multicast_socket(self):
        """多播套接字健康检查"""
        try:
            # 检查套接字是否仍然有效
            if not self.multicast_sock:
                return False
            
            # 尝试获取套接字选项
            self.multicast_sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR)
            return True
            
        except Exception as e:
            self.logger.error(f"多播套接字健康检查失败: {e}")
            return False
    
    def stats_monitor_thread(self):
        """统计监控线程"""
        self.logger.info("统计监控线程启动")
        
        last_goose_count = 0
        last_multicast_count = 0
        last_time = time.time()
        
        while self.running:
            try:
                time.sleep(self.health_check_interval)
                
                current_time = time.time()
                time_diff = current_time - last_time
                
                # 计算吞吐量
                goose_diff = self.stats['goose_to_ip'] - last_goose_count
                multicast_diff = self.stats['ip_to_goose'] - last_multicast_count
                
                self.stats['throughput_goose_per_sec'] = goose_diff / time_diff
                self.stats['throughput_multicast_per_sec'] = multicast_diff / time_diff
                self.stats['uptime'] = current_time - self.stats['start_time']
                
                # 更新计数器
                last_goose_count = self.stats['goose_to_ip']
                last_multicast_count = self.stats['ip_to_goose']
                last_time = current_time
                
                # 导出统计信息
                if self.config.getboolean('enable_stats_export', True):
                    self.export_stats()
                
                # 记录健康状态
                if self.debug or (current_time - self.stats['start_time']) % 300 < self.health_check_interval:
                    self.logger.info(f"服务健康状态 - "
                                   f"运行时间: {self.stats['uptime']:.0f}s, "
                                   f"GOOSE处理: {self.stats['goose_to_ip']}, "
                                   f"多播处理: {self.stats['ip_to_goose']}, "
                                   f"错误: {self.stats['errors']}")
                
            except Exception as e:
                self.record_error("统计监控线程错误", e)
        
        self.logger.info("统计监控线程结束")
    
    def export_stats(self):
        """导出统计信息到文件"""
        try:
            stats_file = self.config.get('stats_file', '/var/lib/goose-bridge/stats.json')
            
            # 确保目录存在
            os.makedirs(os.path.dirname(stats_file), exist_ok=True)
            
            # 准备统计数据
            export_data = {
                'timestamp': datetime.now().isoformat(),
                'service_info': {
                    'interface': self.tun_name,
                    'multicast_address': f"{self.multicast_ip}:{self.multicast_port}",
                    'local_ip': self.local_ip,
                    'tun_ip': self.tun_ip
                },
                'statistics': dict(self.stats),
                'health': {
                    'running': self.running,
                    'error_rate': self.stats['errors'] / max(self.stats['uptime'], 1),
                    'consecutive_errors': self.consecutive_errors
                }
            }
            
            # 写入文件
            with open(stats_file, 'w') as f:
                json.dump(export_data, f, indent=2)
                
        except Exception as e:
            self.logger.warning(f"导出统计信息失败: {e}")
    
    def print_stats(self):
        """打印统计信息"""
        uptime_str = str(timedelta(seconds=int(self.stats['uptime'])))
        
        print(f"\n📊 生产级GOOSE桥接服务统计:")
        print(f"   服务运行时间: {uptime_str}")
        print(f"   本机IP: {self.local_ip}")
        print(f"   TAP接口: {self.tun_name} ({self.tun_ip})")
        print(f"   多播地址: {self.multicast_ip}:{self.multicast_port}")
        print(f"   原始帧数: {self.stats['raw_frames']}")
        print(f"   标准GOOSE帧: {self.stats['goose_received']}")
        print(f"   VLAN GOOSE帧: {self.stats['vlan_goose_received']}")
        print(f"   GOOSE→IP转换: {self.stats['goose_to_ip']}")
        print(f"   IP→GOOSE转换: {self.stats['ip_to_goose']}")
        print(f"   GOOSE吞吐量: {self.stats['throughput_goose_per_sec']:.2f}/秒")
        print(f"   多播吞吐量: {self.stats['throughput_multicast_per_sec']:.2f}/秒")
        print(f"   错误次数: {self.stats['errors']}")
        print(f"   连续错误: {self.consecutive_errors}")
        
        # IGMP保活统计
        if hasattr(self, 'igmp_keepalive') and self.igmp_keepalive:
            igmp_stats = self.igmp_keepalive.get_stats()
            print(f"\n🔄 IGMP保活统计:")
            print(f"   保活次数: {igmp_stats['keepalive_count']}")
            print(f"   重注册次数: {igmp_stats['reregister_count']}")
            print(f"   监控检查: {igmp_stats['monitor_checks']}")
            print(f"   本地缺失: {igmp_stats['local_missing_count']}")
            print(f"   TGW缺失: {igmp_stats['tgw_missing_count']}")
            if igmp_stats['last_keepalive']:
                print(f"   最后保活: {igmp_stats['last_keepalive'].strftime('%H:%M:%S')}")
    
    def create_pid_file(self):
        """创建PID文件"""
        try:
            pid_file = self.config.get('pid_file', '/var/run/goose-bridge.pid')
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
            pid_file = self.config.get('pid_file', '/var/run/goose-bridge.pid')
            if os.path.exists(pid_file):
                os.remove(pid_file)
                self.logger.info("PID文件已删除")
        except Exception as e:
            self.logger.warning(f"删除PID文件失败: {e}")
    
    def start(self):
        """启动桥接服务"""
        self.logger.info("启动生产级GOOSE桥接服务")
        
        # 检查权限
        if os.geteuid() != 0:
            self.logger.error("需要root权限来创建TAP接口")
            return False
        
        # 创建PID文件
        pid_file = self.create_pid_file()
        
        try:
            # 创建TAP接口
            if not self.create_tun_interface():
                return False
            
            # 创建多播套接字
            if not self.create_multicast_socket():
                return False
            
            self.logger.info(f"服务配置:")
            self.logger.info(f"  本机IP: {self.local_ip}")
            self.logger.info(f"  TAP接口: {self.tun_name} ({self.tun_ip})")
            self.logger.info(f"  多播地址: {self.multicast_ip}:{self.multicast_port}")
            self.logger.info(f"  工作线程: {self.worker_threads}")
            self.logger.info(f"  缓冲区大小: {self.buffer_size}")
            self.logger.info(f"  批处理大小: {self.batch_size}")
            
            # 启动服务
            self.running = True
            
            # 启动处理线程
            threads = [
                threading.Thread(target=self.tun_reader_thread, name="TUN-Reader", daemon=True),
                threading.Thread(target=self.multicast_reader_thread, name="Multicast-Reader", daemon=True),
                threading.Thread(target=self.stats_monitor_thread, name="Stats-Monitor", daemon=True)
            ]
            
            for thread in threads:
                thread.start()
                self.logger.info(f"线程 {thread.name} 已启动")
            
            # 启动IGMP保活管理器
            if self.igmp_keepalive:
                if self.igmp_keepalive.start():
                    self.logger.info("🔄 IGMP保活管理器已启动")
                else:
                    self.logger.warning("⚠️  IGMP保活管理器启动失败")
            
            self.logger.info("✅ 生产级GOOSE桥接服务启动成功")
            
            # 主循环
            try:
                last_stats_time = time.time()
                
                while self.running:
                    time.sleep(1)
                    
                    # 定期打印统计信息
                    if time.time() - last_stats_time > 300:  # 每5分钟
                        self.print_stats()
                        last_stats_time = time.time()
            
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
        """停止桥接服务"""
        self.logger.info("正在停止生产级GOOSE桥接服务...")
        
        self.running = False
        
        # 停止IGMP保活管理器
        if hasattr(self, 'igmp_keepalive') and self.igmp_keepalive:
            self.igmp_keepalive.stop()
        
        # 关闭套接字
        if self.multicast_sock:
            try:
                self.multicast_sock.close()
                self.logger.info("多播套接字已关闭")
            except Exception as e:
                self.logger.warning(f"关闭多播套接字失败: {e}")
        
        # 关闭TUN接口
        if self.tun_fd:
            try:
                os.close(self.tun_fd)
                self.logger.info("TAP接口已关闭")
            except Exception as e:
                self.logger.warning(f"关闭TAP接口失败: {e}")
        
        # 删除TUN接口
        try:
            subprocess.run(f"ip link delete {self.tun_name}".split(), 
                         capture_output=True, text=True, timeout=10)
            self.logger.info(f"TAP接口 {self.tun_name} 已删除")
        except Exception as e:
            self.logger.warning(f"删除TAP接口失败: {e}")
        
        # 导出最终统计信息
        if self.config.getboolean('enable_stats_export', True):
            self.export_stats()
        
        self.print_stats()
        self.logger.info("✅ 生产级GOOSE桥接服务已停止")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='生产级GOOSE协议云端桥接服务')
    parser.add_argument('-c', '--config', help='配置文件路径')
    parser.add_argument('-d', '--daemon', action='store_true', help='以守护进程模式运行')
    parser.add_argument('--interface', default='goose0', help='TUN接口名称')
    parser.add_argument('--debug', action='store_true', help='启用调试模式')
    
    args = parser.parse_args()
    
    # 创建桥接服务
    bridge = ProductionGOOSEBridge(config_file=args.config)
    bridge.config_file = args.config  # 保存配置文件路径用于重载
    
    # 覆盖命令行参数
    if args.interface != 'goose0':
        bridge.tun_name = args.interface
    if args.debug:
        bridge.debug = True
        bridge.logger.setLevel(logging.DEBUG)
    
    # 启动服务
    success = bridge.start()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
