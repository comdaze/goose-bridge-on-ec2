#!/usr/bin/env python3
"""
基础IP多播测试脚本
测试最基本的IP协议多播功能
支持发送端、接收端和组合测试
"""

import socket
import struct
import threading
import time
import sys
import os
import signal

class BasicMulticastTester:
    def __init__(self):
        self.running = False
        self.local_ip = self.get_local_ip()
        self.stats = {
            'sent': 0,
            'received': 0,
            'errors': 0
        }
        
    def get_local_ip(self):
        """获取本机IP"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "unknown"
    
    def signal_handler(self, signum, frame):
        """信号处理"""
        print(f"\n收到信号 {signum}，正在停止...")
        self.running = False
    
    def multicast_sender(self, multicast_ip="224.1.1.1", port=12345, interval=1, count=None):
        """多播发送器"""
        print(f"📤 多播发送器启动")
        print(f"   目标: {multicast_ip}:{port}")
        print(f"   本机IP: {self.local_ip}")
        print(f"   发送间隔: {interval}秒")
        if count:
            print(f"   发送数量: {count}条")
        else:
            print(f"   持续发送 (按Ctrl+C停止)")
        
        try:
            # 创建UDP套接字
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            
            # 设置多播TTL
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            
            # 可选：设置多播接口（如果有多个网络接口）
            # sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(self.local_ip))
            
            print(f"✅ 发送套接字创建成功")
            
            sent_count = 0
            start_time = time.time()
            
            while self.running:
                try:
                    # 创建测试消息
                    timestamp = int(time.time())
                    message = f"MULTICAST_MSG_{sent_count+1}_FROM_{self.local_ip}_TIME_{timestamp}"
                    
                    # 发送多播消息
                    sock.sendto(message.encode('utf-8'), (multicast_ip, port))
                    
                    sent_count += 1
                    self.stats['sent'] = sent_count
                    
                    current_time = time.strftime("%H:%M:%S")
                    print(f"📤 [{current_time}] 发送 #{sent_count}: {message}")
                    
                    # 检查是否达到发送数量限制
                    if count and sent_count >= count:
                        break
                    
                    time.sleep(interval)
                    
                except Exception as e:
                    print(f"❌ 发送错误: {e}")
                    self.stats['errors'] += 1
                    time.sleep(1)
            
            sock.close()
            
            runtime = time.time() - start_time
            print(f"\n📊 发送统计:")
            print(f"   运行时间: {runtime:.1f}秒")
            print(f"   发送消息: {sent_count}条")
            print(f"   发送错误: {self.stats['errors']}次")
            print(f"   平均速率: {sent_count/runtime:.2f}条/秒")
            
        except Exception as e:
            print(f"❌ 发送器启动失败: {e}")
    
    def multicast_receiver(self, multicast_ip="224.1.1.1", port=12345, duration=None):
        """多播接收器"""
        print(f"📨 多播接收器启动")
        print(f"   监听: {multicast_ip}:{port}")
        print(f"   本机IP: {self.local_ip}")
        if duration:
            print(f"   接收时长: {duration}秒")
        else:
            print(f"   持续接收 (按Ctrl+C停止)")
        
        try:
            # 创建UDP套接字
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            
            # 允许地址重用
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # 绑定到指定端口（绑定到所有接口）
            sock.bind(('', port))
            print(f"✅ 绑定端口 {port} 成功")
            
            # 加入多播组
            mreq = struct.pack('4sl', socket.inet_aton(multicast_ip), socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            print(f"✅ 加入多播组 {multicast_ip} 成功")
            
            # 设置接收超时
            sock.settimeout(2.0)
            
            received_count = 0
            start_time = time.time()
            senders = set()
            last_status_time = start_time
            
            print(f"🎧 开始监听多播消息...")
            
            while self.running:
                try:
                    # 检查时间限制
                    if duration and (time.time() - start_time) > duration:
                        break
                    
                    # 接收数据
                    data, addr = sock.recvfrom(1024)
                    
                    # 解码消息
                    try:
                        message = data.decode('utf-8')
                    except:
                        message = f"<二进制数据 {len(data)} 字节>"
                    
                    received_count += 1
                    self.stats['received'] = received_count
                    senders.add(addr[0])
                    
                    current_time = time.strftime("%H:%M:%S")
                    
                    # 显示接收到的消息
                    if addr[0] == self.local_ip:
                        print(f"📨 [{current_time}] 接收 #{received_count}: {message} (来自本机)")
                    else:
                        print(f"📨 [{current_time}] 接收 #{received_count}: {message} (来自 {addr[0]})")
                    
                except socket.timeout:
                    # 定期显示状态
                    current_time = time.time()
                    if current_time - last_status_time > 10:  # 每10秒显示一次状态
                        elapsed = int(current_time - start_time)
                        if duration:
                            remaining = duration - elapsed
                            print(f"⏰ 已运行 {elapsed}s，还剩 {remaining}s，收到 {received_count} 条消息")
                        else:
                            print(f"⏰ 已运行 {elapsed}s，收到 {received_count} 条消息")
                        last_status_time = current_time
                    continue
                    
                except Exception as e:
                    print(f"❌ 接收错误: {e}")
                    self.stats['errors'] += 1
                    time.sleep(1)
            
            sock.close()
            
            runtime = time.time() - start_time
            print(f"\n📊 接收统计:")
            print(f"   运行时间: {runtime:.1f}秒")
            print(f"   接收消息: {received_count}条")
            print(f"   发送者数量: {len(senders)}个")
            print(f"   发送者列表: {list(senders)}")
            print(f"   接收错误: {self.stats['errors']}次")
            if received_count > 0:
                print(f"   平均速率: {received_count/runtime:.2f}条/秒")
            
            # 分析结果
            print(f"\n🎯 结果分析:")
            if received_count == 0:
                print("❌ 未接收到任何多播消息")
                print("可能原因:")
                print("   - 发送端未启动或未发送到正确地址")
                print("   - 网络防火墙阻止多播流量")
                print("   - 安全组未允许相应端口")
                print("   - 多播路由配置问题")
                print("   - 系统不支持多播")
            elif len(senders) == 1 and self.local_ip in senders:
                print("⚠️  只收到本机发送的消息（自环）")
                print("说明:")
                print("   - 本机多播功能正常")
                print("   - 但可能无法接收其他实例的消息")
                print("   - 需要检查跨实例网络配置")
            elif len(senders) > 1:
                print("✅ 接收到多个发送者的消息")
                print("说明:")
                print("   - 跨实例多播通信正常")
                print("   - 网络配置正确")
            else:
                print("✅ 接收到远程消息")
                print("说明:")
                print("   - 跨实例多播通信正常")
            
        except Exception as e:
            print(f"❌ 接收器启动失败: {e}")
    
    def combined_test(self, multicast_ip="224.1.1.1", port=12345, duration=30):
        """组合测试：同时发送和接收"""
        print(f"🔄 组合测试启动")
        print(f"   多播地址: {multicast_ip}:{port}")
        print(f"   测试时长: {duration}秒")
        print(f"   本机IP: {self.local_ip}")
        
        self.running = True
        
        # 启动接收器线程
        receiver_thread = threading.Thread(
            target=self.multicast_receiver,
            args=(multicast_ip, port, duration)
        )
        
        # 启动发送器线程
        sender_thread = threading.Thread(
            target=self.multicast_sender,
            args=(multicast_ip, port, 2, duration//2)  # 每2秒发送一次，发送duration//2次
        )
        
        print(f"🚀 启动接收器...")
        receiver_thread.start()
        
        time.sleep(2)  # 等待接收器启动
        
        print(f"🚀 启动发送器...")
        sender_thread.start()
        
        # 等待线程完成
        sender_thread.join()
        receiver_thread.join()
        
        print(f"\n🏁 组合测试完成")
        print(f"📊 总体统计:")
        print(f"   发送消息: {self.stats['sent']}条")
        print(f"   接收消息: {self.stats['received']}条")
        print(f"   错误次数: {self.stats['errors']}次")

def test_system_multicast_support():
    """测试系统多播支持"""
    print(f"🔍 测试系统多播支持...")
    
    # 检查网络接口
    try:
        import subprocess
        result = subprocess.run(['ip', 'link', 'show'], capture_output=True, text=True)
        multicast_interfaces = []
        for line in result.stdout.split('\n'):
            if 'MULTICAST' in line and 'UP' in line:
                interface_name = line.split(':')[1].strip().split('@')[0]
                multicast_interfaces.append(interface_name)
        
        print(f"✅ 支持多播的网络接口: {multicast_interfaces}")
        
    except Exception as e:
        print(f"❌ 检查网络接口失败: {e}")
    
    # 检查IGMP支持
    try:
        with open('/proc/net/igmp', 'r') as f:
            igmp_data = f.read()
        
        print(f"✅ IGMP支持正常")
        print(f"当前IGMP组 (前10行):")
        for i, line in enumerate(igmp_data.split('\n')[:10]):
            if line.strip():
                print(f"   {line}")
        
    except Exception as e:
        print(f"❌ 检查IGMP支持失败: {e}")
    
    # 检查多播路由
    try:
        result = subprocess.run(['ip', 'route', 'show'], capture_output=True, text=True)
        multicast_routes = [line for line in result.stdout.split('\n') if '224.' in line]
        
        if multicast_routes:
            print(f"✅ 发现多播路由:")
            for route in multicast_routes:
                print(f"   {route}")
        else:
            print(f"⚠️  未发现多播路由（这通常是正常的）")
        
    except Exception as e:
        print(f"❌ 检查多播路由失败: {e}")

def main():
    print("基础IP多播测试工具")
    print("=" * 40)
    
    if len(sys.argv) < 2:
        print("用法:")
        print("  系统检查:  sudo python3 basic_ip_multicast_test.py check")
        print("  发送模式:  sudo python3 basic_ip_multicast_test.py send [多播IP] [端口] [间隔] [数量]")
        print("  接收模式:  sudo python3 basic_ip_multicast_test.py receive [多播IP] [端口] [时长]")
        print("  组合测试:  sudo python3 basic_ip_multicast_test.py combined [多播IP] [端口] [时长]")
        print()
        print("示例:")
        print("  sudo python3 basic_ip_multicast_test.py check")
        print("  sudo python3 basic_ip_multicast_test.py send 224.1.1.1 12345 1 10")
        print("  sudo python3 basic_ip_multicast_test.py receive 224.1.1.1 12345 30")
        print("  sudo python3 basic_ip_multicast_test.py combined 224.1.1.1 12345 30")
        print()
        print("推荐测试步骤:")
        print("1. 在两台实例上都运行: sudo python3 basic_ip_multicast_test.py check")
        print("2. 在一台实例运行: sudo python3 basic_ip_multicast_test.py receive 224.1.1.1 12345 60")
        print("3. 在另一台实例运行: sudo python3 basic_ip_multicast_test.py send 224.1.1.1 12345 1 20")
        sys.exit(1)
    
    mode = sys.argv[1]
    tester = BasicMulticastTester()
    
    # 设置信号处理
    signal.signal(signal.SIGINT, tester.signal_handler)
    signal.signal(signal.SIGTERM, tester.signal_handler)
    
    if mode == "check":
        test_system_multicast_support()
        
    elif mode == "send":
        multicast_ip = sys.argv[2] if len(sys.argv) > 2 else "224.1.1.1"
        port = int(sys.argv[3]) if len(sys.argv) > 3 else 12345
        interval = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
        count = int(sys.argv[5]) if len(sys.argv) > 5 else None
        
        tester.running = True
        tester.multicast_sender(multicast_ip, port, interval, count)
        
    elif mode == "receive":
        multicast_ip = sys.argv[2] if len(sys.argv) > 2 else "224.1.1.1"
        port = int(sys.argv[3]) if len(sys.argv) > 3 else 12345
        duration = int(sys.argv[4]) if len(sys.argv) > 4 else None
        
        tester.running = True
        tester.multicast_receiver(multicast_ip, port, duration)
        
    elif mode == "combined":
        multicast_ip = sys.argv[2] if len(sys.argv) > 2 else "224.1.1.1"
        port = int(sys.argv[3]) if len(sys.argv) > 3 else 12345
        duration = int(sys.argv[4]) if len(sys.argv) > 4 else 30
        
        tester.combined_test(multicast_ip, port, duration)
        
    else:
        print(f"❌ 未知模式: {mode}")
        print("支持的模式: check, send, receive, combined")

if __name__ == "__main__":
    main()
