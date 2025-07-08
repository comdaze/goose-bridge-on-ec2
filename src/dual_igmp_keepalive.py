#!/usr/bin/env python3
"""
双路径IGMP保活管理器
为双多播组提供独立的IGMP保活机制，防止AWS TGW超时
"""

import socket
import struct
import threading
import time
import json
import subprocess
from datetime import datetime

class DualIGMPKeepaliveManager:
    """双路径IGMP保活管理器"""
    
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        
        # 多播配置
        self.primary_multicast_ip = config.get('primary_multicast_ip', '224.0.1.100')
        self.backup_multicast_ip = config.get('backup_multicast_ip', '224.0.1.101')
        self.multicast_port = config.getint('multicast_port', 61850)
        
        # IGMP配置
        self.keepalive_interval = config.getint('igmp_keepalive_interval', 90)
        self.monitor_interval = config.getint('igmp_monitor_interval', 120)
        self.reregister_threshold = config.getint('igmp_reregister_threshold', 2)
        self.enable_tgw_monitoring = config.getboolean('enable_tgw_monitoring', True)
        
        # TGW配置
        self.primary_tgw_domain_id = config.get('primary_tgw_multicast_domain_id', 
                                               'tgw-mcast-domain-01d79015018690cef')
        self.backup_tgw_domain_id = config.get('backup_tgw_multicast_domain_id',
                                              'tgw-mcast-domain-01d79015018690cef')
        
        # 创建独立的保活管理器
        self.primary_keepalive = SingleIGMPKeepalive(
            name="primary",
            multicast_ip=self.primary_multicast_ip,
            multicast_port=self.multicast_port,
            tgw_domain_id=self.primary_tgw_domain_id,
            config=config,
            logger=logger
        )
        
        self.backup_keepalive = SingleIGMPKeepalive(
            name="backup", 
            multicast_ip=self.backup_multicast_ip,
            multicast_port=self.multicast_port,
            tgw_domain_id=self.backup_tgw_domain_id,
            config=config,
            logger=logger
        )
        
        # 运行状态
        self.running = False
    
    def start(self):
        """启动双路径IGMP保活"""
        try:
            self.running = True
            
            # 启动主路径保活
            primary_success = self.primary_keepalive.start()
            if primary_success:
                self.logger.info("🔄 主路径IGMP保活启动成功")
            else:
                self.logger.error("❌ 主路径IGMP保活启动失败")
            
            # 启动备路径保活
            backup_success = self.backup_keepalive.start()
            if backup_success:
                self.logger.info("🔄 备路径IGMP保活启动成功")
            else:
                self.logger.error("❌ 备路径IGMP保活启动失败")
            
            if primary_success or backup_success:
                self.logger.info("✅ 双路径IGMP保活管理器启动成功")
                return True
            else:
                self.logger.error("❌ 双路径IGMP保活管理器启动失败")
                return False
                
        except Exception as e:
            self.logger.error(f"启动双路径IGMP保活失败: {e}")
            return False
    
    def stop(self):
        """停止双路径IGMP保活"""
        self.logger.info("正在停止双路径IGMP保活管理器...")
        
        self.running = False
        
        # 停止主路径保活
        self.primary_keepalive.stop()
        
        # 停止备路径保活
        self.backup_keepalive.stop()
        
        self.logger.info("✅ 双路径IGMP保活管理器已停止")
    
    def get_stats(self):
        """获取双路径统计信息"""
        return {
            'primary': self.primary_keepalive.get_stats(),
            'backup': self.backup_keepalive.get_stats()
        }

