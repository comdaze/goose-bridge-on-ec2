#!/usr/bin/env python3
"""
IGMP模式多播测试
专门针对AWS TGW IGMP多播域的测试
"""

import socket
import struct
import threading
import time
import sys
import os
import signal

class IGMPMulticastTester:
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
    
    def igmp_multicast_sender(self, multicast_ip="224.0.1.100", port=61850, interval=2, count=20):
        """IGMP多播发送器 - 增强版"""
        print(f"📤 IGMP多播发送器启动")
        print(f"   目标: {multicast_ip}:{port}")
        print(f"   本机IP: {self.local_ip}")
        print(f"   发送间隔: {interval}秒")
        print(f"   发送数量: {count}条")
        
        try:
            # 创建发送套接字
            send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            
            # 设置多播TTL (重要!)
            send_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 10)  # 增加TTL
            
            # 设置多播接口 (可选，但推荐)
            send_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(self.local_ip))
            
            # 创建接收套接字用于IGMP注册 (关键!)
            recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            recv_sock.bind(('', port + 1))  # 绑定到不同端口避免冲突
            
            # 加入多播组 - 这会发送IGMP Join消息
            mreq = struct.pack('4sl', socket.inet_aton(multicast_ip), socket.INADDR_ANY)
            recv_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            
            print(f"✅ 发送套接字创建成功")
            print(f"✅ IGMP组加入成功 - 已向TGW注册为多播源")
            
            time.sleep(3)  # 等待IGMP注册生效
            
            sent_count = 0
            start_time = time.time()
            
            while self.running and sent_count < count:
                try:
                    # 创建测试消息
                    timestamp = int(time.time())
                    message = f"IGMP_MULTICAST_{sent_count+1}_FROM_{self.local_ip}_TIME_{timestamp}"
                    
                    # 发送多播消息
                    send_sock.sendto(message.encode('utf-8'), (multicast_ip, port))
                    
                    sent_count += 1
                    self.stats['sent'] = sent_count
                    
                    current_time = time.strftime("%H:%M:%S")
                    print(f"📤 [{current_time}] 发送 #{sent_count}: {message}")
                    
                    time.sleep(interval)
                    
                except Exception as e:
                    print(f"❌ 发送错误: {e}")
                    self.stats['errors'] += 1
                    time.sleep(1)
            
            # 保持IGMP成员身份一段时间
            print(f"📡 保持IGMP成员身份10秒...")
            time.sleep(10)
            
            send_sock.close()
            recv_sock.close()
            
            runtime = time.time() - start_time
            print(f"\n📊 IGMP发送统计:")
            print(f"   运行时间: {runtime:.1f}秒")
            print(f"   发送消息: {sent_count}条")
            print(f"   发送错误: {self.stats['errors']}次")
            
        except Exception as e:
            print(f"❌ IGMP发送器启动失败: {e}")
    
    def igmp_multicast_receiver(self, multicast_ip="224.0.1.100", port=61850, duration=60):
        """IGMP多播接收器 - 增强版"""
        print(f"📨 IGMP多播接收器启动")
        print(f"   监听: {multicast_ip}:{port}")
        print(f"   本机IP: {self.local_ip}")
        print(f"   接收时长: {duration}秒")
        
        try:
            # 创建接收套接字
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            
            # 允许地址重用
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # 绑定到指定端口
            sock.bind(('', port))
            print(f"✅ 绑定端口 {port} 成功")
            
            # 加入多播组 - 发送IGMP Join消息到TGW
            mreq = struct.pack('4sl', socket.inet_aton(multicast_ip), socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            print(f"✅ 加入IGMP多播组 {multicast_ip} 成功")
            
            # 设置接收缓冲区
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
            
            # 设置接收超时
            sock.settimeout(3.0)
            
            print(f"⏰ 等待5秒让IGMP注册生效...")
            time.sleep(5)
            
            received_count = 0
            start_time = time.time()
            senders = set()
            last_status_time = start_time
            
            print(f"🎧 开始监听IGMP多播消息...")
            
            while self.running and (time.time() - start_time) < duration:
                try:
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
                        print(f"📨 [{current_time}] 接收 #{received_count}: {message} (来自 {addr[0]}) ⭐")
                    
                except socket.timeout:
                    # 定期显示状态
                    current_time = time.time()
                    if current_time - last_status_time > 15:  # 每15秒显示一次状态
                        elapsed = int(current_time - start_time)
                        remaining = duration - elapsed
                        print(f"⏰ 已运行 {elapsed}s，还剩 {remaining}s，收到 {received_count} 条消息")
                        print(f"   发送者: {list(senders)}")
                        last_status_time = current_time
                    continue
                    
                except Exception as e:
                    print(f"❌ 接收错误: {e}")
                    self.stats['errors'] += 1
                    time.sleep(1)
            
            # 保持IGMP成员身份
            print(f"📡 保持IGMP成员身份5秒...")
            time.sleep(5)
            
            sock.close()
            
            runtime = time.time() - start_time
            print(f"\n📊 IGMP接收统计:")
            print(f"   运行时间: {runtime:.1f}秒")
            print(f"   接收消息: {received_count}条")
            print(f"   发送者数量: {len(senders)}个")
            print(f"   发送者列表: {list(senders)}")
            print(f"   接收错误: {self.stats['errors']}次")
            
            # 结果分析
            print(f"\n🎯 IGMP多播结果分析:")
            if received_count == 0:
                print("❌ 未接收到任何IGMP多播消息")
                print("可能原因:")
                print("   - TGW多播域IGMP配置问题")
                print("   - 发送端未正确注册为IGMP源")
                print("   - 网络接口未正确关联到多播域")
                print("   - IGMP协议被防火墙阻止")
            elif len(senders) == 1 and self.local_ip in senders:
                print("⚠️  只收到本机IGMP消息（自环）")
                print("说明:")
                print("   - 本机IGMP功能正常")
                print("   - TGW多播域可能未正确配置跨实例路由")
            else:
                remote_senders = [ip for ip in senders if ip != self.local_ip]
                if remote_senders:
                    print("✅ 成功接收到远程IGMP多播消息！")
                    print(f"   远程发送者: {remote_senders}")
                    print("说明:")
                    print("   - AWS TGW IGMP多播工作正常")
                    print("   - 跨实例多播通信成功")
                else:
                    print("⚠️  只收到本机消息")
            
        except Exception as e:
            print(f"❌ IGMP接收器启动失败: {e}")

def main():
    print("AWS TGW IGMP多播测试工具")
    print("=" * 40)
    
    if len(sys.argv) < 2:
        print("用法:")
        print("  发送模式:  sudo python3 igmp_multicast_test.py send [多播IP] [端口] [间隔] [数量]")
        print("  接收模式:  sudo python3 igmp_multicast_test.py receive [多播IP] [端口] [时长]")
        print()
        print("示例:")
        print("  sudo python3 igmp_multicast_test.py send 224.0.1.100 61850 2 15")
        print("  sudo python3 igmp_multicast_test.py receive 224.0.1.100 61850 60")
        print()
        print("推荐测试步骤:")
        print("1. 在接收端实例运行: sudo python3 igmp_multicast_test.py receive 224.0.1.100 61850 60")
        print("2. 在发送端实例运行: sudo python3 igmp_multicast_test.py send 224.0.1.100 61850 2 15")
        print("3. 观察接收端是否收到远程消息")
        sys.exit(1)
    
    mode = sys.argv[1]
    tester = IGMPMulticastTester()
    
    # 设置信号处理
    signal.signal(signal.SIGINT, tester.signal_handler)
    signal.signal(signal.SIGTERM, tester.signal_handler)
    
    if mode == "send":
        multicast_ip = sys.argv[2] if len(sys.argv) > 2 else "224.0.1.100"
        port = int(sys.argv[3]) if len(sys.argv) > 3 else 61850
        interval = float(sys.argv[4]) if len(sys.argv) > 4 else 2.0
        count = int(sys.argv[5]) if len(sys.argv) > 5 else 15
        
        tester.running = True
        tester.igmp_multicast_sender(multicast_ip, port, interval, count)
        
    elif mode == "receive":
        multicast_ip = sys.argv[2] if len(sys.argv) > 2 else "224.0.1.100"
        port = int(sys.argv[3]) if len(sys.argv) > 3 else 61850
        duration = int(sys.argv[4]) if len(sys.argv) > 4 else 60
        
        tester.running = True
        tester.igmp_multicast_receiver(multicast_ip, port, duration)
        
    else:
        print(f"❌ 未知模式: {mode}")
        print("支持的模式: send, receive")

if __name__ == "__main__":
    main()
