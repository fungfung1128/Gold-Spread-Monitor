import sys
import os
import json
import time
import threading
import re
import winsound
import uuid

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QTextEdit, QTabWidget, QGridLayout,
                             QFileDialog, QMessageBox, QTableWidget,
                             QTableWidgetItem, QHeaderView, QSplitter,
                             QListWidget, QStackedWidget, QGroupBox, QTextBrowser,
                             QCheckBox, QComboBox, QFormLayout, QScrollArea)
from PyQt6.QtCore import pyqtSignal, QThread, Qt, QTimer, QTime, pyqtSlot
from PyQt6.QtGui import QFont, QColor

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# --- 設定檔名稱 ---
CONFIG_FILE = "monitor_config_v11_dynamic.json"

# ==========================================
#    預設券商設定 (當沒有設定檔時使用)
#    這裡展示如何將原本硬寫的邏輯轉為參數
# ==========================================
DEFAULT_BROKERS = [
    {
        "id": "WF", "name": "永豐金業", "url": "https://www.wfbullion.com/",
        "bid_type": "id", "bid_selector": "pm-llg",
        "ask_type": "id", "ask_selector": "pm-llg",
        # 備註: 永豐原本邏輯特殊(同一格換行)，通用爬蟲會嘗試解析，若不行需用更精確的XPATH
        "note": "自動解析"
    },
    {
        "id": "IG", "name": "IG Markets", "url": "https://www.ig.com/cn/commodities/markets-commodities/gold",
        "bid_type": "css", "bid_selector": ".price-ticket__button--sell .price-ticket__price",
        "ask_type": "css", "ask_selector": ".price-ticket__button--buy .price-ticket__price"
    },
    {
        "id": "Oanda", "name": "Oanda", "url": "https://www.oanda.com/bvi-en/cfds/metals/",
        "bid_type": "xpath", "bid_selector": "//tr[.//span[contains(text(), 'Gold')]]/td[2]",
        "ask_type": "xpath", "ask_selector": "//tr[.//span[contains(text(), 'Gold')]]/td[3]"
    }
]


# ==========================================
#    輔助與邏輯
# ==========================================

def parse_price(text_content):
    """
    強大的價格解析函數：從混亂的字串中提取出第一個合理的浮點數
    """
    try:
        if not text_content: return 0.0
        # 1. 替換掉常見的非數字干擾 (保留小數點)
        # 先把換行轉成空格，方便正則處理
        clean_text = str(text_content).replace('\n', ' ').strip()

        # 2. 使用正則表達式尋找數字 (支援 2,000.50 這種格式)
        # 邏輯: 尋找一段包含數字和小數點的字串
        match = re.search(r'[\d,]+\.?\d*', clean_text)
        if match:
            num_str = match.group(0)
            # 移除千分位逗號
            num_str = num_str.replace(',', '')
            # 處理多個小數點的情況 (防呆)
            if num_str.count('.') > 1:
                parts = num_str.split('.')
                num_str = f"{parts[0]}.{parts[1]}"
            return float(num_str)
        return 0.0
    except:
        return 0.0


