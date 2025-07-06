#!/usr/bin/env python3
"""
AWS TGW IGMP机制验证工具
基于AWS官方文档验证TGW IGMP的时效性机制

AWS TGW IGMP机制：
- 每2分钟发送IGMPv2 QUERY
- 连续3次未响应(6分钟) → 临时移除
- 故障时继续转发最多7分钟
- 继续查询最多12小时
- 12小时未响应 → 永久移除
"""

import time
import socket
import struct
import subprocess
import json
import threading
from datetime import datetime, timedelta

class AWSTransitGatewayIGMPValidator:
    """AWS TGW IGMP机制验证器"""
    
    def __init__(self, multicast_ip='224.0.1.100', multicast_port=61850):
        self.multicast_ip = multicast_ip
        self.multicast_port = multicast_port
        self.tgw_domain_id = 'tgw-mcast-domain-01d79015018690cef'
        
        # 测试状态
        self.test_running = False
        self.sock = None
        
        # 记录数据
        self.timeline = []
        
    def log_event(self, event_type, description, local_igmp=None, tgw_count=None):
        """记录事件"""
        event = {
            'timestamp': datetime.now(),
            'event_type': event_type,
            'description': description,
            'local_igmp': local_igmp,
            'tgw_count': tgw_count
        }
        self.timeline.append(event)
        
        timestamp_str = event['timestamp'].strftime('%H:%M:%S')
        print(f"[{timestamp_str}] {event_type}: {description}")
        if local_igmp is not None:
            print(f"           本地IGMP: {'✅' if local_igmp else '❌'}")
        if tgw_count is not None:
            print(f"           TGW成员: {tgw_count}个")
    
    def check_local_igmp(self):
        """检查本地IGMP状态"""
        try:
            with open('/proc/net/igmp', 'r') as f:
                content = f.read()
            
            # 查找目标多播地址的十六进制表示
            target_hex = '640100E0'  # 224.0.1.100的十六进制
            return target_hex in content
            
        except Exception as e:
            print(f"检查本地IGMP失败: {e}")
            return False
    
    def check_tgw_registration(self):
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
                return len(groups)
            else:
                print(f"查询TGW失败: {result.stderr}")
                return 0
                
        except Exception as e:
            print(f"检查TGW注册失败: {e}")
            return 0
    
    def join_multicast_group(self):
        """加入多播组"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind(('', self.multicast_port))
            
            # 加入多播组
            mreq = struct.pack('4sl', socket.inet_aton(self.multicast_ip), socket.INADDR_ANY)
            self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            
            local_igmp = self.check_local_igmp()
            tgw_count = self.check_tgw_registration()
            
            self.log_event("JOIN", f"加入多播组 {self.multicast_ip}", local_igmp, tgw_count)
            return True
            
        except Exception as e:
            self.log_event("ERROR", f"加入多播组失败: {e}")
            return False
    
    def leave_multicast_group(self):
        """离开多播组"""
        try:
            if self.sock:
                mreq = struct.pack('4sl', socket.inet_aton(self.multicast_ip), socket.INADDR_ANY)
                self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
                self.sock.close()
                self.sock = None
            
            local_igmp = self.check_local_igmp()
            tgw_count = self.check_tgw_registration()
            
            self.log_event("LEAVE", f"离开多播组 {self.multicast_ip}", local_igmp, tgw_count)
            return True
            
        except Exception as e:
            self.log_event("ERROR", f"离开多播组失败: {e}")
            return False
    
    def monitor_status(self, duration_minutes=15):
        """监控状态变化"""
        print(f"🔍 开始监控TGW IGMP状态变化")
        print(f"   监控时长: {duration_minutes} 分钟")
        print(f"   检查间隔: 30秒")
        print(f"   目标: 验证AWS TGW的6分钟临时移除机制")
        print("=" * 70)
        
        start_time = datetime.now()
        end_time = start_time + timedelta(minutes=duration_minutes)
        
        while datetime.now() < end_time:
            local_igmp = self.check_local_igmp()
            tgw_count = self.check_tgw_registration()
            
            elapsed = datetime.now() - start_time
            elapsed_str = str(elapsed).split('.')[0]  # 去掉微秒
            
            self.log_event("CHECK", f"状态检查 (已运行 {elapsed_str})", local_igmp, tgw_count)
            
            time.sleep(30)  # 每30秒检查一次
    
    def test_aws_igmp_timeout(self):
        """测试AWS TGW IGMP超时机制"""
        print("🧪 AWS TGW IGMP超时机制测试")
        print("=" * 70)
        print("测试计划:")
        print("1. 加入多播组")
        print("2. 监控5分钟 (观察正常状态)")
        print("3. 离开多播组")
        print("4. 监控10分钟 (观察TGW超时行为)")
        print("5. 分析结果")
        print("=" * 70)
        
        # 阶段1: 加入多播组
        if not self.join_multicast_group():
            return
        
        # 阶段2: 监控正常状态 (5分钟)
        print(f"\n📊 阶段1: 监控正常状态 (5分钟)")
        print("-" * 50)
        self.monitor_status(5)
        
        # 阶段3: 离开多播组
        print(f"\n📤 阶段2: 离开多播组")
        print("-" * 50)
        self.leave_multicast_group()
        
        # 阶段4: 监控超时行为 (10分钟)
        print(f"\n⏰ 阶段3: 监控TGW超时行为 (10分钟)")
        print("根据AWS文档，TGW应该在6分钟后临时移除成员")
        print("-" * 50)
        self.monitor_status(10)
        
        # 阶段5: 分析结果
        self.analyze_results()
    
    def test_keepalive_effectiveness(self):
        """测试保活机制的有效性"""
        print("🔄 IGMP保活机制有效性测试")
        print("=" * 70)
        print("测试计划:")
        print("1. 加入多播组")
        print("2. 每90秒执行一次保活操作")
        print("3. 监控15分钟")
        print("4. 验证TGW注册是否保持稳定")
        print("=" * 70)
        
        # 加入多播组
        if not self.join_multicast_group():
            return
        
        # 启动保活线程
        keepalive_thread = threading.Thread(target=self._keepalive_worker, daemon=True)
        keepalive_thread.start()
        
        # 监控15分钟
        self.monitor_status(15)
        
        # 停止并分析
        self.test_running = False
        self.leave_multicast_group()
        self.analyze_results()
    
    def _keepalive_worker(self):
        """保活工作线程"""
        self.test_running = True
        keepalive_count = 0
        
        while self.test_running:
            time.sleep(90)  # 每90秒保活一次
            
            if not self.test_running:
                break
            
            try:
                # 执行保活：重新加入多播组
                mreq = struct.pack('4sl', socket.inet_aton(self.multicast_ip), socket.INADDR_ANY)
                self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
                time.sleep(0.1)
                self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                
                keepalive_count += 1
                local_igmp = self.check_local_igmp()
                tgw_count = self.check_tgw_registration()
                
                self.log_event("KEEPALIVE", f"保活操作 #{keepalive_count}", local_igmp, tgw_count)
                
            except Exception as e:
                self.log_event("ERROR", f"保活操作失败: {e}")
    
    def analyze_results(self):
        """分析测试结果"""
        print(f"\n📊 测试结果分析")
        print("=" * 70)
        
        if not self.timeline:
            print("没有记录数据")
            return
        
        # 统计事件
        join_events = [e for e in self.timeline if e['event_type'] == 'JOIN']
        leave_events = [e for e in self.timeline if e['event_type'] == 'LEAVE']
        check_events = [e for e in self.timeline if e['event_type'] == 'CHECK']
        keepalive_events = [e for e in self.timeline if e['event_type'] == 'KEEPALIVE']
        
        print(f"📈 事件统计:")
        print(f"   加入事件: {len(join_events)}")
        print(f"   离开事件: {len(leave_events)}")
        print(f"   状态检查: {len(check_events)}")
        print(f"   保活操作: {len(keepalive_events)}")
        
        # 分析TGW行为
        if leave_events and check_events:
            leave_time = leave_events[0]['timestamp']
            
            # 查找TGW成员数变为0的时间点
            tgw_disappear_time = None
            for event in check_events:
                if event['timestamp'] > leave_time and event['tgw_count'] == 0:
                    tgw_disappear_time = event['timestamp']
                    break
            
            if tgw_disappear_time:
                timeout_duration = tgw_disappear_time - leave_time
                timeout_minutes = timeout_duration.total_seconds() / 60
                
                print(f"\n⏰ TGW超时分析:")
                print(f"   离开时间: {leave_time.strftime('%H:%M:%S')}")
                print(f"   TGW移除时间: {tgw_disappear_time.strftime('%H:%M:%S')}")
                print(f"   超时时长: {timeout_minutes:.1f} 分钟")
                
                if 5.5 <= timeout_minutes <= 6.5:
                    print(f"   ✅ 符合AWS文档描述的6分钟超时机制")
                else:
                    print(f"   ⚠️  超时时长与AWS文档不符 (预期约6分钟)")
            else:
                print(f"\n⏰ TGW超时分析:")
                print(f"   在监控期间TGW注册未消失")
                print(f"   可能需要更长的监控时间")
        
        # 显示时间线
        print(f"\n📋 详细时间线:")
        for event in self.timeline[-10:]:  # 显示最后10个事件
            timestamp_str = event['timestamp'].strftime('%H:%M:%S')
            print(f"   [{timestamp_str}] {event['event_type']}: {event['description']}")

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='AWS TGW IGMP机制验证工具')
    subparsers = parser.add_subparsers(dest='test_type', help='测试类型')
    
    # 超时测试
    timeout_parser = subparsers.add_parser('timeout', help='测试TGW IGMP超时机制')
    
    # 保活测试
    keepalive_parser = subparsers.add_parser('keepalive', help='测试保活机制有效性')
    
    # 状态检查
    status_parser = subparsers.add_parser('status', help='检查当前状态')
    
    args = parser.parse_args()
    
    if not args.test_type:
        parser.print_help()
        return
    
    validator = AWSTransitGatewayIGMPValidator()
    
    if args.test_type == 'timeout':
        validator.test_aws_igmp_timeout()
    elif args.test_type == 'keepalive':
        validator.test_keepalive_effectiveness()
    elif args.test_type == 'status':
        local_igmp = validator.check_local_igmp()
        tgw_count = validator.check_tgw_registration()
        
        print("📋 当前IGMP状态:")
        print(f"   本地IGMP: {'✅ 已注册' if local_igmp else '❌ 未注册'}")
        print(f"   TGW成员: {tgw_count}个")

if __name__ == "__main__":
    main()
