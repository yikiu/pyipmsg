from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, 
                             QLabel, QLineEdit, QCheckBox, QPushButton)
from PySide6.QtCore import Signal

class SettingsDialog(QDialog):
    settings_changed = Signal(str, bool)  # username, show_ip
    
    def __init__(self, current_username="", show_ip=True, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(300)
        
        layout = QVBoxLayout(self)
        
        # 用户名设置
        name_layout = QHBoxLayout()
        name_label = QLabel("显示名称:")
        self.name_input = QLineEdit(current_username)
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_input)
        layout.addLayout(name_layout)
        
        # IP显示设置
        self.show_ip_checkbox = QCheckBox("显示IP地址")
        self.show_ip_checkbox.setChecked(show_ip)
        layout.addWidget(self.show_ip_checkbox)
        
        # 按钮
        button_layout = QHBoxLayout()
        save_button = QPushButton("保存")
        cancel_button = QPushButton("取消")
        button_layout.addWidget(save_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
        
        # 连接信号
        save_button.clicked.connect(self.save_settings)
        cancel_button.clicked.connect(self.reject)
        
    def save_settings(self):
        username = self.name_input.text().strip()
        if not username:
            username = "未命名用户"
        self.settings_changed.emit(username, self.show_ip_checkbox.isChecked())
        self.accept() 