class SingleIGMPKeepalive:
    """单路径IGMP保活管理器"""
    
    def __init__(self, name, multicast_ip, multicast_port, tgw_domain_id, config, logger):
        self.name = name
        self.multicast_ip = multicast_ip
        self.multicast_port = multicast_port
        self.tgw_domain_id = tgw_domain_id
        self.config = config
        self.logger = logger
        
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
        """启动单路径IGMP保活"""
        if self.running:
            return True
        
        try:
            # 创建保活套接字
            self.keepalive_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.keepalive_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # 加入多播组
            mreq = struct.pack('4sl', socket.inet_aton(self.multicast_ip), socket.INADDR_ANY)
            self.keepalive_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            
            self.running = True
            
            # 启动保活线程
            self.keepalive_thread = threading.Thread(
                target=self._keepalive_worker, 
                name=f"IGMP-Keepalive-{self.name}",
                daemon=True
            )
            self.keepalive_thread.start()
            
            # 启动监控线程
            if self.enable_tgw_monitoring:
                self.monitor_thread = threading.Thread(
                    target=self._monitor_worker,
                    name=f"IGMP-Monitor-{self.name}",
                    daemon=True
                )
                self.monitor_thread.start()
            
            self.logger.info(f"🔄 {self.name}路径IGMP保活启动成功")
            self.logger.info(f"   多播地址: {self.multicast_ip}")
            self.logger.info(f"   保活间隔: {self.keepalive_interval}秒")
            self.logger.info(f"   监控间隔: {self.monitor_interval}秒")
            
            return True
            
        except Exception as e:
            self.logger.error(f"启动{self.name}路径IGMP保活失败: {e}")
            return False
    
    def stop(self):
        """停止单路径IGMP保活"""
        self.logger.info(f"正在停止{self.name}路径IGMP保活...")
        self.running = False
        
        # 关闭套接字
        if self.keepalive_sock:
            try:
                mreq = struct.pack('4sl', socket.inet_aton(self.multicast_ip), socket.INADDR_ANY)
                self.keepalive_sock.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
                self.keepalive_sock.close()
            except Exception as e:
                self.logger.warning(f"关闭{self.name}保活套接字失败: {e}")
        
        # 等待线程结束
        if self.keepalive_thread and self.keepalive_thread.is_alive():
            self.keepalive_thread.join(timeout=5)
        
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=5)
        
        self.logger.info(f"{self.name}路径IGMP保活已停止")
    
    def _keepalive_worker(self):
        """IGMP保活工作线程"""
        self.logger.info(f"🔄 {self.name}路径IGMP保活线程启动")
        
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
                self.logger.error(f"{self.name}路径IGMP保活线程错误: {e}")
                time.sleep(5)
        
        self.logger.info(f"{self.name}路径IGMP保活线程结束")
    
    def _monitor_worker(self):
        """IGMP监控工作线程"""
        self.logger.info(f"🔍 {self.name}路径IGMP监控线程启动")
        
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
                self.logger.error(f"{self.name}路径IGMP监控线程错误: {e}")
                time.sleep(10)
        
        self.logger.info(f"{self.name}路径IGMP监控线程结束")
    
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
            
            self.logger.debug(f"{self.name}路径IGMP保活完成: {self.multicast_ip} (第{self.stats['keepalive_count']}次)")
            
        except Exception as e:
            self.logger.warning(f"{self.name}路径IGMP保活失败: {e}")
    
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
            self.logger.error(f"{self.name}路径IGMP监控检查失败: {e}")
    
    def _check_local_igmp_registration(self):
        """检查本地IGMP注册状态"""
        try:
            with open('/proc/net/igmp', 'r') as f:
                content = f.read()
            
            # 将多播IP转换为十六进制格式进行查找
            ip_parts = self.multicast_ip.split('.')
            target_hex = ''.join(f'{int(part):02X}' for part in reversed(ip_parts))
            
            if target_hex in content:
                self.logger.debug(f"{self.name}路径本地IGMP注册正常: {self.multicast_ip}")
                return True
            else:
                self.logger.warning(f"⚠️  {self.name}路径本地IGMP注册缺失: {self.multicast_ip}")
                self.stats['local_missing_count'] += 1
                return False
                
        except Exception as e:
            self.logger.error(f"检查{self.name}路径本地IGMP注册失败: {e}")
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
                    self.logger.debug(f"{self.name}路径TGW多播域注册正常: {self.multicast_ip} ({len(groups)}个)")
                    self.last_tgw_check_success = True
                    return True
                else:
                    self.logger.warning(f"⚠️  {self.name}路径TGW多播域注册缺失: {self.multicast_ip}")
                    self.stats['tgw_missing_count'] += 1
                    self.last_tgw_check_success = False
                    return False
            else:
                self.logger.error(f"查询{self.name}路径TGW多播域失败: {result.stderr}")
                return self.last_tgw_check_success
                
        except Exception as e:
            self.logger.error(f"检查{self.name}路径TGW多播域注册失败: {e}")
            return self.last_tgw_check_success
    
    def _analyze_and_act(self, local_registered, tgw_registered):
        """分析状态并采取相应行动"""
        if not local_registered or not tgw_registered:
            self.consecutive_missing += 1
            
            if self.consecutive_missing >= self.reregister_threshold:
                self.logger.warning(f"🚨 {self.name}路径连续{self.consecutive_missing}次检查发现注册缺失，执行重新注册")
                self._force_reregister()
                self.consecutive_missing = 0
        else:
            # 状态正常，重置计数器
            if self.consecutive_missing > 0:
                self.logger.info(f"✅ {self.name}路径IGMP注册状态已恢复正常")
                self.consecutive_missing = 0
    
    def _force_reregister(self):
        """强制重新注册IGMP组成员"""
        try:
            self.logger.info(f"🔄 强制重新注册{self.name}路径IGMP组成员: {self.multicast_ip}")
            
            # 重新创建套接字
            old_sock = self.keepalive_sock
            
            # 创建新套接字
            new_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            new_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
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
            self.logger.info(f"✅ {self.name}路径IGMP重新注册完成 (第{self.stats['reregister_count']}次)")
            
        except Exception as e:
            self.logger.error(f"强制重新注册{self.name}路径失败: {e}")
    
    def get_stats(self):
        """获取统计信息"""
        return dict(self.stats)