class UnifiedMonitorThread(QThread):
    log_signal = pyqtSignal(str)
    price_signal = pyqtSignal(str, float, float, str)  # (SourceID, Bid, Ask, Time)
    status_signal = pyqtSignal(str, str)  # (SourceID, Status Msg)
    finished_signal = pyqtSignal()

    def __init__(self, brokers_config):
        super().__init__()
        self.running = True
        self.driver = None
        self.brokers = brokers_config  # 接收動態的券商列表
        self.site_handles = {}  # 儲存視窗 Handle

    def setup_driver(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")  # 隱藏瀏覽器模式
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--log-level=3")
        chrome_options.add_argument("--mute-audio")
        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        self.driver = webdriver.Chrome(options=chrome_options)

    def run(self):
        try:
            if not self.brokers:
                self.log_signal.emit("錯誤: 沒有設定任何券商，無法啟動。")
                return

            self.log_signal.emit("系統核心啟動中 (Chrome Driver)...")
            self.setup_driver()
            wait = WebDriverWait(self.driver, 10)

            # --- 初始化分頁 ---
            # 開啟第一個網址
            first_broker = self.brokers[0]
            self.log_signal.emit(f"初始化主分頁: {first_broker['name']} ...")
            self.driver.get(first_broker['url'])
            self.site_handles[first_broker['id']] = self.driver.current_window_handle

            # 開啟其餘分頁
            for broker in self.brokers[1:]:
                if not self.running: break
                self.log_signal.emit(f"開啟背景分頁: {broker['name']} ...")
                self.driver.execute_script(f"window.open('{broker['url']}', '_blank');")
                self.driver.switch_to.window(self.driver.window_handles[-1])
                self.site_handles[broker['id']] = self.driver.current_window_handle
                time.sleep(1)

            self.log_signal.emit("所有連線建立完成，開始即時監控。")

            # --- 監控迴圈 ---
            while self.running:
                for broker in self.brokers:
                    if not self.running: break
                    b_id = broker['id']

                    try:
                        # 切換視窗
                        if b_id in self.site_handles:
                            self.driver.switch_to.window(self.site_handles[b_id])
                            self.scrape_generic(broker, wait)
                        else:
                            self.status_signal.emit(b_id, "視窗遺失")
                    except Exception as e:
                        # self.log_signal.emit(f"[{broker['name']}] 錯誤: {str(e)}") # Debug用
                        self.status_signal.emit(b_id, "連線異常")

                    time.sleep(0.2)  # 每個分頁間隔

                # 每一大輪休息
                for _ in range(10):  # 1秒
                    if not self.running: break
                    time.sleep(0.1)

        except Exception as e:
            self.log_signal.emit(f"核心錯誤: {str(e)}")
        finally:
            self.stop_driver()
            self.finished_signal.emit()

    def scrape_generic(self, broker, wait):
        """
        通用的爬蟲邏輯：根據設定檔中的 Type 和 Selector 去抓取
        """
        now_str = time.strftime("%H:%M:%S")
        bid, ask = 0.0, 0.0

        try:
            # 1. 抓取 Bid
            bid_ele = self.find_element_dynamic(wait, broker['bid_type'], broker['bid_selector'])
            if bid_ele:
                # 特殊處理: 如果 Bid 和 Ask 是同一個元素 (例如換行分隔)
                text = bid_ele.text
                if broker['bid_selector'] == broker['ask_selector']:
                    lines = text.strip().split('\n')
                    # 嘗試解析多行
                    if len(lines) >= 2:
                        bid = parse_price(lines[-2] if len(lines) > 1 else lines[0])
                        ask = parse_price(lines[-1])
                    else:
                        bid = parse_price(text)
                else:
                    bid = parse_price(text)

            # 2. 抓取 Ask (如果尚未從 Bid 邏輯中取得)
            if ask == 0.0:
                ask_ele = self.find_element_dynamic(wait, broker['ask_type'], broker['ask_selector'])
                if ask_ele:
                    ask = parse_price(ask_ele.text)

            # 3. 發送訊號
            if bid > 0 and ask > 0:
                self.price_signal.emit(broker['id'], bid, ask, now_str)
                self.status_signal.emit(broker['id'], "監控中")
            else:
                self.status_signal.emit(broker['id'], "解析失敗")

        except Exception:
            self.status_signal.emit(broker['id'], "等待數據")

    def find_element_dynamic(self, wait, method, selector):
        """根據方法 (ID/CSS/XPATH) 尋找元素"""
        if not selector: return None
        by_method = By.ID
        if method == "css":
            by_method = By.CSS_SELECTOR
        elif method == "xpath":
            by_method = By.XPATH

        try:
            return wait.until(EC.presence_of_element_located((by_method, selector)))
        except:
            return None

    def stop(self):
        self.running = False

    def stop_driver(self):
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None


# ==========================================
#   UI 樣式與設計
# ==========================================
DARK_STYLESHEET = """
QMainWindow, QWidget { background-color: #1e1e1e; color: #e0e0e0; font-family: "Microsoft JhengHei", sans-serif; }
QTabWidget::pane { border: 1px solid #3c3c3c; background: #2b2b2b; }
QTabBar::tab { background: #3c3c3c; color: #aaa; padding: 8px 20px; margin-right: 2px; }
QTabBar::tab:selected { background: #007acc; color: white; font-weight: bold; }
QTableWidget { background-color: #252526; gridline-color: #3c3c3c; border: none; font-size: 15px; }
QTableWidget::item { padding: 5px; border-bottom: 1px solid #333; }
QHeaderView::section { background-color: #333337; color: #cccccc; padding: 6px; border: none; font-weight: bold; }
QPushButton { background-color: #0e639c; color: white; border: none; padding: 6px 12px; border-radius: 4px; }
QPushButton:hover { background-color: #1177bb; }
QPushButton:disabled { background-color: #444; color: #888; }
QLineEdit, QComboBox, QTextEdit { background-color: #3c3c3c; color: white; border: 1px solid #555; padding: 4px; border-radius: 2px; }
QGroupBox { border: 1px solid #555; border-radius: 5px; margin-top: 20px; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; color: #007acc; }
"""


class GoldMonitorApp(QMainWindow):
    audio_log_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("XAUUSD 黃金監控系統 v11 (全動態版)")
        self.resize(1280, 800)
        self.setStyleSheet(DARK_STYLESHEET)

        self.monitor_thread = None

        # 資料結構
        self.brokers_data = []  # 存放所有券商設定的列表
        self.alert_settings = {}  # 存放警報閾值設定
        self.sound_enabled_map = {}  # 存放音效開關
        self.last_triggered_levels = {}

        # 介面參照
        self.ui_inputs_alert = {}
        self.ui_alert_labels = {}
        self.ui_sound_checks = {}

        self.init_data()  # 載入或初始化資料
        self.init_ui()

        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_realtime_clock)
        self.clock_timer.start(1000)

        self.audio_log_signal.connect(self.log_message)

    def init_data(self):
        """載入設定檔，若無則使用預設"""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.brokers_data = data.get("brokers", DEFAULT_BROKERS)
                    self.alert_settings = data.get("alerts", {})
            except Exception as e:
                print(f"載入失敗: {e}")
                self.brokers_data = DEFAULT_BROKERS
        else:
            self.brokers_data = DEFAULT_BROKERS

        # 初始化音效開關
        for b in self.brokers_data:
            if b['id'] not in self.sound_enabled_map:
                self.sound_enabled_map[b['id']] = True

    def save_to_file(self):
        """儲存所有設定到 JSON"""
        # 1. 從介面更新 Alert 設定到記憶體
        self.update_alert_memory()

        data = {
            "brokers": self.brokers_data,
            "alerts": self.alert_settings
        }
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            self.log_message("設定已儲存 (brokers + alerts)")
            QMessageBox.information(self, "成功", "所有設定已儲存！")
        except Exception as e:
            QMessageBox.critical(self, "錯誤", f"儲存失敗: {e}")

    def update_alert_memory(self):
        """將警報設定頁面的數值寫回 self.alert_settings"""
        for b_id, inputs in self.ui_inputs_alert.items():
            tiers = []
            for item in inputs:
                tiers.append({
                    "diff": item['diff'].text(),
                    "sound": item['sound'].text()
                })

            # 取得音效開關狀態
            is_sound_on = True
            if b_id in self.ui_sound_checks:
                is_sound_on = self.ui_sound_checks[b_id].isChecked()
                self.sound_enabled_map[b_id] = is_sound_on

            self.alert_settings[b_id] = {
                "tiers": tiers,
                "sound_enabled": is_sound_on
            }

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        # Top Bar
        top_bar = QHBoxLayout()
        self.btn_start = QPushButton(" ▶ 啟動監控")
        self.btn_start.setStyleSheet("background-color: #28a745; font-size: 14px; padding: 8px;")
        self.btn_start.clicked.connect(self.start_monitor)

        self.btn_stop = QPushButton(" ■ 停止監控")
        self.btn_stop.setStyleSheet("background-color: #dc3545; font-size: 14px; padding: 8px;")
        self.btn_stop.clicked.connect(self.stop_monitor)
        self.btn_stop.setEnabled(False)

        self.lbl_clock = QLabel("--:--:--")
        self.lbl_clock.setFont(QFont("Consolas", 16, QFont.Weight.Bold))
        self.lbl_clock.setStyleSheet("color: #007acc;")

        top_bar.addWidget(self.btn_start)
        top_bar.addWidget(self.btn_stop)
        top_bar.addStretch()
        top_bar.addWidget(QLabel("系統時間:"))
        top_bar.addWidget(self.lbl_clock)
        main_layout.addLayout(top_bar)

        # Tabs
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # Tab 1: Monitor
        self.tab_monitor = QWidget()
        self.setup_monitor_tab()
        self.tabs.addTab(self.tab_monitor, "即時行情")

        # Tab 2: Alert Settings
        self.tab_settings = QWidget()
        self.setup_settings_tab()
        self.tabs.addTab(self.tab_settings, "點差警報設定")

        # Tab 3: Broker Manager (NEW)
        self.tab_manager = QWidget()
        self.setup_manager_tab()
        self.tabs.addTab(self.tab_manager, "⚙ 券商與HTML管理")

        # Tab 4: Logs
        self.tab_log = QWidget()
        self.setup_log_tab()
        self.tabs.addTab(self.tab_log, "系統日誌")

    # ---------------------------
    #    Tab 1: 儀表板
    # ---------------------------
    def setup_monitor_tab(self):
        layout = QVBoxLayout(self.tab_monitor)
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["券商 (Broker)", "Bid (賣出)", "Ask (買入)", "點差 (Spread)", "最後更新", "狀態", "音效"])

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)

        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        layout.addWidget(self.table)
        self.rebuild_monitor_table()  # 根據資料建立表格

    def rebuild_monitor_table(self):
        """根據 brokers_data 重建表格列"""
        self.table.setRowCount(0)
        self.table.setRowCount(len(self.brokers_data))
        self.ui_sound_checks = {}  # 清空重置

        font_price = QFont("Arial", 14)
        font_spread = QFont("Arial", 16, QFont.Weight.Bold)

        for row, broker in enumerate(self.brokers_data):
            b_id = broker['id']
            # Name
            item_name = QTableWidgetItem(broker['name'])
            item_name.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_name.setFont(QFont("Microsoft JhengHei", 11, QFont.Weight.Bold))
            self.table.setItem(row, 0, item_name)

            # Bid/Ask/Spread/Time/Status
            for col in range(1, 6):
                item = QTableWidgetItem("--")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col in [1, 2]:
                    item.setFont(font_price)
                    item.setForeground(QColor("#4ec9b0")) if col == 1 else item.setForeground(QColor("#f44747"))
                if col == 3:
                    item.setFont(font_spread)
                    item.setForeground(QColor("#dcdcaa"))
                self.table.setItem(row, col, item)

            # Sound Checkbox
            container = QWidget()
            chk_layout = QHBoxLayout(container)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk = QCheckBox()

            # 從 alert_settings 恢復狀態，若無則預設 True
            is_checked = self.alert_settings.get(b_id, {}).get("sound_enabled", True)
            chk.setChecked(is_checked)

            chk.toggled.connect(lambda checked, bid=b_id: self.toggle_sound_state(bid, checked))
            chk_layout.addWidget(chk)
            self.table.setCellWidget(row, 6, container)
            self.ui_sound_checks[b_id] = chk

    def toggle_sound_state(self, b_id, checked):
        self.sound_enabled_map[b_id] = checked

    # ---------------------------
    #    Tab 2: 警報設定
    # ---------------------------
    def setup_settings_tab(self):
        layout = QVBoxLayout(self.tab_settings)

        # 我們需要動態產生這個頁面，所以放一個 ScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.settings_content_widget = QWidget()
        self.settings_form_layout = QVBoxLayout(self.settings_content_widget)
        scroll.setWidget(self.settings_content_widget)

        layout.addWidget(scroll)

        btn_save = QPushButton("💾 儲存所有設定")
        btn_save.setFixedSize(200, 45)
        btn_save.clicked.connect(self.save_to_file)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)

        self.rebuild_settings_ui()

    def rebuild_settings_ui(self):
        """根據 brokers_data 重建警報設定介面"""
        # 清除舊的控件
        for i in reversed(range(self.settings_form_layout.count())):
            w = self.settings_form_layout.itemAt(i).widget()
            if w: w.setParent(None)

        self.ui_inputs_alert = {}
        self.ui_alert_labels = {}

        for broker in self.brokers_data:
            b_id = broker['id']
            group = QGroupBox(f"{broker['name']} ({broker['url'][:30]}...)")
            grid = QGridLayout(group)

            grid.addWidget(QLabel("層級"), 0, 0)
            grid.addWidget(QLabel("當點差大於 >"), 0, 1)
            grid.addWidget(QLabel("音效路徑"), 0, 2)
            grid.addWidget(QLabel("狀態"), 0, 4)

            self.ui_inputs_alert[b_id] = []

            # 載入舊設定
            saved_tiers = self.alert_settings.get(b_id, {}).get("tiers", [])

            for i in range(3):  # 3個層級
                lbl_lvl = QLabel(f"Lv {i + 1}")
                txt_diff = QLineEdit()
                txt_diff.setFixedWidth(80)
                txt_diff.setPlaceholderText("0.5")

                txt_sound = QLineEdit()
                txt_sound.setPlaceholderText("未設定音效")
                txt_sound.setReadOnly(True)

                # 填入舊值
                if i < len(saved_tiers):
                    txt_diff.setText(saved_tiers[i].get("diff", ""))
                    txt_sound.setText(saved_tiers[i].get("sound", ""))

                btn_browse = QPushButton("選取")
                btn_browse.setFixedSize(50, 25)
                btn_browse.clicked.connect(lambda _, t=txt_sound: self.browse_audio_file(t))

                lbl_status = QLabel("● 待機")
                lbl_status.setStyleSheet("color: gray")
                self.ui_alert_labels[(b_id, i)] = lbl_status

                grid.addWidget(lbl_lvl, i + 1, 0)
                grid.addWidget(txt_diff, i + 1, 1)
                grid.addWidget(txt_sound, i + 1, 2)
                grid.addWidget(btn_browse, i + 1, 3)
                grid.addWidget(lbl_status, i + 1, 4)

                self.ui_inputs_alert[b_id].append({"diff": txt_diff, "sound": txt_sound})

            self.settings_form_layout.addWidget(group)

        self.settings_form_layout.addStretch()

    def browse_audio_file(self, line_edit):
        f, _ = QFileDialog.getOpenFileName(self, "選取音效", "", "Audio (*.wav)")
        if f: line_edit.setText(f)

    # ---------------------------
    #    Tab 3: 券商管理 (新增功能)
    # ---------------------------
    def setup_manager_tab(self):
        layout = QHBoxLayout(self.tab_manager)

        # 左側列表
        left_layout = QVBoxLayout()
        self.list_manager = QListWidget()
        self.list_manager.currentRowChanged.connect(self.load_broker_details)
        left_layout.addWidget(QLabel("已設定券商清單:"))
        left_layout.addWidget(self.list_manager)

        btn_add = QPushButton("➕ 新增券商")
        btn_add.clicked.connect(self.add_new_broker)
        btn_add.setStyleSheet("background-color: #007acc;")
        left_layout.addWidget(btn_add)

        layout.addLayout(left_layout, 1)

        # 右側編輯區
        self.grp_edit = QGroupBox("編輯券商詳細資料")
        form = QFormLayout(self.grp_edit)

        self.txt_edit_name = QLineEdit()
        self.txt_edit_url = QLineEdit()

        # Bid Selector
        self.cmb_bid_type = QComboBox()
        self.cmb_bid_type.addItems(["id", "css", "xpath"])
        self.txt_bid_selector = QLineEdit()
        self.txt_bid_selector.setPlaceholderText("例如: #price-bid 或 //div[@id='bid']")

        # Ask Selector
        self.cmb_ask_type = QComboBox()
        self.cmb_ask_type.addItems(["id", "css", "xpath"])
        self.txt_ask_selector = QLineEdit()
        self.txt_ask_selector.setPlaceholderText("例如: #price-ask")

        form.addRow("名稱 (Name):", self.txt_edit_name)
        form.addRow("網址 (URL):", self.txt_edit_url)
        form.addRow("--- HTML 抓取規則 ---", QLabel(""))
        form.addRow("Bid 類型:", self.cmb_bid_type)
        form.addRow("Bid 路徑:", self.txt_bid_selector)
        form.addRow("Ask 類型:", self.cmb_ask_type)
        form.addRow("Ask 路徑:", self.txt_ask_selector)

        btn_box = QHBoxLayout()
        self.btn_update = QPushButton("更新/保存修改")
        self.btn_update.clicked.connect(self.save_broker_details)
        self.btn_update.setStyleSheet("background-color: #28a745;")

        self.btn_delete = QPushButton("刪除此券商")
        self.btn_delete.clicked.connect(self.delete_current_broker)
        self.btn_delete.setStyleSheet("background-color: #dc3545;")

        btn_box.addWidget(self.btn_update)
        btn_box.addWidget(self.btn_delete)
        form.addRow(btn_box)

        # 教學區
        help_text = QTextBrowser()
        help_text.setFixedHeight(150)
        help_text.setHtml("""
        <p style='color:#ccc'><b>如何填寫 HTML 路徑?</b></p>
        <ul>
        <li><b>ID:</b> 網頁元素的 id 屬性 (例: <i>price-val</i>)</li>
        <li><b>CSS:</b> CSS 選擇器 (例: <i>.price-class span</i>)</li>
        <li><b>XPath:</b> 強大的路徑語言 (例: <i>//div[contains(text(),'Gold')]/span</i>)</li>
        </ul>
        <p>※ 系統會自動過濾文字中的貨幣符號，只要選到包含數字的元素即可。</p>
        """)
        form.addRow(help_text)

        layout.addWidget(self.grp_edit, 2)

        self.refresh_manager_list()

    def refresh_manager_list(self):
        """重新整理管理列表"""
        self.list_manager.clear()
        for b in self.brokers_data:
            self.list_manager.addItem(f"{b['name']}")

    def load_broker_details(self, row):
        if row < 0 or row >= len(self.brokers_data): return

        data = self.brokers_data[row]
        self.txt_edit_name.setText(data['name'])
        self.txt_edit_url.setText(data['url'])

        idx_bid = self.cmb_bid_type.findText(data.get('bid_type', 'id'))
        self.cmb_bid_type.setCurrentIndex(idx_bid)
        self.txt_bid_selector.setText(data.get('bid_selector', ''))

        idx_ask = self.cmb_ask_type.findText(data.get('ask_type', 'id'))
        self.cmb_ask_type.setCurrentIndex(idx_ask)
        self.txt_ask_selector.setText(data.get('ask_selector', ''))

    def add_new_broker(self):
        new_data = {
            "id": str(uuid.uuid4())[:8],
            "name": "新券商",
            "url": "https://",
            "bid_type": "css", "bid_selector": "",
            "ask_type": "css", "ask_selector": ""
        }
        self.brokers_data.append(new_data)
        self.refresh_manager_list()
        self.list_manager.setCurrentRow(len(self.brokers_data) - 1)
        self.log_message("已新增一個空白券商，請填寫詳細資料並保存。")

    def save_broker_details(self):
        row = self.list_manager.currentRow()
        if row < 0: return

        # 1. 更新記憶體中的 brokers_data
        target = self.brokers_data[row]
        target['name'] = self.txt_edit_name.text()
        target['url'] = self.txt_edit_url.text()
        target['bid_type'] = self.cmb_bid_type.currentText()
        target['bid_selector'] = self.txt_bid_selector.text()
        target['ask_type'] = self.cmb_ask_type.currentText()
        target['ask_selector'] = self.txt_ask_selector.text()

        # 2. 重新整理列表名稱
        self.list_manager.item(row).setText(target['name'])

        # 3. 儲存檔案
        self.save_to_file()

        # 4. 觸發介面重建 (重要)
        self.rebuild_monitor_table()
        self.rebuild_settings_ui()
        self.log_message(f"券商 [{target['name']}] 資料已更新。")

    def delete_current_broker(self):
        row = self.list_manager.currentRow()
        if row < 0: return

        name = self.brokers_data[row]['name']
        ret = QMessageBox.question(self, "確認刪除", f"確定要刪除 [{name}] 嗎?",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if ret == QMessageBox.StandardButton.Yes:
            del self.brokers_data[row]
            self.refresh_manager_list()
            self.save_to_file()
            self.rebuild_monitor_table()
            self.rebuild_settings_ui()

            # 清空編輯區
            self.txt_edit_name.clear()
            self.txt_edit_url.clear()

    # ---------------------------
    #    Tab 4: 日誌
    # ---------------------------
    def setup_log_tab(self):
        layout = QVBoxLayout(self.tab_log)
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setStyleSheet("background-color: #1e1e1e; color: #ccc; font-family: Consolas;")
        layout.addWidget(self.txt_log)
        btn_clear = QPushButton("清除日誌")
        btn_clear.clicked.connect(self.txt_log.clear)
        layout.addWidget(btn_clear)

    # ---------------------------
    #    核心功能
    # ---------------------------
    def update_realtime_clock(self):
        self.lbl_clock.setText(QTime.currentTime().toString("HH:mm:ss"))

    @pyqtSlot(str)
    def log_message(self, msg):
        ts = time.strftime("%H:%M:%S")
        self.txt_log.append(f"[{ts}] {msg}")

    def start_monitor(self):
        if not self.brokers_data:
            QMessageBox.warning(self, "警告", "沒有券商資料，請先至「券商管理」新增。")
            return

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.grp_edit.setEnabled(False)  # 鎖定編輯功能

        self.log_message(">>> 監控系統啟動")

        # 將設定傳入 Thread
        self.monitor_thread = UnifiedMonitorThread(self.brokers_data)
        self.monitor_thread.log_signal.connect(self.log_message)
        self.monitor_thread.price_signal.connect(self.on_price_update)
        self.monitor_thread.status_signal.connect(self.on_status_update)
        self.monitor_thread.finished_signal.connect(self.on_thread_finished)
        self.monitor_thread.start()

    def stop_monitor(self):
        self.log_message("正在停止所有程序...")
        self.btn_stop.setEnabled(False)
        if self.monitor_thread:
            self.monitor_thread.stop()

    def on_price_update(self, b_id, bid, ask, time_str):
        # 尋找這個 ID 在 Table 中的 Row
        row = -1
        for i, b in enumerate(self.brokers_data):
            if b['id'] == b_id:
                row = i
                break
        if row == -1: return

        spread = abs(ask - bid)
        self.table.item(row, 1).setText(f"{bid:.2f}")
        self.table.item(row, 2).setText(f"{ask:.2f}")
        self.table.item(row, 3).setText(f"{spread:.2f}")
        self.table.item(row, 4).setText(time_str)
        self.table.item(row, 5).setText("監控中")
        self.table.item(row, 5).setForeground(QColor("#4ec9b0"))

        self.check_alert(b_id, spread, row)

    def on_status_update(self, b_id, msg):
        row = -1
        for i, b in enumerate(self.brokers_data):
            if b['id'] == b_id:
                row = i
                break
        if row != -1:
            item = self.table.item(row, 5)
            item.setText(msg)
            item.setForeground(QColor("#f44747") if msg != "監控中" else QColor("#4ec9b0"))

    def check_alert(self, b_id, spread, row_idx):
        # 檢查閾值
        inputs = self.ui_inputs_alert.get(b_id, [])
        highest_lvl = -1
        sound_path = None

        for i, item in enumerate(inputs):
            try:
                val = item['diff'].text()
                thresh = float(val) if val else 999.0
            except:
                thresh = 999.0

            lbl = self.ui_alert_labels.get((b_id, i))
            if lbl:
                if spread >= thresh and thresh > 0:
                    lbl.setText("● 觸發")
                    lbl.setStyleSheet("color: #ff3333; font-weight: bold;")
                    highest_lvl = i
                    sound_path = item['sound'].text()
                else:
                    lbl.setText("● 待機")
                    lbl.setStyleSheet("color: gray;")

        # 更新表格視覺
        item_spread = self.table.item(row_idx, 3)
        if highest_lvl >= 0:
            item_spread.setBackground(QColor("#660000"))
        else:
            item_spread.setBackground(QColor("#252526"))

        # 播放音效
        last = self.last_triggered_levels.get(b_id, -1)
        is_sound_on = self.sound_enabled_map.get(b_id, True)

        if highest_lvl > last:
            self.log_message(f"[{self.brokers_data[row_idx]['name']}] 警報觸發! 點差: {spread:.2f}")
            if sound_path and os.path.exists(sound_path) and is_sound_on:
                threading.Thread(target=self.play_sound, args=(sound_path,), daemon=True).start()

        self.last_triggered_levels[b_id] = highest_lvl

    def play_sound(self, path):
        try:
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_NODEFAULT)
        except:
            pass

    def on_thread_finished(self):
        self.log_message(">>> 監控已停止")
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.grp_edit.setEnabled(True)  # 解鎖編輯
        self.monitor_thread = None

    def closeEvent(self, event):
        if self.monitor_thread and self.monitor_thread.isRunning():
            reply = QMessageBox.question(self, '確認退出', '監控正在執行，確定要強制關閉嗎？',
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.stop_monitor()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = GoldMonitorApp()
    window.show()
    sys.exit(app.exec())