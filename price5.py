import sys
import os
import json
import time
import threading
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                             QTextEdit, QTabWidget, QGroupBox, QGridLayout, 
                             QFileDialog, QMessageBox, QFrame)
from PyQt6.QtCore import pyqtSignal, QThread, Qt, QTimer, QTime
from PyQt6.QtGui import QFont, QColor

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from playsound import playsound

# --- 設定檔名稱 ---
CONFIG_FILE = "monitor_config.json"

# --- 工作執行緒 (負責 Selenium 爬蟲) ---
class CrawlerThread(QThread):
    # 定義信號用來更新 GUI
    log_signal = pyqtSignal(str)           # 傳送日誌文字
    price_signal = pyqtSignal(float, float, str) # 傳送 (Bid, Ask, Time)
    status_signal = pyqtSignal(str)        # 傳送狀態列文字
    finished_signal = pyqtSignal()         # 結束信號

    def __init__(self, driver_path):
        super().__init__()
        self.driver_path = driver_path
        self.running = True
        self.driver = None

    def run(self):
        # 設定 Driver 服務路徑
        service = Service(executable_path=self.driver_path)
        
        chrome_options = Options()
        
        # --- 啟用無頭模式 (Headless) ---
        chrome_options.add_argument("--headless") 
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        
        # 加入防偵測與穩定性參數
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        chrome_options.add_argument("--ignore-certificate-errors")
        chrome_options.add_argument("--log-level=3") # 減少控制台垃圾訊息

        try:
            self.log_signal.emit("正在背景啟動 Chrome 瀏覽器 (無頭模式)...")
            self.status_signal.emit("啟動瀏覽器中...")
            
            # 初始化瀏覽器
            self.driver = webdriver.Chrome(service=service, options=chrome_options)

            self.log_signal.emit("前往目標網站...")
            self.driver.get("https://www.wfbullion.com/")
            
            wait = WebDriverWait(self.driver, 20)
            
            while self.running:
                try:
                    # 等待價格元素出現
                    price_element = wait.until(EC.presence_of_element_located((By.ID, "pm-llg")))
                    raw_text = price_element.text.strip()
                    lines = raw_text.split('\n')

                    if len(lines) > 3:
                        # 解析網頁結構 (第3行是買入價，第4行是賣出價)
                        bid_str = lines[2].strip().replace(',', '')
                        ask_line = lines[3].strip()
                        ask_str = ask_line.split(' ')[0].replace(',', '')

                        try:
                            bid = float(bid_str)
                            ask = float(ask_str)
                            now_str = time.strftime("%H:%M:%S")

                            # 發送數據給 GUI
                            self.price_signal.emit(bid, ask, now_str)
                            self.status_signal.emit("監控中 - 運行正常")
                        except ValueError:
                            self.log_signal.emit(f"數據轉換錯誤: {bid_str} / {ask_str}")
                    else:
                        self.log_signal.emit("抓取格式異常 (行數不足)")

                except Exception as e:
                    if not self.running: break
                    err_msg = str(e).lower()
                    if "invalid session id" in err_msg or "no such window" in err_msg:
                        self.log_signal.emit("瀏覽器已被關閉，停止監控。")
                        break
                
                # 暫停機制 (將 1 秒切分成小片段)
                for _ in range(10): 
                    if not self.running: break
                    time.sleep(0.1)

        except Exception as e:
            self.log_signal.emit(f"發生致命錯誤: {str(e)}")
        finally:
            self.stop_driver()
            self.finished_signal.emit()

    def stop(self):
        self.running = False

    def stop_driver(self):
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None

