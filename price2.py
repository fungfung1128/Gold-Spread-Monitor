import sys
import os
import json
import time
import threading
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                             QTextEdit, QTabWidget, QGroupBox, QGridLayout, 
                             QFileDialog, QMessageBox)
from PyQt6.QtCore import pyqtSignal, QThread, Qt
from PyQt6.QtGui import QFont

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
        # 若要背景執行可取消註解下面這行
        # chrome_options.add_argument("--headless") 
        
        # 加入防偵測與穩定性參數
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        chrome_options.add_argument("--ignore-certificate-errors")
        chrome_options.add_argument("--log-level=3") # 減少控制台垃圾訊息

        try:
            self.log_signal.emit("正在啟動 Chrome 瀏覽器...")
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
                        # 重要修正：加入 replace(',', '') 以處理千分位 (例如 2,650.00)
                        bid_str = lines[2].strip().replace(',', '')
                        ask_line = lines[3].strip()
                        ask_str = ask_line.split(' ')[0].replace(',', '') # 賣出價可能包含其他文字，取第一段

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
                    # 避免日誌刷頻，只記錄關鍵錯誤 (如瀏覽器被關閉)
                    err_msg = str(e).lower()
                    if "invalid session id" in err_msg or "no such window" in err_msg:
                        self.log_signal.emit("瀏覽器已被關閉，停止監控。")
                        break
                    # 其他網路延遲等錯誤可選擇性忽略
                
                # 暫停機制 (將 3 秒切分成小片段以便能快速響應停止指令)
                for _ in range(30): 
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
        self.setWindowTitle("倫敦金點差監控 (EXE版)")
        self.resize(600, 680)
        
        self.crawler_thread = None

        # 初始化 UI
        self.init_ui()
        
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

        # 新增點差顯示
        self.lbl_spread = QLabel("當前點差 (Spread): --")
        self.lbl_spread.setFont(QFont("Arial", 24, QFont.Weight.Bold))
        self.lbl_spread.setStyleSheet("color: purple; background-color: #f0f0f0; padding: 5px;")
        self.lbl_spread.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_time = QLabel("最後更新: --")
        self.lbl_time.setAlignment(Qt.AlignmentFlag.AlignCenter)

        price_layout.addWidget(self.lbl_bid)
        price_layout.addWidget(self.lbl_ask)
        price_layout.addWidget(self.lbl_spread)
        price_layout.addWidget(self.lbl_time)
        price_group.setLayout(price_layout)
        layout.addWidget(price_group)

        # --- 警報設定區 (3層級) ---
        alert_group = QGroupBox("點差警報設定 (當 點差 >= 參數 時播放)")
        alert_layout = QGridLayout()
        
        alert_layout.addWidget(QLabel("層級"), 0, 0)
        alert_layout.addWidget(QLabel("點差門檻"), 0, 1)
        alert_layout.addWidget(QLabel("音效路徑"), 0, 2)
        alert_layout.addWidget(QLabel("操作"), 0, 3)

        self.tiers = [] # 儲存 UI 元件

        # 建立 3 行設定
        for i in range(3):
            lbl_level = QLabel(f"層級 {i+1}")
            
            # 點數輸入框
            txt_diff = QLineEdit()
            txt_diff.setPlaceholderText("如 0.7")
            txt_diff.setFixedWidth(80)
            
            # 音效路徑輸入框
            txt_sound = QLineEdit()
            txt_sound.setPlaceholderText("未選擇音效")
            txt_sound.setReadOnly(False)
            
            # 瀏覽按鈕
            btn_browse = QPushButton("瀏覽")
            btn_browse.clicked.connect(lambda checked, t=txt_sound: self.browse_file(t))
            
            alert_layout.addWidget(lbl_level, i+1, 0)
            alert_layout.addWidget(txt_diff, i+1, 1)
            alert_layout.addWidget(txt_sound, i+1, 2)
            alert_layout.addWidget(btn_browse, i+1, 3)

            self.tiers.append({
                "diff": txt_diff,
                "sound": txt_sound
            })

        alert_group.setLayout(alert_layout)
        layout.addWidget(alert_group)

        # --- 控制按鈕區 ---
        btn_layout = QHBoxLayout()
        
        self.btn_start = QPushButton("開始監控")
        self.btn_start.setStyleSheet("background-color: green; color: white; font-size: 16px; padding: 10px;")
        self.btn_start.clicked.connect(self.start_monitor)
        
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setStyleSheet("background-color: red; color: white; font-size: 16px; padding: 10px;")
        self.btn_stop.clicked.connect(self.stop_monitor)
        self.btn_stop.setEnabled(False)

        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        layout.addLayout(btn_layout)

        # --- 狀態列 ---
        self.lbl_status = QLabel("狀態: 等待開始")
        self.lbl_status.setStyleSheet("color: gray; margin-top: 10px;")
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
    
    def get_base_path(self):
        """
        關鍵函式：判斷程式執行路徑
        """
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
        self.lbl_time.setText(f"最後更新: {time_str}")

        # --- 這裡就是你要的邏輯 ---
        # 計算點差：絕對值 (Ask - Bid)
        spread = abs(ask - bid)
        
        # 顯示點差
        self.lbl_spread.setText(f"當前點差 (Spread): {spread:.2f}")

        # 檢查是否觸發警報
        self.check_alert(spread, bid, ask)

    def check_alert(self, current_spread, bid, ask):
        settings = self.get_tier_settings()
        
        triggered_tier = None

        # 排序：從門檻最高的開始檢查
        valid_settings = [s for s in settings if s['diff'] > 0]
        valid_settings.sort(key=lambda x: x['diff'], reverse=True)

        for tier in valid_settings:
            # 邏輯：如果 當前點差 >= 設定值，則觸發
            if current_spread >= tier['diff']:
                triggered_tier = tier
                break
        
        if triggered_tier:
            msg = f"!!! 觸發警報 !!! 點差擴大: {current_spread:.2f} >= 門檻 {triggered_tier['diff']} [Bid:{bid} Ask:{ask}]"
            self.log_message(msg)
            
            # 背景播放音效 (播放 2 次)
            if triggered_tier['sound']:
                threading.Thread(target=self.play_sound_task, args=(triggered_tier['sound'], 2), daemon=True).start()

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
                # time.sleep(0.5) 
        except Exception as e:
            self.log_message(f"播放失敗: {e}")

    def start_monitor(self):
        # 1. 取得程式根目錄
        base_path = self.get_base_path()
        driver_path = os.path.join(base_path, "chromedriver.exe")
        
        # 2. 檢查 chromedriver 是否存在
        if not os.path.exists(driver_path):
            QMessageBox.critical(self, "錯誤", f"找不到 chromedriver.exe\n\n請確保它位於以下目錄：\n{base_path}")
            return

        # 3. 儲存 UI 設定
        self.save_settings()

        # 4. 初始化狀態
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.txt_log.clear()
        self.log_message("--- 開始監控程序 ---")
        self.log_message(f"模式：監控買賣點差 (Spread)")

        # 5. 啟動執行緒
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

    # --- 設定存取 ---
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

    # --- 關閉視窗事件 ---
    def closeEvent(self, event):
        if self.crawler_thread and self.crawler_thread.isRunning():
            reply = QMessageBox.question(self, '退出', '監控正在執行中，確定要退出嗎？',
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