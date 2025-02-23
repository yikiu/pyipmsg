from PySide6.QtCore import QObject, Signal, QThread
import socket
import json
import time
import os
from datetime import datetime

class UDPListener(QThread):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.socket.bind(('0.0.0.0', 15000))
        self.running = True

    def run(self):
        while self.running:
            try:
                data, addr = self.socket.recvfrom(65535)
                self.callback(data, addr)
            except Exception as e:
                print(f"Error in UDP listener: {e}")
                time.sleep(0.1)

    def stop(self):
        self.running = False
        self.socket.close()

class UDPClient(QObject):
    message_received = Signal(str, str)  # 发送者, 消息
    user_online = Signal(str, str)  # IP, 用户名
    user_offline = Signal(str)  # IP
    file_request = Signal(str, str, int, str)  # sender_ip, filename, size, sender_name
    file_transfer_request = Signal(str, str)  # filename, target_ip
    file_accepted = Signal(str, str)  # filename, target_ip
    file_rejected = Signal(str, str)  # filename, sender_name
    file_transfer_complete = Signal(str, str, str)  # filename, operation, target_ip
    
    def __init__(self):
        super().__init__()
        self.broadcast_port = 15000
        self.username = "未命名用户"  # 默认用户名
        self.online_users = {}  # {ip: (username, last_seen)}
        self.file_server_port = 15001
        self.app_identifier = "PyIPMSG"  # 添加应用标识
        
        # 获取本机所有IP地址
        self.local_ips = self.get_local_ips()
        print(f"Local IPs: {self.local_ips}")  # 用于调试
        
        # 创建发送用的socket
        self.send_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.send_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.send_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # 创建并启动监听线程
        self.listener = UDPListener(self.handle_message)
        self.listener.start()
        
        # 加载保存的设置
        self.load_settings()
        
        # 定期发送在线状态
        self.start_heartbeat()
        
    def __del__(self):
        self.listener.stop()
        self.send_socket.close()
        
    def start_heartbeat(self):
        def heartbeat():
            while True:
                self.broadcast_presence()
                self.check_online_users()
                time.sleep(10)
        
        self.heartbeat_thread = QThread()
        self.heartbeat_thread.run = heartbeat
        self.heartbeat_thread.start()
        
    def check_online_users(self):
        current_time = datetime.now()
        offline_users = []
        for ip, (username, last_seen) in self.online_users.items():
            if (current_time - last_seen).seconds > 30:
                offline_users.append(ip)
        
        for ip in offline_users:
            del self.online_users[ip]
            self.user_offline.emit(ip)
    
    def handle_message(self, data, addr):
        try:
            msg = json.loads(data.decode())
            sender_ip = addr[0]
            
            # 检查是否是来自同一应用的消息
            if msg.get('app') != self.app_identifier:
                return
                
            # 如果是本机的其他IP地址发来的消息，忽略它
            if sender_ip in self.local_ips:
                return
                
            if msg['type'] == 'message':
                self.message_received.emit(sender_ip, msg['content'])
            
            elif msg['type'] == 'presence':
                self.online_users[sender_ip] = (msg['username'], datetime.now())
                self.user_online.emit(sender_ip, msg['username'])
            
            elif msg['type'] == 'file_request':
                self.file_request.emit(
                    sender_ip,
                    msg['filename'],
                    int(msg['size']),  # 确保是整数
                    msg.get('sender', '未知用户')
                )
                
            elif msg['type'] == 'file_response':
                if msg['accepted']:
                    self.file_accepted.emit(msg['filename'], sender_ip)
                else:
                    # 获取拒绝者的用户名
                    sender_name = self.online_users.get(sender_ip, ('未知用户', None))[0]
                    self.file_rejected.emit(msg['filename'], sender_name)
            
        except Exception as e:
            print(f"Error handling message: {e}")
    
    def send_message(self, message, target_ip):
        data = {
            'app': self.app_identifier,
            'type': 'message',
            'content': message
        }
        self.send_socket.sendto(json.dumps(data).encode(), (target_ip, self.broadcast_port))
    
    def broadcast_presence(self):
        data = {
            'app': self.app_identifier,
            'type': 'presence',
            'status': 'online',
            'username': self.username
        }
        try:
            # 获取所有网络接口的广播地址
            import netifaces
            for interface in netifaces.interfaces():
                addrs = netifaces.ifaddresses(interface)
                if netifaces.AF_INET in addrs:
                    for addr in addrs[netifaces.AF_INET]:
                        if 'broadcast' in addr:
                            broadcast_addr = addr['broadcast']
                            self.send_socket.sendto(
                                json.dumps(data).encode(),
                                (broadcast_addr, self.broadcast_port)
                            )
        except:
            # 如果获取网络接口失败，使用默认广播地址
            self.send_socket.sendto(
                json.dumps(data).encode(),
                ('255.255.255.255', self.broadcast_port)
            )
    
    def send_file_request(self, filename, target_ip):
        file_size = os.path.getsize(filename)
        data = {
            'app': self.app_identifier,
            'type': 'file_request',
            'filename': os.path.basename(filename),
            'size': file_size,
            'port': self.file_server_port,
            'sender': self.username
        }
        # 先发送请求，不要立即触发传输
        self.send_socket.sendto(json.dumps(data).encode(), (target_ip, self.broadcast_port))

    def send_file_response(self, filename, target_ip, accepted):
        data = {
            'app': self.app_identifier,
            'type': 'file_response',
            'filename': filename,
            'accepted': accepted
        }
        self.send_socket.sendto(json.dumps(data).encode(), (target_ip, self.broadcast_port))

    def load_settings(self):
        try:
            with open('settings.json', 'r', encoding='utf-8') as f:
                settings = json.load(f)
                self.username = settings.get('username', self.username)
        except:
            pass
            
    def save_settings(self):
        try:
            with open('settings.json', 'w', encoding='utf-8') as f:
                json.dump({'username': self.username}, f, ensure_ascii=False)
        except:
            pass

    def set_username(self, username):
        self.username = username
        self.save_settings()  # 保存设置
        self.broadcast_presence()  # 立即广播新用户名 

    def get_local_ips(self):
        local_ips = set()
        try:
            import netifaces
            for interface in netifaces.interfaces():
                addrs = netifaces.ifaddresses(interface)
                if netifaces.AF_INET in addrs:
                    for addr in addrs[netifaces.AF_INET]:
                        if 'addr' in addr and addr['addr'] != '127.0.0.1':
                            local_ips.add(addr['addr'])
        except:
            import socket
            hostname = socket.gethostname()
            local_ips.add(socket.gethostbyname(hostname))
        return local_ips 