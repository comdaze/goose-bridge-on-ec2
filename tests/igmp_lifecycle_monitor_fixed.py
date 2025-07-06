#!/usr/bin/env python3
"""
IGMP生命周期监控工具 - 修复版
修复了地址解析的BUG
"""

import time
import subprocess
import json
import socket
import struct
import threading
from datetime import datetime, timedelta

class IGMPLifecycleMonitor:
    """IGMP生命周期监控器 - 修复版"""
    
    def __init__(self):
        self.running = False
        self.multicast_ip = '224.0.1.100'
        self.multicast_port = 61850
        self.tgw_domain_id = 'tgw-mcast-domain-01d79015018690cef'
        
        # 监控数据
        self.igmp_history = []
        self.tgw_history = []
    
    def get_local_igmp_groups(self):
        """获取本地IGMP组信息 - 修复版"""
        try:
            with open('/proc/net/igmp', 'r') as f:
                content = f.read()
            
            groups = []
            lines = content.strip().split('\n')
            current_device = None
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # 设备行
                if line.startswith(('1\t', '2\t', '3\t', '4\t', '5\t')):
                    parts = line.split()
                    if len(parts) >= 2:
                        current_device = parts[1].rstrip(':')
                
                # 组信息行 (以制表符开头)
                elif line.startswith('\t') and current_device:
                    parts = line.split()
                    if len(parts) >= 4:
                        group_hex = parts[0]
                        users = int(parts[1])
                        timer = parts[2]
                        reporter = int(parts[3])
                        
                        # 修复：正确转换十六进制IP到点分十进制
                        try:
                            # /proc/net/igmp中的地址是小端序十六进制
                            ip_int = int(group_hex, 16)
                            ip_bytes = struct.pack('<I', ip_int)  # 小端序
                            ip_addr = socket.inet_ntoa(ip_bytes)
                            
                            groups.append({
                                'device': current_device,
                                'ip': ip_addr,
                                'users': users,
                                'timer': timer,
                                'reporter': reporter,
                                'timestamp': datetime.now(),
                                'hex': group_hex
                            })
                        except Exception as e:
                            print(f"地址转换错误 {group_hex}: {e}")
            
            return groups
            
        except Exception as e:
            print(f"读取本地IGMP组失败: {e}")
            return []
    
    def get_tgw_multicast_groups(self):
        """获取TGW多播域组信息"""
        try:
            result = subprocess.run([
                'aws', 'ec2', 'search-transit-gateway-multicast-groups',
                '--transit-gateway-multicast-domain-id', self.tgw_domain_id,
                '--output', 'json'
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                groups = []
                
                for group in data.get('MulticastGroups', []):
                    groups.append({
                        'ip': group.get('GroupIpAddress'),
                        'member_type': group.get('MemberType'),
                        'network_interface': group.get('NetworkInterfaceId'),
                        'is_member': group.get('GroupMember'),
                        'is_source': group.get('GroupSource'),
                        'timestamp': datetime.now()
                    })
                
                return groups
            else:
                print(f"查询TGW多播组失败: {result.stderr}")
                return []
                
        except Exception as e:
            print(f"获取TGW多播组异常: {e}")
            return []
    
    def join_multicast_group(self):
        """加入多播组"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('', self.multicast_port))
            
            # 加入多播组
            mreq = struct.pack('4sl', socket.inet_aton(self.multicast_ip), socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            
            print(f"✅ 成功加入多播组 {self.multicast_ip}:{self.multicast_port}")
            return sock
            
        except Exception as e:
            print(f"❌ 加入多播组失败: {e}")
            return None
    
    def leave_multicast_group(self, sock):
        """离开多播组"""
        try:
            if sock:
                # 离开多播组
                mreq = struct.pack('4sl', socket.inet_aton(self.multicast_ip), socket.INADDR_ANY)
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
                sock.close()
                print(f"✅ 成功离开多播组 {self.multicast_ip}")
        except Exception as e:
            print(f"❌ 离开多播组失败: {e}")
    
    def monitor_lifecycle(self, duration=300, interval=5):
        """监控IGMP生命周期 - 修复版"""
        print(f"🔍 开始监控IGMP生命周期 (修复版)")
        print(f"   监控时长: {duration} 秒")
        print(f"   检查间隔: {interval} 秒")
        print(f"   目标组: {self.multicast_ip}")
        print("=" * 60)
        
        self.running = True
        start_time = time.time()
        
        # 先加入多播组
        sock = self.join_multicast_group()
        if not sock:
            return
        
        try:
            while self.running and (time.time() - start_time) < duration:
                current_time = datetime.now()
                
                # 获取本地IGMP状态
                local_groups = self.get_local_igmp_groups()
                target_local = [g for g in local_groups if g['ip'] == self.multicast_ip]
                
                # 获取TGW状态
                tgw_groups = self.get_tgw_multicast_groups()
                target_tgw = [g for g in tgw_groups if g['ip'] == self.multicast_ip]
                
                # 记录历史
                self.igmp_history.append({
                    'timestamp': current_time,
                    'local_groups': target_local,
                    'tgw_groups': target_tgw
                })
                
                # 显示当前状态
                elapsed = int(time.time() - start_time)
                print(f"\n⏰ [{current_time.strftime('%H:%M:%S')}] 第{elapsed}秒:")
                
                if target_local:
                    for group in target_local:
                        print(f"   ✅ 本地IGMP: {group['ip']} 设备:{group['device']} "
                              f"用户:{group['users']} 定时器:{group['timer']} 报告者:{group['reporter']} "
                              f"(hex:{group['hex']})")
                else:
                    print(f"   ❌ 本地IGMP: {self.multicast_ip} 未找到")
                    
                    # 显示所有本地IGMP组用于调试
                    if local_groups:
                        print(f"   🔍 本地所有IGMP组:")
                        for group in local_groups[:5]:  # 只显示前5个
                            print(f"      - {group['ip']} ({group['hex']}) 设备:{group['device']}")
                
                if target_tgw:
                    tgw_count = len(target_tgw)
                    member_count = len([g for g in target_tgw if g['is_member']])
                    print(f"   🌐 TGW状态: {tgw_count}个接口, {member_count}个成员")
                    
                    for group in target_tgw[:3]:  # 只显示前3个
                        eni_short = group['network_interface'][-8:] if group['network_interface'] else 'N/A'
                        print(f"      - ENI:...{eni_short} 类型:{group['member_type']} "
                              f"成员:{group['is_member']} 源:{group['is_source']}")
                else:
                    print(f"   ❌ TGW状态: {self.multicast_ip} 未找到")
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n监控被中断")
        finally:
            self.running = False
            self.leave_multicast_group(sock)
        
        # 分析结果
        self.analyze_lifecycle()
    
    def analyze_lifecycle(self):
        """分析生命周期数据"""
        if not self.igmp_history:
            return
        
        print(f"\n📊 IGMP生命周期分析 (修复版):")
        print("=" * 60)
        
        # 统计本地IGMP存在时间
        local_present_count = sum(1 for h in self.igmp_history if h['local_groups'])
        local_present_rate = local_present_count / len(self.igmp_history) * 100
        
        # 统计TGW存在时间
        tgw_present_count = sum(1 for h in self.igmp_history if h['tgw_groups'])
        tgw_present_rate = tgw_present_count / len(self.igmp_history) * 100
        
        print(f"📈 统计结果:")
        print(f"   总检查次数: {len(self.igmp_history)}")
        print(f"   本地IGMP存在率: {local_present_rate:.1f}% ({local_present_count}次)")
        print(f"   TGW注册存在率: {tgw_present_rate:.1f}% ({tgw_present_count}次)")
        
        # 计算平均生存时间
        if len(self.igmp_history) > 1:
            total_duration = (self.igmp_history[-1]['timestamp'] - self.igmp_history[0]['timestamp']).total_seconds()
            print(f"\n⏱️  监控总时长: {total_duration:.0f} 秒")
            
            if local_present_rate == 100 and tgw_present_rate == 100:
                print(f"🎉 IGMP注册在整个监控期间保持稳定！")
            elif local_present_rate > 90 and tgw_present_rate > 90:
                print(f"✅ IGMP注册基本稳定，偶有波动")
            else:
                print(f"⚠️  IGMP注册存在不稳定情况")

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='IGMP生命周期监控工具 - 修复版')
    subparsers = parser.add_subparsers(dest='command', help='可用命令')
    
    # 生命周期监控
    monitor_parser = subparsers.add_parser('monitor', help='监控IGMP生命周期')
    monitor_parser.add_argument('--duration', type=int, default=300, help='监控时长(秒)')
    monitor_parser.add_argument('--interval', type=int, default=5, help='检查间隔(秒)')
    
    # 状态检查
    subparsers.add_parser('status', help='检查当前IGMP状态')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    monitor = IGMPLifecycleMonitor()
    
    if args.command == 'monitor':
        monitor.monitor_lifecycle(args.duration, args.interval)
    elif args.command == 'status':
        print("📋 当前IGMP状态 (修复版):")
        local_groups = monitor.get_local_igmp_groups()
        tgw_groups = monitor.get_tgw_multicast_groups()
        
        print(f"\n本地IGMP组 ({len(local_groups)}个):")
        for group in local_groups:
            print(f"  {group['ip']} ({group['hex']}) - 设备:{group['device']} 用户:{group['users']} 定时器:{group['timer']}")
        
        print(f"\nTGW多播组 ({len(tgw_groups)}个):")
        target_groups = [g for g in tgw_groups if g['ip'] == '224.0.1.100']
        print(f"  224.0.1.100: {len(target_groups)}个注册")

if __name__ == "__main__":
    main()
