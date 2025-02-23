import sys
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow
from network.udp_client import UDPClient
from network.file_server import FileTransferServer
from ui.settings_dialog import SettingsDialog

def main():
    app = QApplication(sys.argv)
    
    window = MainWindow()
    udp_client = UDPClient()
    file_server = FileTransferServer()
    
    # 连接信号和槽
    window.send_message_signal.connect(udp_client.send_message)
    window.send_file_signal.connect(udp_client.send_file_request)
    
    udp_client.message_received.connect(window.receive_message)
    udp_client.user_online.connect(window.add_user)
    udp_client.user_offline.connect(window.remove_user)
    udp_client.file_request.connect(window.handle_file_request)
    
    # 连接文件传输信号
    udp_client.file_transfer_request.connect(file_server.send_file)
    file_server.transfer_progress.connect(window.update_transfer_progress)
    file_server.transfer_complete.connect(window.transfer_complete)
    file_server.transfer_status.connect(window.update_transfer_status)
    file_server.transfer_error.connect(window.handle_transfer_error)
    
    # 连接取消传输信号
    window.cancel_transfer_signal.connect(file_server.cancel_transfer)
    
    # 连接设置相关信号
    window.settings_changed_signal.connect(udp_client.set_username)
    
    # 连接刷新信号
    window.refresh_signal.connect(udp_client.broadcast_presence)
    
    # 连接文件传输相关信号
    window.file_response_signal.connect(udp_client.send_file_response)
    udp_client.file_accepted.connect(window.handle_file_transfer_accepted)
    window.file_transfer_request.connect(file_server.send_file)
    
    # 连接文件保存路径信号
    window.set_save_path_signal.connect(file_server.set_save_path)
    
    # 连接文件拒绝信号
    udp_client.file_rejected.connect(window.handle_file_rejected)
    
    # 广播在线状态
    udp_client.broadcast_presence()
    
    # 启动文件接收服务器
    file_server.start_receiving()
    
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main() 