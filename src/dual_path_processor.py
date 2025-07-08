#!/usr/bin/env python3
"""
双路径数据处理器
实现双TAP接口读取和双多播数据处理的核心逻辑
"""

import os
import struct
import socket
import select
import threading
import time
import logging

# 协议常量
GOOSE_ETHERTYPE = 0x88B8
VLAN_ETHERTYPE = 0x8100
GOOSE_MULTICAST_MAC = bytes.fromhex('01:0C:CD:01:00:01'.replace(':', ''))

class DualPathProcessor:
    """双路径数据处理器"""
    
    def __init__(self, tap_manager, multicast_manager, config, logger):
        self.tap_manager = tap_manager
        self.multicast_manager = multicast_manager
        self.config = config
        self.logger = logger
        
        # 性能配置
        self.buffer_size = config.getint('buffer_size', 2048)
        self.batch_size = config.getint('batch_size', 10)
        
        # 运行状态
        self.running = False
        
        # 处理线程
        self.threads = []
        
        # 统计信息
        self.stats = {
            'primary': {
                'goose_to_ip': 0,
                'ip_to_goose': 0,
                'goose_received': 0,
                'vlan_goose_received': 0,
                'errors': 0,
                'last_activity': time.time()
            },
            'backup': {
                'goose_to_ip': 0,
                'ip_to_goose': 0,
                'goose_received': 0,
                'vlan_goose_received': 0,
                'errors': 0,
                'last_activity': time.time()
            }
        }
    
    def start(self):
        """启动双路径数据处理"""
        try:
            self.running = True
            
            # 启动主路径处理线程
            primary_threads = [
                threading.Thread(
                    target=self.tap_reader_worker,
                    args=(
                        self.tap_manager.primary_fd,
                        self.multicast_manager.primary_sock,
                        self.multicast_manager.primary_multicast_ip,
                        'primary'
                    ),
                    name="Primary-TAP-Reader",
                    daemon=True
                ),
                threading.Thread(
                    target=self.multicast_receiver_worker,
                    args=(
                        self.multicast_manager.primary_sock,
                        self.tap_manager.primary_fd,
                        'primary'
                    ),
                    name="Primary-Multicast-Receiver",
                    daemon=True
                )
            ]
            
            # 启动备路径处理线程
            backup_threads = [
                threading.Thread(
                    target=self.tap_reader_worker,
                    args=(
                        self.tap_manager.backup_fd,
                        self.multicast_manager.backup_sock,
                        self.multicast_manager.backup_multicast_ip,
                        'backup'
                    ),
                    name="Backup-TAP-Reader",
                    daemon=True
                ),
                threading.Thread(
                    target=self.multicast_receiver_worker,
                    args=(
                        self.multicast_manager.backup_sock,
                        self.tap_manager.backup_fd,
                        'backup'
                    ),
                    name="Backup-Multicast-Receiver",
                    daemon=True
                )
            ]
            
            # 启动所有线程
            self.threads = primary_threads + backup_threads
            
            for thread in self.threads:
                thread.start()
                self.logger.info(f"线程 {thread.name} 已启动")
            
            self.logger.info("✅ 双路径数据处理器启动成功")
            return True
            
        except Exception as e:
            self.logger.error(f"启动双路径数据处理器失败: {e}")
            return False
    
    def stop(self):
        """停止双路径数据处理"""
        self.logger.info("正在停止双路径数据处理器...")
        self.running = False
        
        # 等待所有线程结束
        for thread in self.threads:
            if thread.is_alive():
                thread.join(timeout=5)
                if thread.is_alive():
                    self.logger.warning(f"线程 {thread.name} 未能正常结束")
                else:
                    self.logger.info(f"线程 {thread.name} 已结束")
        
        self.logger.info("✅ 双路径数据处理器已停止")
    
    def tap_reader_worker(self, tap_fd, multicast_sock, multicast_ip, path_name):
        """TAP接口读取工作线程"""
        self.logger.info(f"🔄 {path_name}路径TAP读取线程启动")
        
        consecutive_timeouts = 0
        max_consecutive_timeouts = 100
        
        while self.running:
            try:
                # 使用select进行非阻塞I/O
                ready, _, _ = select.select([tap_fd], [], [], 1.0)
                
                if ready:
                    consecutive_timeouts = 0
                    
                    # 批量读取帧以提高性能
                    frames_processed = 0
                    while frames_processed < self.batch_size and self.running:
                        try:
                            frame_data = os.read(tap_fd, self.buffer_size)
                            if not frame_data:
                                break
                            
                            # 解析帧
                            frame = self.parse_ethernet_frame_with_vlan(frame_data)
                            
                            if frame and self.is_goose_frame(frame):
                                if frame['has_vlan']:
                                    self.stats[path_name]['vlan_goose_received'] += 1
                                else:
                                    self.stats[path_name]['goose_received'] += 1
                                
                                # 转换为IP多播
                                success = self.goose_to_multicast(frame, multicast_sock, multicast_ip, path_name)
                                if success:
                                    self.stats[path_name]['goose_to_ip'] += 1
                                    self.stats[path_name]['last_activity'] = time.time()
                            
                            frames_processed += 1
                            
                        except BlockingIOError:
                            # 没有更多数据可读
                            break
                        except Exception as e:
                            self.stats[path_name]['errors'] += 1
                            self.logger.error(f"{path_name}路径TAP读取帧处理失败: {e}")
                            break
                else:
                    consecutive_timeouts += 1
                    if consecutive_timeouts > max_consecutive_timeouts:
                        self.logger.warning(f"{path_name}路径TAP接口长时间无数据")
                        consecutive_timeouts = 0
                
            except Exception as e:
                self.stats[path_name]['errors'] += 1
                self.logger.error(f"{path_name}路径TAP读取线程错误: {e}")
                time.sleep(1)
        
        self.logger.info(f"{path_name}路径TAP读取线程结束")
    
    def multicast_receiver_worker(self, multicast_sock, tap_fd, path_name):
        """多播接收工作线程"""
        self.logger.info(f"🔄 {path_name}路径多播接收线程启动")
        
        consecutive_timeouts = 0
        max_consecutive_timeouts = 100
        
        while self.running:
            try:
                ready, _, _ = select.select([multicast_sock], [], [], 1.0)
                
                if ready:
                    consecutive_timeouts = 0
                    
                    # 批量处理多播数据
                    packets_processed = 0
                    while packets_processed < self.batch_size and self.running:
                        try:
                            packet_data, sender_addr = multicast_sock.recvfrom(self.buffer_size)
                            
                            # 过滤本机发送的数据
                            if sender_addr[0] != self.multicast_manager.local_ip:
                                success = self.multicast_to_goose(packet_data, sender_addr, tap_fd, path_name)
                                if success:
                                    self.stats[path_name]['ip_to_goose'] += 1
                                    self.stats[path_name]['last_activity'] = time.time()
                            
                            packets_processed += 1
                            
                        except BlockingIOError:
                            # 没有更多数据可读
                            break
                        except Exception as e:
                            self.stats[path_name]['errors'] += 1
                            self.logger.error(f"{path_name}路径多播数据处理失败: {e}")
                            break
                else:
                    consecutive_timeouts += 1
                    if consecutive_timeouts > max_consecutive_timeouts:
                        self.logger.warning(f"{path_name}路径多播套接字长时间无数据")
                        consecutive_timeouts = 0
                
            except Exception as e:
                self.stats[path_name]['errors'] += 1
                self.logger.error(f"{path_name}路径多播接收线程错误: {e}")
                time.sleep(1)
        
        self.logger.info(f"{path_name}路径多播接收线程结束")
    
    def parse_ethernet_frame_with_vlan(self, frame_data):
        """解析支持VLAN标签的以太网帧"""
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
        """检查是否为GOOSE帧"""
        return (frame and 
                frame['ethertype'] == GOOSE_ETHERTYPE and 
                frame['dst_mac'] == GOOSE_MULTICAST_MAC)
    
    def goose_to_multicast(self, goose_frame, multicast_sock, multicast_ip, path_name):
        """将GOOSE帧转换为IP多播"""
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
            
            multicast_sock.sendto(packet_data, (multicast_ip, self.multicast_manager.multicast_port))
            
            if self.config.getboolean('debug', False):
                src_mac_str = ':'.join(f'{b:02x}' for b in goose_frame['src_mac'])
                vlan_str = f"VLAN {goose_frame['vlan_id']}" if goose_frame['has_vlan'] else "无VLAN"
                self.logger.debug(f"{path_name}路径 GOOSE→IP: {src_mac_str} → {multicast_ip}:{self.multicast_manager.multicast_port} ({vlan_str})")
            
            return True
            
        except Exception as e:
            self.logger.error(f"{path_name}路径GOOSE转多播失败: {e}")
            return False
    
    def multicast_to_goose(self, packet_data, sender_addr, tap_fd, path_name):
        """将IP多播转换为GOOSE帧"""
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
            
            # 写入TAP接口
            os.write(tap_fd, ethernet_frame)
            
            if self.config.getboolean('debug', False):
                src_mac_str = ':'.join(f'{b:02x}' for b in src_mac)
                age_ms = (int(time.time() * 1000000) - timestamp) // 1000
                vlan_str = f"VLAN {vlan_id}" if vlan_flag else "无VLAN"
                self.logger.debug(f"{path_name}路径 IP→GOOSE: {sender_addr[0]} → {src_mac_str} (延迟: {age_ms}ms, {vlan_str})")
            
            return True
            
        except Exception as e:
            self.logger.error(f"{path_name}路径多播转GOOSE失败: {e}")
            return False
    
    def get_stats(self):
        """获取统计信息"""
        return dict(self.stats)