# --- 主視窗 ---
class GoldMonitorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("倫敦金點差監控")
        self.resize(680, 750) # 稍微加寬視窗以容納狀態欄
        
        self.crawler_thread = None

        # 初始化 UI
        self.init_ui()
        
        # 初始化即時時鐘 Timer
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_realtime_clock)
        self.clock_timer.start(1000)
        
        # 載入設定
        self.load_settings()

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        # 建立分頁
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # 分頁 1: 監控面板
        self.tab_monitor = QWidget()
        self.setup_monitor_tab()
        self.tabs.addTab(self.tab_monitor, "監控面板")

        # 分頁 2: 運行日誌
        self.tab_log = QWidget()
        self.setup_log_tab()
        self.tabs.addTab(self.tab_log, "運行日誌")

    def setup_monitor_tab(self):
        layout = QVBoxLayout(self.tab_monitor)

        # --- 價格顯示區 ---
        price_group = QGroupBox("即時報價")
        price_layout = QVBoxLayout()
        
        self.lbl_bid = QLabel("買入 (Bid): --")
        self.lbl_bid.setFont(QFont("Arial", 20, QFont.Weight.Bold))
        self.lbl_bid.setStyleSheet("color: blue;")
        self.lbl_bid.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.lbl_ask = QLabel("賣出 (Ask): --")
        self.lbl_ask.setFont(QFont("Arial", 20, QFont.Weight.Bold))
        self.lbl_ask.setStyleSheet("color: red;")
        self.lbl_ask.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 點差顯示
        self.lbl_spread = QLabel("當前點差 (Spread): --")
        self.lbl_spread.setFont(QFont("Arial", 24, QFont.Weight.Bold))
        self.lbl_spread.setStyleSheet("color: purple; background-color: #f0f0f0; padding: 10px; border-radius: 5px;")
        self.lbl_spread.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_data_time = QLabel("數據更新時間: --")
        self.lbl_data_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_data_time.setStyleSheet("color: gray;")

        price_layout.addWidget(self.lbl_bid)
        price_layout.addWidget(self.lbl_ask)
        price_layout.addWidget(self.lbl_spread)
        price_layout.addWidget(self.lbl_data_time)
        price_group.setLayout(price_layout)
        layout.addWidget(price_group)

        # --- 警報設定區 (3層級) ---
        alert_group = QGroupBox("點差警報設定")
        alert_layout = QGridLayout()
        
        # 設定表頭
        alert_layout.addWidget(QLabel("層級"), 0, 0)
        alert_layout.addWidget(QLabel("點差門檻"), 0, 1)
        alert_layout.addWidget(QLabel("音效路徑"), 0, 2)
        alert_layout.addWidget(QLabel("狀態"), 0, 3) # 新增狀態欄
        alert_layout.addWidget(QLabel("操作"), 0, 4)

        self.tiers = []

        # 建立 3 行設定
        for i in range(3):
            lbl_level = QLabel(f"層級 {i+1}")
            
            txt_diff = QLineEdit()
            txt_diff.setPlaceholderText("如 0.7")
            txt_diff.setFixedWidth(80)
            
            txt_sound = QLineEdit()
            txt_sound.setPlaceholderText("未選擇音效")
            txt_sound.setReadOnly(False)
            
            # --- 新增：狀態標籤 ---
            lbl_status_display = QLabel("") 
            lbl_status_display.setStyleSheet("color: red; font-weight: bold;")
            lbl_status_display.setFixedWidth(60)
            
            btn_browse = QPushButton("瀏覽")
            btn_browse.clicked.connect(lambda checked, t=txt_sound: self.browse_file(t))
            
            alert_layout.addWidget(lbl_level, i+1, 0)
            alert_layout.addWidget(txt_diff, i+1, 1)
            alert_layout.addWidget(txt_sound, i+1, 2)
            alert_layout.addWidget(lbl_status_display, i+1, 3) # 放置狀態標籤
            alert_layout.addWidget(btn_browse, i+1, 4)

            self.tiers.append({
                "diff": txt_diff,
                "sound": txt_sound,
                "status_lbl": lbl_status_display  # 儲存引用以便更新
            })

        alert_group.setLayout(alert_layout)
        layout.addWidget(alert_group)

        # --- 控制按鈕區 ---
        btn_layout = QHBoxLayout()
        
        self.btn_start = QPushButton("開始背景監控")
        self.btn_start.setStyleSheet("background-color: green; color: white; font-size: 16px; padding: 10px; font-weight: bold;")
        self.btn_start.clicked.connect(self.start_monitor)
        
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setStyleSheet("background-color: red; color: white; font-size: 16px; padding: 10px; font-weight: bold;")
        self.btn_stop.clicked.connect(self.stop_monitor)
        self.btn_stop.setEnabled(False)

        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        layout.addLayout(btn_layout)

        # --- 分隔線 ---
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        # --- 即時大字體時鐘 ---
        self.lbl_realtime_clock = QLabel("--:--:--")
        self.lbl_realtime_clock.setFont(QFont("Arial", 48, QFont.Weight.Bold))
        self.lbl_realtime_clock.setStyleSheet("""
            QLabel {
                color: #2c3e50;
                background-color: #ecf0f1;
                border: 2px solid #bdc3c7;
                border-radius: 10px;
                padding: 5px;
            }
        """)
        self.lbl_realtime_clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_realtime_clock)

        # --- 狀態列 ---
        self.lbl_status = QLabel("狀態: 等待開始")
        self.lbl_status.setStyleSheet("color: gray; margin-top: 5px;")
        layout.addWidget(self.lbl_status)

    def setup_log_tab(self):
        layout = QVBoxLayout(self.tab_log)
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setFont(QFont("Consolas", 10))
        
        btn_clear = QPushButton("清除日誌")
        btn_clear.clicked.connect(lambda: self.txt_log.clear())
        
        layout.addWidget(self.txt_log)
        layout.addWidget(btn_clear)

    # --- 核心邏輯 ---

    def update_realtime_clock(self):
        current_time = QTime.currentTime()
        time_text = current_time.toString("HH:mm:ss")
        self.lbl_realtime_clock.setText(time_text)
    
    def get_base_path(self):
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        else:
            return os.path.dirname(os.path.abspath(__file__))

    def browse_file(self, line_edit):
        file_name, _ = QFileDialog.getOpenFileName(self, "選擇音效檔", "", "Audio Files (*.mp3 *.wav *.ogg);;All Files (*.*)")
        if file_name:
            line_edit.setText(file_name)

    def log_message(self, msg):
        timestamp = time.strftime("%H:%M:%S")
        self.txt_log.append(f"[{timestamp}] {msg}")
        sb = self.txt_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def update_status(self, msg):
        self.lbl_status.setText(f"狀態: {msg}")

    def update_price(self, bid, ask, time_str):
        self.lbl_bid.setText(f"買入 (Bid): {bid:.2f}")
        self.lbl_ask.setText(f"賣出 (Ask): {ask:.2f}")
        self.lbl_data_time.setText(f"數據更新時間: {time_str}")

        spread = abs(ask - bid)
        self.lbl_spread.setText(f"當前點差 (Spread): {spread:.2f}")

        # 檢查是否觸發警報
        self.check_alert(spread, bid, ask)

    def check_alert(self, current_spread, bid, ask):
        settings = self.get_tier_settings()
        
        # 收集需要播放音效的層級 (可能有同時多個觸發，我們只播最嚴重的一個以防吵雜)
        sounds_to_play = []

        # 遍歷每一個層級，獨立判斷狀態
        for i, tier in enumerate(settings):
            ui_component = self.tiers[i] # 取得對應的 UI 元件 (包含 label)
            status_label = ui_component['status_lbl']
            threshold = tier['diff']

            # 情況 A: 點差 >= 門檻 (觸發)
            if threshold > 0 and current_spread >= threshold:
                # 檢查當前狀態
                if status_label.text() != "已播放":
                    # 狀態轉換：未播放 -> 已播放
                    status_label.setText("已播放")
                    
                    msg = f"!!! 觸發警報 (層級 {i+1}) !!! 點差擴大: {current_spread:.2f} >= {threshold}"
                    self.log_message(msg)
                    
                    # 加入播放清單
                    if tier['sound']:
                        sounds_to_play.append((threshold, tier['sound']))
                
                # 如果已經是 "已播放"，則什麼都不做 (靜音保持狀態)

            # 情況 B: 點差 < 門檻 (解除)
            elif threshold > 0 and current_spread < threshold:
                if status_label.text() == "已播放":
                    # 狀態轉換：已播放 -> 重置
                    status_label.setText("") 
                    # self.log_message(f"層級 {i+1} 警報解除 (點差回落)")

        # 播放音效邏輯
        if sounds_to_play:
            # 如果同時觸發多個層級 (例如從 0 直接跳到 1.0，同時超過 0.5 和 0.8)
            # 這裡選擇只播放「門檻最高」的那個音效，避免多重音效混雜
            # 排序：根據 threshold (item[0]) 由大到小
            sounds_to_play.sort(key=lambda x: x[0], reverse=True)
            
            best_sound_path = sounds_to_play[0][1]
            threading.Thread(target=self.play_sound_task, args=(best_sound_path, 2), daemon=True).start()

    def get_tier_settings(self):
        data = []
        for t in self.tiers:
            try:
                val = float(t['diff'].text())
            except ValueError:
                val = 0.0
            path = t['sound'].text().strip()
            data.append({"diff": val, "sound": path})
        return data

    def play_sound_task(self, path, repeat_count):
        if not os.path.exists(path):
            self.log_message(f"找不到音效檔: {path}")
            return
        
        try:
            for i in range(repeat_count):
                playsound(path)
        except Exception as e:
            self.log_message(f"播放失敗: {e}")

    def start_monitor(self):
        base_path = self.get_base_path()
        driver_path = os.path.join(base_path, "chromedriver.exe")
        
        if not os.path.exists(driver_path):
            QMessageBox.critical(self, "錯誤", f"找不到 chromedriver.exe\n\n請確保它位於以下目錄：\n{base_path}")
            return

        self.save_settings()

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.txt_log.clear()
        self.log_message("--- 開始監控程序 (無頭模式) ---")
        self.log_message(f"模式：監控買賣點差 (Spread)")

        self.crawler_thread = CrawlerThread(driver_path)
        self.crawler_thread.log_signal.connect(self.log_message)
        self.crawler_thread.price_signal.connect(self.update_price)
        self.crawler_thread.status_signal.connect(self.update_status)
        self.crawler_thread.finished_signal.connect(self.on_thread_finished)
        self.crawler_thread.start()

    def stop_monitor(self):
        if self.crawler_thread:
            self.update_status("正在停止...")
            self.crawler_thread.stop()
            self.btn_stop.setEnabled(False)

    def on_thread_finished(self):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.update_status("已停止")
        self.log_message("--- 監控已停止 ---")
        self.crawler_thread = None

    def save_settings(self):
        data = self.get_tier_settings()
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            self.log_message("設定已儲存")
        except Exception as e:
            self.log_message(f"設定儲存失敗: {e}")

    def load_settings(self):
        if not os.path.exists(CONFIG_FILE):
            return
        
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            for i, item in enumerate(data):
                if i < len(self.tiers):
                    if item['diff'] > 0:
                        self.tiers[i]['diff'].setText(str(item['diff']))
                    self.tiers[i]['sound'].setText(item.get('sound', ''))
        except Exception as e:
            self.log_message(f"讀取設定失敗: {e}")

    def closeEvent(self, event):
        if self.crawler_thread and self.crawler_thread.isRunning():
            reply = QMessageBox.question(self, '退出', '監控正在背景執行中，確定要退出嗎？',
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.crawler_thread.stop()
                self.crawler_thread.wait()
                self.save_settings()
                event.accept()
            else:
                event.ignore()
        else:
            self.save_settings()
            event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    font = QFont("Microsoft JhengHei", 10)
    app.setFont(font)
    
    window = GoldMonitorApp()
    window.show()
    sys.exit(app.exec())