#!/usr/bin/env python3
"""
GOOSE桥接服务性能测试工具
用于压力测试和性能评估
"""

import time
import threading
import socket
import struct
import statistics
import argparse
from datetime import datetime

class GOOSEBridgeBenchmark:
    """GOOSE桥接性能测试器"""
    
    def __init__(self):
        self.results = {
            'sent_packets': 0,
            'received_packets': 0,
            'lost_packets': 0,
            'latencies': [],
            'errors': 0,
            'start_time': 0,
            'end_time': 0
        }
        self.running = False
    
    def generate_test_goose_packet(self, seq_num):
        """生成测试GOOSE数据包"""
        # 模拟libiec61850的GOOSE数据包格式
        src_mac = bytes([0x02, 0x00, 0x00, 0x00, 0x00, 0x01])  # 测试MAC
        timestamp = struct.pack('!Q', int(time.time() * 1000000))
        vlan_info = struct.pack('!HH', 1, 100)  # VLAN标志和ID
        
        # 简化的GOOSE载荷
        goose_payload = struct.pack('!HH', 1000, 32) + struct.pack('!I', seq_num) + b'\x00' * 24
        
        return src_mac + timestamp + vlan_info + goose_payload
    
    def sender_thread(self, target_ip, target_port, rate, duration, packet_size):
        """发送线程"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 10)
            
            interval = 1.0 / rate if rate > 0 else 0
            seq_num = 0
            
            start_time = time.time()
            next_send_time = start_time
            
            while self.running and (time.time() - start_time) < duration:
                current_time = time.time()
                
                if current_time >= next_send_time:
                    # 生成测试数据包
                    packet = self.generate_test_goose_packet(seq_num)
                    
                    # 调整到指定大小
                    if len(packet) < packet_size:
                        packet += b'\x00' * (packet_size - len(packet))
                    elif len(packet) > packet_size:
                        packet = packet[:packet_size]
                    
                    try:
                        sock.sendto(packet, (target_ip, target_port))
                        self.results['sent_packets'] += 1
                        seq_num += 1
                        
                        next_send_time += interval
                        
                    except Exception as e:
                        self.results['errors'] += 1
                        print(f"发送错误: {e}")
                
                # 精确控制发送速率
                if interval > 0:
                    sleep_time = next_send_time - time.time()
                    if sleep_time > 0:
                        time.sleep(min(sleep_time, 0.001))
            
            sock.close()
            
        except Exception as e:
            print(f"发送线程错误: {e}")
            self.results['errors'] += 1
    
    def receiver_thread(self, listen_port, duration):
        """接收线程"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('', listen_port))
            
            # 加入多播组
            mreq = struct.pack('4sl', socket.inet_aton('224.0.1.100'), socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            sock.settimeout(1.0)
            
            start_time = time.time()
            
            while self.running and (time.time() - start_time) < duration + 5:  # 额外等待5秒
                try:
                    data, addr = sock.recvfrom(2048)
                    receive_time = time.time()
                    
                    # 解析时间戳计算延迟
                    if len(data) >= 14:
                        try:
                            send_timestamp = struct.unpack('!Q', data[6:14])[0]
                            send_time = send_timestamp / 1000000.0
                            latency = (receive_time - send_time) * 1000  # 毫秒
                            
                            if 0 <= latency <= 10000:  # 合理的延迟范围
                                self.results['latencies'].append(latency)
                            
                        except:
                            pass
                    
                    self.results['received_packets'] += 1
                    
                except socket.timeout:
                    continue
                except Exception as e:
                    self.results['errors'] += 1
            
            sock.close()
            
        except Exception as e:
            print(f"接收线程错误: {e}")
            self.results['errors'] += 1
    
    def run_throughput_test(self, target_ip='224.0.1.100', target_port=61850, 
                           listen_port=61851, rate=100, duration=30, packet_size=200):
        """运行吞吐量测试"""
        print(f"🚀 开始吞吐量测试")
        print(f"   目标: {target_ip}:{target_port}")
        print(f"   监听: {listen_port}")
        print(f"   发送速率: {rate} pps")
        print(f"   测试时长: {duration} 秒")
        print(f"   数据包大小: {packet_size} 字节")
        print("-" * 50)
        
        # 重置结果
        self.results = {
            'sent_packets': 0,
            'received_packets': 0,
            'lost_packets': 0,
            'latencies': [],
            'errors': 0,
            'start_time': time.time(),
            'end_time': 0
        }
        
        self.running = True
        
        # 启动线程
        sender = threading.Thread(target=self.sender_thread, 
                                args=(target_ip, target_port, rate, duration, packet_size))
        receiver = threading.Thread(target=self.receiver_thread, 
                                   args=(listen_port, duration))
        
        sender.start()
        receiver.start()
        
        # 实时显示进度
        start_time = time.time()
        try:
            while sender.is_alive() or receiver.is_alive():
                time.sleep(1)
                elapsed = time.time() - start_time
                
                if elapsed <= duration:
                    sent = self.results['sent_packets']
                    received = self.results['received_packets']
                    current_rate = sent / elapsed if elapsed > 0 else 0
                    
                    print(f"\r⏱️  进度: {elapsed:.1f}s | "
                          f"发送: {sent} | 接收: {received} | "
                          f"速率: {current_rate:.1f} pps", end='', flush=True)
        
        except KeyboardInterrupt:
            print("\n测试被中断")
            self.running = False
        
        # 等待线程结束
        sender.join(timeout=5)
        receiver.join(timeout=5)
        
        self.results['end_time'] = time.time()
        self.running = False
        
        print("\n" + "-" * 50)
        self.print_results()
    
    def run_latency_test(self, target_ip='224.0.1.100', target_port=61850, 
                        listen_port=61851, count=1000, interval=0.01):
        """运行延迟测试"""
        print(f"🎯 开始延迟测试")
        print(f"   目标: {target_ip}:{target_port}")
        print(f"   监听: {listen_port}")
        print(f"   数据包数量: {count}")
        print(f"   发送间隔: {interval} 秒")
        print("-" * 50)
        
        duration = count * interval + 10  # 额外等待时间
        
        # 重置结果
        self.results = {
            'sent_packets': 0,
            'received_packets': 0,
            'lost_packets': 0,
            'latencies': [],
            'errors': 0,
            'start_time': time.time(),
            'end_time': 0
        }
        
        self.running = True
        
        # 启动接收线程
        receiver = threading.Thread(target=self.receiver_thread, 
                                   args=(listen_port, duration))
        receiver.start()
        
        # 等待接收器启动
        time.sleep(1)
        
        # 发送测试数据包
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 10)
            
            for i in range(count):
                if not self.running:
                    break
                
                packet = self.generate_test_goose_packet(i)
                sock.sendto(packet, (target_ip, target_port))
                self.results['sent_packets'] += 1
                
                if (i + 1) % 100 == 0:
                    print(f"📤 已发送: {i + 1}/{count}")
                
                time.sleep(interval)
            
            sock.close()
            
        except KeyboardInterrupt:
            print("\n测试被中断")
        except Exception as e:
            print(f"发送错误: {e}")
            self.results['errors'] += 1
        
        # 等待接收完成
        print("⏳ 等待接收完成...")
        receiver.join(timeout=15)
        
        self.results['end_time'] = time.time()
        self.running = False
        
        print("-" * 50)
        self.print_results()
    
    def print_results(self):
        """打印测试结果"""
        duration = self.results['end_time'] - self.results['start_time']
        sent = self.results['sent_packets']
        received = self.results['received_packets']
        lost = sent - received
        loss_rate = (lost / sent * 100) if sent > 0 else 0
        
        print(f"📊 测试结果:")
        print(f"   测试时长: {duration:.2f} 秒")
        print(f"   发送数据包: {sent}")
        print(f"   接收数据包: {received}")
        print(f"   丢失数据包: {lost}")
        print(f"   丢包率: {loss_rate:.2f}%")
        print(f"   错误次数: {self.results['errors']}")
        
        if sent > 0:
            avg_send_rate = sent / duration
            print(f"   平均发送速率: {avg_send_rate:.2f} pps")
        
        if received > 0:
            avg_recv_rate = received / duration
            print(f"   平均接收速率: {avg_recv_rate:.2f} pps")
        
        # 延迟统计
        latencies = self.results['latencies']
        if latencies:
            print(f"\n📈 延迟统计 ({len(latencies)} 个样本):")
            print(f"   最小延迟: {min(latencies):.3f} ms")
            print(f"   最大延迟: {max(latencies):.3f} ms")
            print(f"   平均延迟: {statistics.mean(latencies):.3f} ms")
            print(f"   中位延迟: {statistics.median(latencies):.3f} ms")
            
            if len(latencies) > 1:
                print(f"   延迟标准差: {statistics.stdev(latencies):.3f} ms")
            
            # 延迟分布
            p95 = sorted(latencies)[int(len(latencies) * 0.95)]
            p99 = sorted(latencies)[int(len(latencies) * 0.99)]
            print(f"   95%延迟: {p95:.3f} ms")
            print(f"   99%延迟: {p99:.3f} ms")
        
        # 性能评估
        print(f"\n🎯 性能评估:")
        if loss_rate < 0.1:
            print("   丢包率: 🟢 优秀")
        elif loss_rate < 1.0:
            print("   丢包率: 🟡 良好")
        else:
            print("   丢包率: 🔴 需要优化")
        
        if latencies:
            avg_latency = statistics.mean(latencies)
            if avg_latency < 1.0:
                print("   延迟: 🟢 优秀")
            elif avg_latency < 5.0:
                print("   延迟: 🟡 良好")
            else:
                print("   延迟: 🔴 需要优化")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='GOOSE桥接服务性能测试工具')
    
    subparsers = parser.add_subparsers(dest='test_type', help='测试类型')
    
    # 吞吐量测试
    throughput_parser = subparsers.add_parser('throughput', help='吞吐量测试')
    throughput_parser.add_argument('--target-ip', default='224.0.1.100', help='目标IP')
    throughput_parser.add_argument('--target-port', type=int, default=61850, help='目标端口')
    throughput_parser.add_argument('--listen-port', type=int, default=61851, help='监听端口')
    throughput_parser.add_argument('--rate', type=int, default=100, help='发送速率(pps)')
    throughput_parser.add_argument('--duration', type=int, default=30, help='测试时长(秒)')
    throughput_parser.add_argument('--packet-size', type=int, default=200, help='数据包大小')
    
    # 延迟测试
    latency_parser = subparsers.add_parser('latency', help='延迟测试')
    latency_parser.add_argument('--target-ip', default='224.0.1.100', help='目标IP')
    latency_parser.add_argument('--target-port', type=int, default=61850, help='目标端口')
    latency_parser.add_argument('--listen-port', type=int, default=61851, help='监听端口')
    latency_parser.add_argument('--count', type=int, default=1000, help='数据包数量')
    latency_parser.add_argument('--interval', type=float, default=0.01, help='发送间隔(秒)')
    
    args = parser.parse_args()
    
    if not args.test_type:
        parser.print_help()
        return
    
    benchmark = GOOSEBridgeBenchmark()
    
    if args.test_type == 'throughput':
        benchmark.run_throughput_test(
            target_ip=args.target_ip,
            target_port=args.target_port,
            listen_port=args.listen_port,
            rate=args.rate,
            duration=args.duration,
            packet_size=args.packet_size
        )
    elif args.test_type == 'latency':
        benchmark.run_latency_test(
            target_ip=args.target_ip,
            target_port=args.target_port,
            listen_port=args.listen_port,
            count=args.count,
            interval=args.interval
        )

if __name__ == "__main__":
    main()
