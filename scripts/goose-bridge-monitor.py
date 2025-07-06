#!/usr/bin/env python3
"""
GOOSE桥接服务监控工具
提供实时监控、统计分析和健康检查功能
"""

import json
import time
import sys
import os
import subprocess
import argparse
from datetime import datetime, timedelta
from pathlib import Path

class GOOSEBridgeMonitor:
    """GOOSE桥接服务监控器"""
    
    def __init__(self, stats_file='/var/lib/goose-bridge/stats.json'):
        self.stats_file = stats_file
        self.service_name = 'goose-bridge'
    
    def get_service_status(self):
        """获取服务状态"""
        try:
            result = subprocess.run(['systemctl', 'is-active', self.service_name], 
                                  capture_output=True, text=True)
            active = result.stdout.strip() == 'active'
            
            result = subprocess.run(['systemctl', 'is-enabled', self.service_name], 
                                  capture_output=True, text=True)
            enabled = result.stdout.strip() == 'enabled'
            
            return {'active': active, 'enabled': enabled}
        except:
            return {'active': False, 'enabled': False}
    
    def get_stats(self):
        """获取统计信息"""
        try:
            if os.path.exists(self.stats_file):
                with open(self.stats_file, 'r') as f:
                    return json.load(f)
            return None
        except Exception as e:
            print(f"读取统计文件失败: {e}")
            return None
    
    def format_uptime(self, seconds):
        """格式化运行时间"""
        return str(timedelta(seconds=int(seconds)))
    
    def format_rate(self, rate):
        """格式化速率"""
        if rate < 1:
            return f"{rate:.3f}"
        elif rate < 10:
            return f"{rate:.2f}"
        else:
            return f"{rate:.1f}"
    
    def show_status(self):
        """显示服务状态"""
        print("🔍 GOOSE桥接服务状态监控")
        print("=" * 60)
        
        # 服务状态
        service_status = self.get_service_status()
        active_icon = "✅" if service_status['active'] else "❌"
        enabled_icon = "✅" if service_status['enabled'] else "❌"
        
        print(f"📋 服务状态:")
        print(f"   运行状态: {active_icon} {'运行中' if service_status['active'] else '已停止'}")
        print(f"   开机启动: {enabled_icon} {'已启用' if service_status['enabled'] else '已禁用'}")
        
        # 统计信息
        stats = self.get_stats()
        if stats:
            print(f"\n📊 服务统计 (更新时间: {stats['timestamp']}):")
            
            service_info = stats.get('service_info', {})
            statistics = stats.get('statistics', {})
            health = stats.get('health', {})
            
            print(f"   接口配置: {service_info.get('interface', 'N/A')}")
            print(f"   多播地址: {service_info.get('multicast_address', 'N/A')}")
            print(f"   本机IP: {service_info.get('local_ip', 'N/A')}")
            print(f"   TUN接口IP: {service_info.get('tun_ip', 'N/A')}")
            
            uptime = statistics.get('uptime', 0)
            print(f"\n⏱️  运行信息:")
            print(f"   运行时间: {self.format_uptime(uptime)}")
            print(f"   处理帧数: {statistics.get('raw_frames', 0)}")
            print(f"   GOOSE帧: {statistics.get('goose_received', 0)} + {statistics.get('vlan_goose_received', 0)} (VLAN)")
            print(f"   转换统计: GOOSE→IP {statistics.get('goose_to_ip', 0)}, IP→GOOSE {statistics.get('ip_to_goose', 0)}")
            
            goose_rate = statistics.get('throughput_goose_per_sec', 0)
            multicast_rate = statistics.get('throughput_multicast_per_sec', 0)
            print(f"   实时吞吐: GOOSE {self.format_rate(goose_rate)}/s, 多播 {self.format_rate(multicast_rate)}/s")
            
            error_count = statistics.get('errors', 0)
            error_rate = health.get('error_rate', 0)
            consecutive_errors = health.get('consecutive_errors', 0)
            
            print(f"\n🏥 健康状态:")
            print(f"   总错误数: {error_count}")
            print(f"   错误率: {error_rate:.6f}/秒")
            print(f"   连续错误: {consecutive_errors}")
            
            # 健康评估
            if error_rate < 0.001 and consecutive_errors < 5:
                health_status = "🟢 健康"
            elif error_rate < 0.01 and consecutive_errors < 20:
                health_status = "🟡 警告"
            else:
                health_status = "🔴 异常"
            
            print(f"   整体状态: {health_status}")
        else:
            print(f"\n⚠️  无法获取统计信息")
            if not service_status['active']:
                print("   服务未运行")
            else:
                print("   统计文件不存在或无法读取")
    
    def show_logs(self, lines=50, follow=False):
        """显示日志"""
        cmd = ['journalctl', '-u', self.service_name, '-n', str(lines)]
        if follow:
            cmd.append('-f')
        
        try:
            if follow:
                subprocess.run(cmd)
            else:
                result = subprocess.run(cmd, capture_output=True, text=True)
                print(result.stdout)
        except KeyboardInterrupt:
            pass
        except Exception as e:
            print(f"获取日志失败: {e}")
    
    def monitor_realtime(self, interval=5):
        """实时监控"""
        print("🔄 实时监控模式 (按Ctrl+C退出)")
        print("=" * 60)
        
        try:
            while True:
                # 清屏
                os.system('clear')
                
                # 显示时间
                print(f"📅 监控时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print()
                
                # 显示状态
                self.show_status()
                
                # 等待
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n监控已停止")
    
    def service_control(self, action):
        """服务控制"""
        valid_actions = ['start', 'stop', 'restart', 'reload', 'enable', 'disable']
        
        if action not in valid_actions:
            print(f"❌ 无效操作: {action}")
            print(f"有效操作: {', '.join(valid_actions)}")
            return False
        
        try:
            print(f"🔧 执行操作: {action}")
            result = subprocess.run(['systemctl', action, self.service_name], 
                                  capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"✅ 操作成功: {action}")
                return True
            else:
                print(f"❌ 操作失败: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"❌ 执行操作失败: {e}")
            return False
    
    def export_report(self, output_file=None):
        """导出监控报告"""
        if not output_file:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = f"goose_bridge_report_{timestamp}.json"
        
        try:
            report = {
                'report_time': datetime.now().isoformat(),
                'service_status': self.get_service_status(),
                'statistics': self.get_stats()
            }
            
            with open(output_file, 'w') as f:
                json.dump(report, f, indent=2)
            
            print(f"✅ 监控报告已导出: {output_file}")
            return True
            
        except Exception as e:
            print(f"❌ 导出报告失败: {e}")
            return False

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='GOOSE桥接服务监控工具')
    parser.add_argument('--stats-file', default='/var/lib/goose-bridge/stats.json',
                       help='统计文件路径')
    
    subparsers = parser.add_subparsers(dest='command', help='可用命令')
    
    # 状态命令
    subparsers.add_parser('status', help='显示服务状态')
    
    # 日志命令
    log_parser = subparsers.add_parser('logs', help='显示服务日志')
    log_parser.add_argument('-n', '--lines', type=int, default=50, help='显示行数')
    log_parser.add_argument('-f', '--follow', action='store_true', help='跟踪日志')
    
    # 监控命令
    monitor_parser = subparsers.add_parser('monitor', help='实时监控')
    monitor_parser.add_argument('-i', '--interval', type=int, default=5, help='刷新间隔(秒)')
    
    # 服务控制命令
    control_parser = subparsers.add_parser('control', help='服务控制')
    control_parser.add_argument('action', choices=['start', 'stop', 'restart', 'reload', 'enable', 'disable'],
                               help='控制操作')
    
    # 报告命令
    report_parser = subparsers.add_parser('report', help='导出监控报告')
    report_parser.add_argument('-o', '--output', help='输出文件名')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    monitor = GOOSEBridgeMonitor(args.stats_file)
    
    if args.command == 'status':
        monitor.show_status()
    elif args.command == 'logs':
        monitor.show_logs(args.lines, args.follow)
    elif args.command == 'monitor':
        monitor.monitor_realtime(args.interval)
    elif args.command == 'control':
        monitor.service_control(args.action)
    elif args.command == 'report':
        monitor.export_report(args.output)

if __name__ == "__main__":
    main()
