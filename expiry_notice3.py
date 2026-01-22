import sys
import os
import json
import pandas as pd
from datetime import datetime, timedelta
import pytz
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QTableWidget,
                             QTableWidgetItem, QFileDialog, QHeaderView, QStatusBar,
                             QMessageBox, QTabWidget, QTextEdit, QLineEdit)
from PyQt6.QtCore import QTimer, Qt, QUrl
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput


class SettlementMonitor(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("結算到期通知系統")
        self.resize(1250, 850)  # 稍微加寬以容納新輸入框

        # --- 核心變數 ---
        self.config_file = "config.json"
        self.log_folder = "logs"
        self.last_excel_path = ""
        self.custom_sounds = {}  # {Product: SoundPath}
        self.loop_settings = {}  # {UniqueID: LoopCount}

        # 自動重啟預設值
        self.daily_restart_time = "06:00:00"

        # 播放控制變數
        self.active_loops_left = 0
        self.current_playing_product = None

        self.df_schedule = pd.DataFrame()
        self.alert_triggered = set()
        self.default_sound = "sounds/alert.wav"

        # 確保目錄存在
        if not os.path.exists(self.log_folder):
            os.makedirs(self.log_folder)
        if not os.path.exists("sounds"):
            os.makedirs("sounds")

        # --- 初始化 ---
        self.load_config()  # 先讀取設定 (包含重啟時間)
        self.init_ui()  # 再建立 UI (會把時間填入輸入框)

        # --- 系統計時器 (UI 更新) ---
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_status)
        self.timer.start(1000)  # 每 1000 毫秒 (1秒) 觸發一次

        # --- 音效播放器 ---
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.player.mediaStatusChanged.connect(self.on_media_status_changed)

        # 自動載入上次的檔案
        if self.last_excel_path and os.path.exists(self.last_excel_path):
            self.process_data(self.last_excel_path)

        print(f"系統啟動完成。預計每日重啟時間: {self.daily_restart_time}")
        self.write_log(f"系統啟動。每日重啟時間設定為: {self.daily_restart_time}")

    def load_config(self):
        """讀取設定"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.last_excel_path = config.get("last_excel", "")
                    self.custom_sounds = config.get("custom_sounds", {})
                    self.loop_settings = config.get("loop_settings", {})
                    # 讀取重啟時間，若無則使用預設值
                    self.daily_restart_time = config.get("daily_restart_time", "06:00:00")
            except Exception as e:
                print(f"載入設定檔失敗: {e}")

    def save_config(self, manual=False):
        """儲存設定 (包含 UI 上的重啟時間)"""

        # 如果是手動儲存，先從 UI 獲取最新的重啟時間設定
        if hasattr(self, 'input_restart'):
            new_time = self.input_restart.text().strip()
            # 簡單驗證長度，避免存入空值
            if len(new_time) >= 5:
                self.daily_restart_time = new_time

        config = {
            "last_excel": self.last_excel_path,
            "custom_sounds": self.custom_sounds,
            "loop_settings": self.loop_settings,
            "daily_restart_time": self.daily_restart_time
        }
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=4)

            if manual:
                print(f"設定已儲存。重啟時間更新為: {self.daily_restart_time}")
                QMessageBox.information(self, "儲存成功",
                                        f"版面設定與路徑已儲存\n每日重啟時間: {self.daily_restart_time}")
        except Exception as e:
            print(f"儲存設定失敗: {e}")
            if manual:
                QMessageBox.critical(self, "儲存失敗", f"無法寫入設定檔: {e}")

    def restart_program(self):
        """重啟程式"""
        print("執行每日自動重啟...")
        self.write_log("系統正在執行每日自動重啟...")
        self.save_config()  # 重啟前先存檔

        # 使用 os.execl 重新執行當前的 Python script
        python = sys.executable
        os.execl(python, python, *sys.argv)

    def init_ui(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #000000; }
            QTabWidget::pane { border: 1px solid #444; }
            QTabBar::tab {
                background: #222; color: #aaa; padding: 10px 20px;
                border: 1px solid #444; border-bottom: none;
            }
            QTabBar::tab:selected { background: #007acc; color: white; font-weight: bold; }
            QLabel { color: #e0e0e0; font-family: 'Microsoft JhengHei', Segoe UI; font-size: 14px; }
            QTableWidget { 
                background-color: #000000; color: #ffffff; 
                gridline-color: #333333; font-size: 14px;
                selection-background-color: #333333;
            }
            QHeaderView::section {
                background-color: #111111; color: #ffaa00;
                padding: 8px; border: 1px solid #333333; font-weight: bold;
            }
            QPushButton {
                background-color: #333333; color: white;
                border: 1px solid #555; border-radius: 4px; padding: 6px 12px;
            }
            QPushButton:hover { background-color: #555555; }
            #btnSave { background-color: #2e7d32; border: 1px solid #4caf50; }
            QTextEdit { background-color: #111; color: #0f0; font-family: Consolas; font-size: 13px; }
            QLineEdit { 
                background-color: #222; color: #0f0; border: 1px solid #555; 
                padding: 4px; font-family: Consolas; font-size: 14px;
            }
        """)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        self.tab_monitor = QWidget()
        self.init_monitor_tab()
        self.tabs.addTab(self.tab_monitor, "📊 監控面板")

        self.tab_log = QWidget()
        self.init_log_tab()
        self.tabs.addTab(self.tab_log, "📝 播放日誌")

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

    def init_monitor_tab(self):
        layout = QVBoxLayout(self.tab_monitor)
        top_layout = QHBoxLayout()

        # 按鈕區
        self.btn_load = QPushButton("📥 重新導入結算表(GMT+0)")
        self.btn_load.clicked.connect(self.select_file)

        self.btn_save = QPushButton("💾 儲存設定")
        self.btn_save.setObjectName("btnSave")
        self.btn_save.clicked.connect(lambda: self.save_config(manual=True))

        # --- 新增：每日重啟時間設定 ---
        lbl_restart = QLabel("每日重啟時間 (HH:MM:SS):")
        self.input_restart = QLineEdit()
        self.input_restart.setText(self.daily_restart_time)  # 填入設定檔讀取的值
        self.input_restart.setFixedWidth(100)
        self.input_restart.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.input_restart.setPlaceholderText("06:00:00")

        # 時間顯示
        self.lbl_current_time = QLabel("系統時間: --:--:--")
        self.lbl_current_time.setFont(QFont("Consolas", 15, QFont.Weight.Bold))
        self.lbl_current_time.setStyleSheet("color: #00ff00; margin-left: 20px;")

        # 排版加入
        top_layout.addWidget(self.btn_load)
        top_layout.addWidget(self.btn_save)

        # 加入間隔
        top_layout.addSpacing(20)
        top_layout.addWidget(lbl_restart)
        top_layout.addWidget(self.input_restart)

        top_layout.addStretch()
        top_layout.addWidget(self.lbl_current_time)
        layout.addLayout(top_layout)

        # 表格區
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        headers = ["產品", "結算時間 (GMT+8)", "預警倒數", "狀態", "連播次數", "音效路徑", "設定"]
        self.table.setHorizontalHeaderLabels(headers)

        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        # 連結變更事件
        self.table.itemChanged.connect(self.on_table_item_changed)
        layout.addWidget(self.table)

    def init_log_tab(self):
        layout = QVBoxLayout(self.tab_log)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

    def write_log(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        self.log_text.append(log_entry)

        # 寫入檔案
        date_str = datetime.now().strftime("%Y-%m-%d")
        filename = os.path.join(self.log_folder, f"log_{date_str}.txt")
        try:
            with open(filename, "a", encoding="utf-8") as f:
                f.write(log_entry + "\n")
        except Exception as e:
            print(f"寫入 Log 檔案失敗: {e}")

    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "選擇結算表", "", "Data (*.xlsx *.csv)")
        if file_path:
            self.last_excel_path = file_path
            self.save_config()
            self.process_data(file_path)

    def process_data(self, file_path):
        try:
            df = pd.read_excel(file_path) if file_path.endswith('.xlsx') else pd.read_csv(file_path)
            first_col = df.columns[0]
            df = df.rename(columns={first_col: 'Product'})

            date_cols = [c for c in df.columns if any(k in str(c) for k in ['年', '月', 'Month', '202'])]
            df_melted = df.melt(id_vars=['Product'], value_vars=date_cols, value_name='TimeStr').dropna()

            schedule = []
            tz_gmt0, tz_gmt8 = pytz.utc, pytz.timezone('Asia/Taipei')

            for _, row in df_melted.iterrows():
                try:
                    raw = row['TimeStr']
                    dt = raw if isinstance(raw, datetime) else datetime.strptime(str(raw).strip(), "%Y-%m-%d %H:%M:%S")
                    dt_gmt0 = tz_gmt0.localize(dt) if dt.tzinfo is None else dt.astimezone(tz_gmt0)

                    if dt_gmt0 > datetime.now(pytz.utc):
                        schedule.append({
                            'Product': str(row['Product']).strip(),
                            'Settle0': dt_gmt0,
                            'Settle8': dt_gmt0.astimezone(tz_gmt8),
                            'AlertTarget0': dt_gmt0 - timedelta(minutes=30),
                            'UniqueID': f"{row['Product']}_{dt_gmt0.timestamp()}"
                        })
                except Exception as row_err:
                    print(f"處理資料行錯誤: {row_err}")
                    continue

            self.df_schedule = pd.DataFrame(schedule).sort_values('Settle0')
            self.refresh_table()
            self.write_log(f"成功載入: {os.path.basename(file_path)}，共 {len(schedule)} 筆")
        except Exception as e:
            print(f"檔案處理嚴重錯誤: {e}")
            QMessageBox.warning(self, "載入失敗", f"錯誤：{e}")

    def refresh_table(self):
        """刷新表格 (含防呆初始設定)"""
        try:
            self.table.blockSignals(True)
            self.table.setRowCount(len(self.df_schedule))

            for idx, row in self.df_schedule.iterrows():
                i = self.df_schedule.index.get_loc(idx)
                prod = row['Product']
                uid = row['UniqueID']

                # 建立 Item 並設定預設值
                items = [
                    QTableWidgetItem(prod),  # 0: 產品
                    QTableWidgetItem(row['Settle8'].strftime("%Y-%m-%d %H:%M:%S")),  # 1: 時間
                    QTableWidgetItem("--"),  # 2: 倒數
                    QTableWidgetItem("監控中"),  # 3: 狀態
                    QTableWidgetItem(str(self.loop_settings.get(uid, 3))),  # 4: 連播
                    QTableWidgetItem(os.path.basename(self.custom_sounds.get(prod, "預設音效")))  # 5: 音效
                ]

                # 設定 Item 屬性
                for col, item in enumerate(items):
                    # 除了連播設定(col 4)，其他唯讀
                    if col != 4:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

                    # 時間、倒數、狀態、連播 置中
                    if col in [1, 2, 3, 4]:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                    self.table.setItem(i, col, item)

                # 按鈕
                btn_set = QPushButton("更改音效")
                btn_set.clicked.connect(lambda ch, r=i, p=prod: self.pick_sound(r, p))
                self.table.setCellWidget(i, 6, btn_set)

            self.table.blockSignals(False)
        except Exception as e:
            print(f"表格刷新錯誤 Refresh Table Error: {e}")

    def on_table_item_changed(self, item):
        """表格變更事件 (防呆與錯誤捕捉)"""
        if item is None: return  # 防呆: 如果 Item 是空的就直接跳過

        try:
            if item.column() == 4:  # 連播次數欄位
                row = item.row()
                # 再次檢查 index 是否越界
                if row >= len(self.df_schedule): return

                row_data = self.df_schedule.iloc[row]
                uid = row_data['UniqueID']
                new_value = item.text()

                if new_value.isdigit() and int(new_value) > 0:
                    self.loop_settings[uid] = int(new_value)
                    self.save_config()
                else:
                    self.table.blockSignals(True)
                    item.setText(str(self.loop_settings.get(uid, 3)))
                    self.table.blockSignals(False)
                    self.status_bar.showMessage("❌ 請輸入大於 0 的數字", 3000)
        except Exception as e:
            print(f"表格編輯錯誤 Item Changed Error: {e}")

    def pick_sound(self, row_idx, product_name):
        try:
            file_path, _ = QFileDialog.getOpenFileName(self, f"選擇 {product_name} 音效", "sounds", "WAV (*.wav)")
            if file_path:
                self.custom_sounds[product_name] = file_path

                # 防呆: 確保該格存在才設定文字
                item = self.table.item(row_idx, 5)
                if item:
                    item.setText(os.path.basename(file_path))

                self.save_config()
                self.write_log(f"更新音效: {product_name}")
        except Exception as e:
            print(f"選擇音效錯誤: {e}")

    def update_status(self):
        """每秒更新狀態 (含每日重啟與防呆)"""
        now_gmt8 = datetime.now(pytz.timezone('Asia/Taipei'))
        now_str = now_gmt8.strftime('%Y-%m-%d %H:%M:%S')
        self.lbl_current_time.setText(f"系統時間 (GMT+8): {now_str}")

        # ★ 每日重啟檢查 ★
        # 比對目前的 "時:分:秒" 是否等於設定值 (從 self.daily_restart_time 變數讀取)
        if now_gmt8.strftime("%H:%M:%S") == self.daily_restart_time:
            self.restart_program()
            return  # 重啟後停止後續邏輯

        if self.df_schedule.empty: return

        now_gmt0 = datetime.now(pytz.utc)

        try:
            for i in range(self.table.rowCount()):
                # 防呆: 確保資料索引安全
                if i >= len(self.df_schedule): break

                row_data = self.df_schedule.iloc[i]

                # 取得 Table Item (加入防呆，若為 None 則不操作)
                item_cd = self.table.item(i, 2)
                item_st = self.table.item(i, 3)

                # 如果表格這一行還沒初始化好，就跳過
                if item_cd is None or item_st is None:
                    continue

                prod = row_data['Product']
                uid = row_data['UniqueID']
                alert_target = row_data['AlertTarget0']
                settle_time = row_data['Settle0']

                delta = alert_target - now_gmt0
                sec = int(delta.total_seconds())

                # 邏輯判斷
                if sec > 0:
                    h, r = divmod(sec, 3600)
                    m, s = divmod(r, 60)
                    item_cd.setText(f"{h:02}:{m:02}:{s:02}")
                    item_st.setText("監控中")
                    # 顏色重置
                    self.set_row_color(i, QColor("#000000"))

                elif now_gmt0 < settle_time:
                    item_cd.setText("00:00:00")
                    item_st.setText("🚨 準備結算")
                    item_st.setForeground(QColor("#ffaa00"))
                    item_cd.setForeground(QColor("#ff4444"))

                    alert_id = f"alert_{uid}"
                    if alert_id not in self.alert_triggered:
                        self.alert_triggered.add(alert_id)
                        loop_count = self.loop_settings.get(uid, 3)
                        self.start_alarm_sequence(prod, loop_count)
                        self.write_log(f"觸發警報: {prod}")
                        self.set_row_color(i, QColor("#4a2a00"))
                else:
                    item_cd.setText("--")
                    item_st.setText("✅ 已結算")
                    item_st.setForeground(QColor("#888888"))
                    item_cd.setForeground(QColor("#888888"))
                    self.set_row_color(i, QColor("#111111"))

        except Exception as e:
            # ★ 錯誤輸出至 Console ★
            print(f"Update Status Error (Row {i}): {e}")

    def set_row_color(self, row_idx, color):
        """輔助函數：設定整行背景色 (含防呆)"""
        try:
            for c in range(7):
                item = self.table.item(row_idx, c)
                if item:  # 防呆 Check
                    item.setBackground(color)
        except Exception:
            pass

    def start_alarm_sequence(self, product_name, count):
        self.active_loops_left = count
        self.current_playing_product = product_name
        self.play_sound(product_name)

    def play_sound(self, product_name):
        try:
            sound_path = self.custom_sounds.get(product_name)
            if not sound_path or not os.path.exists(sound_path):
                potential = os.path.join("sounds", f"{product_name}.wav")
                sound_path = potential if os.path.exists(potential) else self.default_sound

            if os.path.exists(sound_path):
                self.player.setSource(QUrl.fromLocalFile(os.path.abspath(sound_path)))
                self.audio_output.setVolume(1.0)
                self.player.play()
            else:
                print(f"找不到音效檔案: {sound_path}")
        except Exception as e:
            print(f"播放音效錯誤: {e}")

    def on_media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.active_loops_left > 1:
                self.active_loops_left -= 1
                if self.current_playing_product:
                    self.play_sound(self.current_playing_product)
            else:
                self.active_loops_left = 0
                self.current_playing_product = None


if __name__ == '__main__':
    try:
        app = QApplication(sys.argv)
        win = SettlementMonitor()
        win.show()
        sys.exit(app.exec())
    except Exception as e:
        print(f"程式崩潰 (Critical Error): {e}")