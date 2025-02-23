from PySide6.QtCore import QObject, Signal, QThread
import socket
import json
import os
import hashlib
from dataclasses import dataclass
from enum import Enum

class TransferStatus(Enum):
    WAITING = "等待中"
    TRANSFERRING = "传输中"
    COMPLETED = "已完成"
    CANCELLED = "已取消"
    ERROR = "传输错误"

@dataclass
class TransferInfo:
    filename: str
    size: int
    md5: str
    operation: str
    status: TransferStatus = TransferStatus.WAITING

class FileTransferServer(QObject):
    transfer_progress = Signal(str, str, int)  # filename, operation, progress
    transfer_complete = Signal(str, str)  # filename, operation
    transfer_error = Signal(str, str, str)  # filename, operation, error_message
    transfer_status = Signal(str, TransferStatus)  # filename, status
    
    def __init__(self):
        super().__init__()
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(('0.0.0.0', 15001))
        self.server.listen(5)
        self.active_transfers = {}  # {filename: TransferInfo}
        self.cancel_flags = set()  # 存储需要取消的传输文件名
        self.save_paths = {}  # {filename: save_path}
        
        # 启动接收服务器线程
        self.accept_thread = None
        self.running = True
        
    def __del__(self):
        self.running = False
        if self.server:
            self.server.close()
            
    def start_receiving(self):
        def accept_connections():
            while self.running:
                try:
                    client, addr = self.server.accept()
                    # 为每个客户端创建新线程处理
                    client_thread = QThread()
                    client_thread.run = lambda: self.handle_client(client, addr)
                    client_thread.start()
                except Exception as e:
                    if self.running:  # 只在非正常关闭时打印错误
                        print(f"Error accepting connection: {e}")
                    break
                    
        self.accept_thread = QThread()
        self.accept_thread.run = accept_connections
        self.accept_thread.start()
        
    def calculate_md5(self, filename):
        hash_md5 = hashlib.md5()
        with open(filename, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
        
    def send_file(self, filename, target_ip):
        try:
            print(f"Starting to send file: {filename} to {target_ip}")  # 调试信息
            # 准备传输信息
            file_size = os.path.getsize(filename)
            md5 = self.calculate_md5(filename)
            base_filename = os.path.basename(filename)
            
            transfer_info = TransferInfo(
                filename=base_filename,
                size=file_size,
                md5=md5,
                operation='send'
            )
            self.active_transfers[base_filename] = transfer_info
            
            def transfer():
                try:
                    print(f"Connecting to {target_ip}:15001")  # 调试信息
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.settimeout(30)
                        s.connect((target_ip, 15001))
                        
                        # 发送文件信息
                        info = {
                            'filename': base_filename,
                            'size': file_size,
                            'md5': md5
                        }
                        s.send(json.dumps(info).encode())
                        
                        # 等待确认
                        response = json.loads(s.recv(1024).decode())
                        if response.get('status') == 'rejected':
                            raise Exception("接收方拒绝接收文件")
                        elif response.get('status') != 'ready':
                            raise Exception("接收方未准备好")
                        
                        transfer_info.status = TransferStatus.TRANSFERRING
                        self.transfer_status.emit(base_filename, TransferStatus.TRANSFERRING)
                        
                        # 发送文件内容
                        sent = 0
                        with open(filename, 'rb') as f:
                            while sent < file_size:
                                if base_filename in self.cancel_flags:
                                    raise Exception("传输已取消")
                                    
                                chunk = f.read(8192)
                                if not chunk:
                                    break
                                s.send(chunk)
                                sent += len(chunk)
                                progress = int((sent / file_size) * 100)
                                self.transfer_progress.emit(base_filename, 'send', progress)
                        
                        # 等待接收方确认MD5
                        verify_result = json.loads(s.recv(1024).decode())
                        if verify_result.get('md5_match'):
                            transfer_info.status = TransferStatus.COMPLETED
                            self.transfer_status.emit(base_filename, TransferStatus.COMPLETED)
                            self.transfer_complete.emit(base_filename, 'send')
                        else:
                            raise Exception("文件校验失败")
                            
                except Exception as e:
                    print(f"Error in transfer thread: {e}")  # 调试信息
                    if base_filename in self.cancel_flags:
                        transfer_info.status = TransferStatus.CANCELLED
                        self.transfer_status.emit(base_filename, TransferStatus.CANCELLED)
                    else:
                        transfer_info.status = TransferStatus.ERROR
                        self.transfer_status.emit(base_filename, TransferStatus.ERROR)
                        self.transfer_error.emit(base_filename, 'send', str(e))
                finally:
                    if base_filename in self.cancel_flags:
                        self.cancel_flags.remove(base_filename)
                    
            self.transfer_thread = QThread()
            self.transfer_thread.run = transfer
            self.transfer_thread.start()
            
        except Exception as e:
            print(f"Error in send_file: {e}")  # 调试信息
            self.transfer_error.emit(base_filename, 'send', str(e))
    
    def set_save_path(self, filename, save_path):
        self.save_paths[filename] = save_path

    def handle_client(self, client, addr):
        try:
            # 接收文件信息
            info = json.loads(client.recv(1024).decode())
            filename = info['filename']
            file_size = info['size']
            expected_md5 = info['md5']
            
            # 获取保存路径，如果没有设置则拒绝接收
            if filename not in self.save_paths:
                client.send(json.dumps({'status': 'rejected'}).encode())
                return
            
            save_path = self.save_paths[filename]
            transfer_info = TransferInfo(
                filename=filename,
                size=file_size,
                md5=expected_md5,
                operation='receive'
            )
            self.active_transfers[filename] = transfer_info
            
            # 发送准备就绪确认
            client.send(json.dumps({'status': 'ready'}).encode())
            
            transfer_info.status = TransferStatus.TRANSFERRING
            self.transfer_status.emit(filename, TransferStatus.TRANSFERRING)
            
            # 接收文件内容
            received = 0
            hash_md5 = hashlib.md5()
            
            with open(save_path, 'wb') as f:  # 使用用户指定的保存路径
                while received < file_size:
                    if filename in self.cancel_flags:
                        raise Exception("传输已取消")
                        
                    chunk = client.recv(8192)
                    if not chunk:
                        break
                    
                    hash_md5.update(chunk)
                    f.write(chunk)
                    received += len(chunk)
                    progress = int((received / file_size) * 100)
                    self.transfer_progress.emit(filename, 'receive', progress)
            
            # 验证MD5
            actual_md5 = hash_md5.hexdigest()
            md5_match = actual_md5 == expected_md5
            client.send(json.dumps({'md5_match': md5_match}).encode())
            
            if md5_match:
                transfer_info.status = TransferStatus.COMPLETED
                self.transfer_status.emit(filename, TransferStatus.COMPLETED)
                self.transfer_complete.emit(filename, 'receive')
            else:
                raise Exception("文件校验失败")
                
        except Exception as e:
            if filename in self.cancel_flags:
                transfer_info.status = TransferStatus.CANCELLED
                self.transfer_status.emit(filename, TransferStatus.CANCELLED)
            else:
                transfer_info.status = TransferStatus.ERROR
                self.transfer_status.emit(filename, TransferStatus.ERROR)
                self.transfer_error.emit(filename, 'receive', str(e))
            
            # 清理未完成的文件
            try:
                if os.path.exists(save_path):
                    os.remove(save_path)
            except:
                pass
                
        finally:
            if filename in self.save_paths:
                del self.save_paths[filename]  # 清理保存路径
            if filename in self.cancel_flags:
                self.cancel_flags.remove(filename)
            client.close()
    
    def cancel_transfer(self, filename):
        self.cancel_flags.add(filename) 