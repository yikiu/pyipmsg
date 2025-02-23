from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QTextEdit, QLineEdit, 
                             QPushButton, QListWidget, QListWidgetItem,
                             QFileDialog, QMessageBox, QProgressBar, QLabel, QMenuBar, QMenu, QSystemTrayIcon)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
import os
from network.file_server import TransferStatus
from .settings_dialog import SettingsDialog
import logging
from datetime import datetime
import json

class UserListItem(QListWidgetItem):
    def __init__(self, username, ip):
        super().__init__(username)
        self.ip = ip

class TransferWidget(QWidget):
    def __init__(self, filename, operation, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        
        self.filename = filename
        self.operation = operation
        
        self.label = QLabel(f"{'发送' if operation == 'send' else '接收'} {filename}")
        self.progress = QProgressBar()
        self.progress.setMinimum(0)
        self.progress.setMaximum(100)
        
        self.status_label = QLabel(TransferStatus.WAITING.value)
        self.cancel_button = QPushButton("取消")
        
        layout.addWidget(self.label)
        layout.addWidget(self.progress)
        layout.addWidget(self.status_label)
        layout.addWidget(self.cancel_button)
        
    def update_progress(self, value):
        self.progress.setValue(value)
        
    def update_status(self, status: TransferStatus):
        self.status_label.setText(status.value)
        if status in [TransferStatus.COMPLETED, TransferStatus.CANCELLED, TransferStatus.ERROR]:
            self.cancel_button.setEnabled(False)

class MainWindow(QMainWindow):
    send_message_signal = Signal(str, str)  # 消息, 目标IP
    send_file_signal = Signal(str, str)  # 文件路径, 目标IP
    cancel_transfer_signal = Signal(str)  # filename
    settings_changed_signal = Signal(str)  # username
    refresh_signal = Signal()  # 新增刷新信号
    file_response_signal = Signal(str, str, bool)  # filename, target_ip, accepted
    set_save_path_signal = Signal(str, str)  # filename, save_path
    file_transfer_request = Signal(str, str)  # filename, target_ip
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Python IPMSG")
        self.setMinimumSize(800, 600)
        
        # 创建中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建主布局
        layout = QHBoxLayout(central_widget)
        
        # 左侧用户列表
        users_layout = QVBoxLayout()
        self.user_list = QListWidget()
        self.user_list.setMaximumWidth(200)
        self.user_list.itemClicked.connect(self.user_selected)
        users_layout.addWidget(self.user_list)
        
        # 在用户列表上方添加刷新按钮
        refresh_button = QPushButton("刷新用户列表")
        refresh_button.clicked.connect(self.refresh_users)
        users_layout.insertWidget(0, refresh_button)
        
        # 添加文件传输按钮
        self.file_button = QPushButton("发送文件")
        self.file_button.setEnabled(False)
        self.file_button.clicked.connect(self.send_file)
        users_layout.addWidget(self.file_button)
        
        layout.addLayout(users_layout)
        
        # 右侧聊天区域
        chat_layout = QVBoxLayout()
        
        # 聊天记录显示区域
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        chat_layout.addWidget(self.chat_display)
        
        # 添加文件传输进度区域
        self.transfer_layout = QVBoxLayout()
        self.transfers = {}  # {filename: TransferWidget}
        chat_layout.addLayout(self.transfer_layout)
        
        # 消息输入区域
        input_layout = QHBoxLayout()
        self.message_input = QLineEdit()
        self.send_button = QPushButton("发送")
        self.send_button.setEnabled(False)
        input_layout.addWidget(self.message_input)
        input_layout.addWidget(self.send_button)
        
        chat_layout.addLayout(input_layout)
        layout.addLayout(chat_layout)
        
        # 连接信号
        self.send_button.clicked.connect(self.send_message)
        self.message_input.returnPressed.connect(self.send_message)
        
        self.current_chat_user = None
        
        # 在现有初始化代码前添加
        self.setup_logging()
        
        # 在现有初始化代码中添加
        self.show_ip = True
        self.setup_menu()
        
        # 加载保存的设置
        self.load_settings()
        
        # 添加拖放支持
        self.setAcceptDrops(True)
        
        # 添加聊天记录存储
        self.chat_history = {}  # {ip: [messages]}
        self.load_chat_history()
        
        # 添加系统托盘图标
        self.tray_icon = QSystemTrayIcon(self)
        icon_pixmap = QPixmap(16, 16)
        icon_pixmap.fill(Qt.blue)  # 创建一个蓝色图标
        self.tray_icon.setIcon(QIcon(icon_pixmap))
        self.tray_icon.show()
        
    def setup_logging(self):
        self.logger = logging.getLogger('ipmsg')
        self.logger.setLevel(logging.INFO)
        
        # 文件处理器
        fh = logging.FileHandler('ipmsg.log', encoding='utf-8')
        fh.setLevel(logging.INFO)
        
        # 格式化器
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        
        self.logger.addHandler(fh)
        
    def setup_menu(self):
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu("文件")
        settings_action = file_menu.addAction("设置")
        settings_action.triggered.connect(self.show_settings)
        file_menu.addSeparator()
        exit_action = file_menu.addAction("退出")
        exit_action.triggered.connect(self.close)
        
    def show_settings(self):
        dialog = SettingsDialog(
            current_username=self.windowTitle().replace(" - Python IPMSG", ""),
            show_ip=self.show_ip,
            parent=self
        )
        dialog.settings_changed.connect(self.handle_settings_changed)
        dialog.exec()
        
    def load_settings(self):
        try:
            with open('settings.json', 'r', encoding='utf-8') as f:
                settings = json.load(f)
                username = settings.get('username', "未命名用户")
                self.show_ip = settings.get('show_ip', True)
                self.setWindowTitle(f"{username} - Python IPMSG")
        except:
            pass
            
    def save_settings(self):
        try:
            with open('settings.json', 'w', encoding='utf-8') as f:
                json.dump({
                    'username': self.windowTitle().replace(" - Python IPMSG", ""),
                    'show_ip': self.show_ip
                }, f, ensure_ascii=False)
        except:
            pass
            
    def refresh_users(self):
        # 清空用户列表
        self.user_list.clear()
        self.refresh_signal.emit()
        self.logger.info("User list refreshed")
        
    def handle_settings_changed(self, username, show_ip):
        self.setWindowTitle(f"{username} - Python IPMSG")
        self.show_ip = show_ip
        self.update_user_list()
        self.save_settings()  # 保存设置
        self.logger.info(f"Settings updated - Username: {username}, Show IP: {show_ip}")
        self.settings_changed_signal.emit(username)
        
    def update_user_list(self):
        for i in range(self.user_list.count()):
            item = self.user_list.item(i)
            if self.show_ip:
                item.setText(f"{item.text().split(' [')[0]} [{item.ip}]")
            else:
                item.setText(item.text().split(' [')[0])
    
    def user_selected(self, item):
        self.current_chat_user = item
        self.send_button.setEnabled(True)
        self.file_button.setEnabled(True)
        
        # 切换聊天记录
        self.chat_display.clear()
        if item.ip in self.chat_history:
            for msg in self.chat_history[item.ip]:
                self.chat_display.append(msg)
                
        # 清除粗体标记
        font = item.font()
        font.setBold(False)
        item.setFont(font)
        
    def add_user(self, ip, username):
        # 修改现有方法
        for i in range(self.user_list.count()):
            item = self.user_list.item(i)
            if item.ip == ip:
                display_name = f"{username} [{ip}]" if self.show_ip else username
                item.setText(display_name)
                self.logger.info(f"User updated: {username} ({ip})")
                return
        
        display_name = f"{username} [{ip}]" if self.show_ip else username
        item = UserListItem(display_name, ip)
        self.user_list.addItem(item)
        self.logger.info(f"New user added: {username} ({ip})")
        
    def remove_user(self, ip):
        # 修改现有方法
        for i in range(self.user_list.count()):
            item = self.user_list.item(i)
            if item.ip == ip:
                self.user_list.takeItem(i)
                if self.current_chat_user and self.current_chat_user.ip == ip:
                    self.current_chat_user = None
                    self.send_button.setEnabled(False)
                    self.file_button.setEnabled(False)
                self.logger.info(f"User removed: {item.text()} ({ip})")
                break
                
    def send_message(self):
        if not self.current_chat_user:
            return
            
        message = self.message_input.text()
        if message:
            msg_text = f"我: {message}"
            self.chat_display.append(msg_text)
            self.add_chat_message(self.current_chat_user.ip, msg_text)
            self.send_message_signal.emit(message, self.current_chat_user.ip)
            self.message_input.clear()
            
    def receive_message(self, sender_ip, message):
        username = "未知用户"
        for i in range(self.user_list.count()):
            item = self.user_list.item(i)
            if item.ip == sender_ip:
                username = item.text().split(' [')[0]  # 去掉IP部分
                break
                
        msg_text = f"{username}: {message}"
        
        # 如果当前聊天窗口不是发送方，显示系统通知
        if not self.current_chat_user or self.current_chat_user.ip != sender_ip:
            self.tray_icon.showMessage(
                f"来自 {username} 的新消息",
                message,
                QSystemTrayIcon.Information,
                3000  # 显示3秒
            )
            # 在用户列表中找到对应项并设置字体为粗体
            for i in range(self.user_list.count()):
                item = self.user_list.item(i)
                if item.ip == sender_ip:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                    break
        
        # 添加消息到聊天记录
        self.chat_display.append(msg_text)
        self.add_chat_message(sender_ip, msg_text)
        
    def send_file(self):
        if not self.current_chat_user:
            return
            
        file_path, _ = QFileDialog.getOpenFileName(self, "选择文件")
        if file_path:
            # 添加传输进度显示
            filename = os.path.basename(file_path)
            self.add_transfer_progress(filename, 'send')
            # 保存文件路径以供后续使用
            self.pending_files = getattr(self, 'pending_files', {})
            self.pending_files[filename] = file_path
            # 发送文件请求
            self.send_file_signal.emit(file_path, self.current_chat_user.ip)
            
    def handle_file_request(self, sender_ip, filename, size, sender_name):
        size_mb = size / (1024 * 1024)  # size 已经是整数了
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Question)
        msg.setText(f"{sender_name} 想要发送文件给你")
        msg.setInformativeText(f"文件名: {filename}\n大小: {size_mb:.2f} MB")
        msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        
        if msg.exec() == QMessageBox.Ok:
            save_path, _ = QFileDialog.getSaveFileName(
                self,
                "保存文件",
                filename,
                "所有文件 (*.*)"
            )
            if save_path:
                self.add_transfer_progress(filename, 'receive')
                # 发送接受信号
                self.file_response_signal.emit(filename, sender_ip, True)
                # 发出设置保存路径的信号
                self.set_save_path_signal.emit(filename, save_path)
            else:
                # 用户取消了保存对话框，发送拒绝信号
                self.file_response_signal.emit(filename, sender_ip, False)
        else:
            # 用户点击了拒绝按钮，发送拒绝信号
            self.file_response_signal.emit(filename, sender_ip, False)
        
    def add_transfer_progress(self, filename, operation):
        if filename not in self.transfers:
            widget = TransferWidget(filename, operation, self)
            widget.cancel_button.clicked.connect(
                lambda: self.cancel_transfer_signal.emit(filename)
            )
            self.transfers[filename] = widget
            self.transfer_layout.addWidget(widget)
            
    def update_transfer_progress(self, filename, operation, value):
        if filename in self.transfers:
            self.transfers[filename].update_progress(value)
            
    def update_transfer_status(self, filename, status):
        if filename in self.transfers:
            self.transfers[filename].update_status(status)
            
    def handle_transfer_error(self, filename, operation, error_message):
        QMessageBox.warning(
            self,
            "传输错误",
            f"{'发送' if operation == 'send' else '接收'} {filename} 时发生错误：\n{error_message}"
        )
            
    def transfer_complete(self, filename, operation):
        if filename in self.transfers:
            widget = self.transfers[filename]  # 直接获取 TransferWidget 对象
            widget.label.setText(f"{'发送' if operation == 'send' else '接收'} {filename} - 完成")
            widget.progress.setValue(100)

    def closeEvent(self, event):
        reply = QMessageBox.question(
            self, '确认退出',
            "确定要退出程序吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.save_settings()  # 保存设置
            self.logger.info("Application closing")
            event.accept()
        else:
            event.ignore() 

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and self.current_chat_user:
            event.acceptProposedAction()
            
    def dropEvent(self, event):
        if self.current_chat_user:
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                if os.path.isfile(file_path):
                    self.add_transfer_progress(os.path.basename(file_path), 'send')
                    self.send_file_signal.emit(file_path, self.current_chat_user.ip)
                    
    def handle_file_transfer_complete(self, filename, operation, target_ip):
        widget = self.transfers.get(filename)
        if widget:
            widget.update_status(TransferStatus.COMPLETED)
        
        if operation == 'send':
            QMessageBox.information(self, "传输完成", f"文件 {filename} 已成功发送")
        else:
            QMessageBox.information(self, "传输完成", f"文件 {filename} 已成功接收")
        self.logger.info(f"File transfer complete: {filename} ({operation})")
        
    def save_chat_history(self):
        try:
            with open('chat_history.json', 'w', encoding='utf-8') as f:
                json.dump(self.chat_history, f, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Error saving chat history: {e}")
            
    def load_chat_history(self):
        try:
            with open('chat_history.json', 'r', encoding='utf-8') as f:
                self.chat_history = json.load(f)
        except:
            self.chat_history = {}
            
    def add_chat_message(self, ip, message):
        if ip not in self.chat_history:
            self.chat_history[ip] = []
        self.chat_history[ip].append(message)
        self.save_chat_history() 

    def handle_file_transfer_accepted(self, filename, target_ip):
        # 当接收方接受文件时，开始实际的文件传输
        if hasattr(self, 'pending_files') and filename in self.pending_files:
            file_path = self.pending_files[filename]
            self.file_transfer_request.emit(file_path, target_ip)
            del self.pending_files[filename] 

    def handle_file_rejected(self, filename, sender_name):
        # 处理文件拒绝消息
        QMessageBox.information(
            self,
            "文件传输取消",
            f"{sender_name} 拒绝接收文件 {filename}"
        )
        # 更新传输状态
        if filename in self.transfers:
            self.transfers[filename].update_status(TransferStatus.CANCELLED)
            
    def handle_settings_changed(self, username, show_ip):
        self.setWindowTitle(f"{username} - Python IPMSG")
        self.show_ip = show_ip
        self.update_user_list()
        self.save_settings()  # 保存设置
        self.logger.info(f"Settings updated - Username: {username}, Show IP: {show_ip}")
        self.settings_changed_signal.emit(username) 