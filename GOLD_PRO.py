import sys
import os
import json
import time
import threading
import re
import datetime
import winsound

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QTextEdit, QTabWidget, QGridLayout,
                             QFileDialog, QMessageBox, QTableWidget,
                             QTableWidgetItem, QHeaderView, QSplitter,
                             QListWidget, QStackedWidget, QFrame, QGroupBox, QTextBrowser)
from PyQt6.QtCore import pyqtSignal, QThread, Qt, QTimer, QTime, pyqtSlot, QSize
from PyQt6.QtGui import QFont, QColor, QBrush, QIcon

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# --- 設定檔名稱 ---
CONFIG_FILE = "monitor_config_v9_pro.json"


# ==========================================
#   輔助與邏輯
# ==========================================

def parse_price(price_str):
    """移除逗號與非數字字符，轉換為 float"""
    try:
        if not price_str: return 0.0
        clean_str = re.sub(r'[^\d.]', '', str(price_str))
        return float(clean_str)
    except:
        return 0.0


class UnifiedMonitorThread(QThread):
    log_signal = pyqtSignal(str)
    price_signal = pyqtSignal(str, float, float, str)  # (Source, Bid, Ask, Time)
    status_signal = pyqtSignal(str, str)  # (Source, Status Msg)
    finished_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.running = True
        self.driver = None
        self.sites = {
            "WF": {"url": "https://www.wfbullion.com/", "handle": None, "name": "永豐金業"},
            "IG": {"url": "https://www.ig.com/cn/commodities/markets-commodities/gold", "handle": None,
                   "name": "IG Markets"},
            "Oanda": {"url": "https://www.oanda.com/bvi-en/cfds/metals/", "handle": None, "name": "Oanda"},
            "Forex": {"url": "https://www.forex.com/cn/markets-to-trade/precious-metals/", "handle": None,
                      "name": "Forex.com"},
            "MW": {"url": "https://www.mw801.com/", "handle": None, "name": "英皇金業"},
            "Axi": {"url": "https://www.axi.com/int/trade/cfds/commodities", "handle": None, "name": "Axi"},
            "Capital": {"url": "https://capital.com/zh-hant/markets/commodities", "handle": None,
                        "name": "Capital.com"},
            "KVB": {"url": "https://www.kvbplus.com/prime/product/commodities", "handle": None, "name": "KVB Plus"},
            "VT": {
                "url": "https://www.vtmarketsglobal.com/precious-metals/?_sasdk=dMTlhZmRkY2IyMTI5NTEtMDA2ODAzZWVkY2Y0MjE3LTI2MDYxYTUxLTEzMjcxMDQtMTlhZmRkY2IyMTMxMTk1",
                "handle": None, "name": "VT Markets"},
            "MF": {"url": "https://www.mega-fusion.com/tc/trading/instruments/precious-metals", "handle": None,
                   "name": "Mega Fusion"},
        }

    def setup_driver(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")  # 生產環境建議開啟 Headless
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--log-level=3")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--mute-audio")
        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        self.driver = webdriver.Chrome(options=chrome_options)

    def run(self):
        try:
            self.log_signal.emit("系統核心啟動中 (Chrome Driver)...")
            self.setup_driver()
            wait = WebDriverWait(self.driver, 10)

            site_keys = list(self.sites.keys())
            first_key = site_keys[0]

            self.log_signal.emit(f"初始化主分頁: {self.sites[first_key]['name']} ...")
            self.driver.get(self.sites[first_key]["url"])
            self.sites[first_key]["handle"] = self.driver.current_window_handle

            for key in site_keys[1:]:
                if not self.running: break
                self.log_signal.emit(f"開啟背景分頁: {self.sites[key]['name']} ...")
                self.driver.execute_script(f"window.open('{self.sites[key]['url']}', '_blank');")
                self.driver.switch_to.window(self.driver.window_handles[-1])
                self.sites[key]["handle"] = self.driver.current_window_handle
                time.sleep(1)

            self.log_signal.emit("所有連線建立完成，開始即時監控。")

            while self.running:
                for key in site_keys:
                    if not self.running: break
                    try:
                        self.driver.switch_to.window(self.sites[key]["handle"])
                        self.scrape_site(key, wait)
                    except Exception:
                        self.status_signal.emit(key, "連線異常")
                    time.sleep(0.2)

                    # 每一輪休息
                for _ in range(20):
                    if not self.running: break
                    time.sleep(0.1)

        except Exception as e:
            self.log_signal.emit(f"核心錯誤: {str(e)}")
        finally:
            self.stop_driver()
            self.finished_signal.emit()

    def scrape_site(self, key, wait):
        now_str = time.strftime("%H:%M:%S")
        try:
            bid, ask = 0.0, 0.0

            if key == "WF":
                el = wait.until(EC.presence_of_element_located((By.ID, "pm-llg")))
                lines = el.text.strip().split('\n')
                if len(lines) > 3:
                    bid = parse_price(lines[2])
                    ask = parse_price(lines[3].split(' ')[0])
            elif key == "IG":
                bid = parse_price(wait.until(EC.visibility_of_element_located(
                    (By.CSS_SELECTOR, ".price-ticket__button--sell .price-ticket__price"))).text)
                ask = parse_price(wait.until(EC.visibility_of_element_located(
                    (By.CSS_SELECTOR, ".price-ticket__button--buy .price-ticket__price"))).text)
            elif key == "Oanda":
                row = wait.until(EC.presence_of_element_located((By.XPATH, "//tr[.//span[contains(text(), 'Gold')]]")))
                cells = row.find_elements(By.TAG_NAME, "td")
                bid, ask = parse_price(cells[1].text), parse_price(cells[2].text)
            elif key == "Forex":
                row = wait.until(EC.presence_of_element_located((By.XPATH, "//tr[.//a[@title='XAU USD']]")))
                bid = parse_price(row.find_element(By.CSS_SELECTOR, ".mp__td--Bid").text)
                ask = parse_price(row.find_element(By.CSS_SELECTOR, ".mp__td--Offer").text)
            elif key == "MW":
                bid = parse_price(wait.until(EC.presence_of_element_located((By.ID, "XAUUSD1"))).text)
                ask = parse_price(wait.until(EC.presence_of_element_located((By.ID, "XAUUSD2"))).text)
            elif key == "Axi":
                row = wait.until(EC.presence_of_element_located((By.ID, "XAUUSD"))).find_element(By.XPATH,
                                                                                                 "./ancestor::tr")
                cells = row.find_elements(By.CLASS_NAME, "price")
                bid, ask = parse_price(cells[0].text), parse_price(cells[1].text)
            elif key == "Capital":
                btn = wait.until(EC.presence_of_element_located((By.XPATH,
                                                                 "//span[contains(text(), 'Gold Spot') or contains(text(), '現貨黃金')]/ancestor::button")))
                txt = btn.text.split('\n')
                bid, ask = parse_price(txt[2]), parse_price(txt[3])
            elif key == "KVB":
                el = wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'XAUUSD')]")))
                row = el.find_element(By.XPATH, "./ancestor::tr")
                els = row.find_elements(By.XPATH, ".//div[contains(@class, 'style_price')]")
                bid, ask = parse_price(els[0].text), parse_price(els[1].text)
            elif key == "VT":
                row = wait.until(EC.presence_of_element_located((By.XPATH, "//td[@data-symbol='XAUUSD']/ancestor::tr")))
                bid_el, ask_el = row.find_element(By.XPATH, ".//td[contains(@class, 'bid_text')]"), row.find_element(
                    By.XPATH, ".//td[contains(@class, 'ask_text')]")
                b_val, a_val = bid_el.get_attribute("data"), ask_el.get_attribute("data")
                bid, ask = parse_price(b_val if b_val else bid_el.text), parse_price(a_val if a_val else ask_el.text)
            elif key == "MF":
                iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
                found = False
                for frame in iframes:
                    try:
                        self.driver.switch_to.frame(frame)
                        if len(self.driver.find_elements(By.ID, "ticker_bid_375")) > 0:
                            found = True;
                            break
                        self.driver.switch_to.default_content()
                    except:
                        self.driver.switch_to.default_content()

                b_el = wait.until(EC.visibility_of_element_located((By.ID, "ticker_bid_375")))
                a_el = wait.until(EC.visibility_of_element_located((By.ID, "ticker_ask_375")))
                b_txt = self.driver.execute_script("return arguments[0].textContent;", b_el)
                a_txt = self.driver.execute_script("return arguments[0].textContent;", a_el)
                bid, ask = parse_price(b_txt), parse_price(a_txt)
                if found: self.driver.switch_to.default_content()

            if bid > 0 and ask > 0:
                self.price_signal.emit(key, bid, ask, now_str)
                self.status_signal.emit(key, "監控中")
            else:
                self.status_signal.emit(key, "數據異常")

        except Exception:
            try:
                self.driver.switch_to.default_content()
            except:
                pass
            self.status_signal.emit(key, "等待數據")

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
#   UI 樣式與設計 (Modern Dark Theme)
# ==========================================

DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #1e1e1e;
    color: #e0e0e0;
    font-family: "Segoe UI", "Microsoft JhengHei", sans-serif;
}
QTabWidget::pane {
    border: 1px solid #3c3c3c;
    background: #2b2b2b;
}
QTabBar::tab {
    background: #3c3c3c;
    color: #aaa;
    padding: 8px 20px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #007acc;
    color: white;
    font-weight: bold;
}
QTableWidget {
    background-color: #252526;
    gridline-color: #3c3c3c;
    border: none;
    font-size: 15px;
}
QTableWidget::item {
    padding: 5px;
    border-bottom: 1px solid #333;
}
QHeaderView::section {
    background-color: #333337;
    color: #cccccc;
    padding: 6px;
    border: none;
    font-weight: bold;
}
QPushButton {
    background-color: #0e639c;
    color: white;
    border: none;
    padding: 8px 15px;
    border-radius: 4px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #1177bb;
}
QPushButton:disabled {
    background-color: #444;
    color: #888;
}
QLineEdit {
    background-color: #3c3c3c;
    color: white;
    border: 1px solid #555;
    padding: 4px;
    border-radius: 2px;
}
QListWidget {
    background-color: #252526;
    border: 1px solid #3c3c3c;
}
QListWidget::item {
    padding: 10px;
}
QListWidget::item:selected {
    background-color: #37373d;
    border-left: 3px solid #007acc;
}
QGroupBox {
    border: 1px solid #555;
    border-radius: 5px;
    margin-top: 20px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 3px;
    color: #007acc;
}
QTextBrowser {
    background-color: #252526;
    color: #e0e0e0;
    border: none;
    font-size: 14px;
    padding: 10px;
}
"""


class GoldMonitorApp(QMainWindow):
    audio_log_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("XAUUSD黃金監控系統")
        self.resize(1100, 700)
        self.setStyleSheet(DARK_STYLESHEET)

        self.monitor_thread = None
        self.setting_inputs = {}
        self.alert_status_labels = {}
        self.last_triggered_levels = {}

        # 定義券商列表與顯示名稱 (已更新名稱)
        self.brokers_map = {
            "WF": "永豐金業(Wing Fung)",
            "IG": "IG Markets",
            "Oanda": "Oanda",
            "Forex": "Forex.com",
            "MW": "英皇金業(Emperor)",
            "Axi": "Axi",
            "Capital": "Capital.com",
            "KVB": "KVB Plus",
            "VT": "VT Markets",
            "MF": "Mega Fusion"
        }
        self.broker_keys = list(self.brokers_map.keys())
        self.row_map = {key: i for i, key in enumerate(self.broker_keys)}

        self.init_ui()

        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_realtime_clock)
        self.clock_timer.start(1000)

        self.audio_log_signal.connect(self.log_message)
        self.load_settings()

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # --- 頂部控制列 ---
        top_bar = QHBoxLayout()

        self.btn_start = QPushButton(" 啟動監控")
        self.btn_start.setStyleSheet("background-color: #28a745;")
        self.btn_start.clicked.connect(self.start_monitor)

        self.btn_stop = QPushButton(" 停止監控")
        self.btn_stop.setStyleSheet("background-color: #dc3545;")
        self.btn_stop.clicked.connect(self.stop_monitor)
        self.btn_stop.setEnabled(False)

        self.lbl_clock = QLabel("--:--:--")
        self.lbl_clock.setFont(QFont("Consolas", 16, QFont.Weight.Bold))
        self.lbl_clock.setStyleSheet("color: #007acc;")

        top_bar.addWidget(self.btn_start)
        top_bar.addWidget(self.btn_stop)
        top_bar.addStretch()
        top_bar.addWidget(QLabel("系統時間:"))  # 改為系統時間
        top_bar.addWidget(self.lbl_clock)
        main_layout.addLayout(top_bar)

        # --- 主要分頁區 ---
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # Tab 1: 儀表板
        self.tab_monitor = QWidget()
        self.setup_monitor_tab()
        self.tabs.addTab(self.tab_monitor, "即時行情看板")

        # Tab 2: 警報設定
        self.tab_settings = QWidget()
        self.setup_settings_tab()
        self.tabs.addTab(self.tab_settings, "點差警報設定")  # 改為點差警報設定

        # Tab 3: 綜合網址 (新增)
        self.tab_urls = QWidget()
        self.setup_urls_tab()
        self.tabs.addTab(self.tab_urls, "綜合網址")

        # Tab 4: 系統日誌
        self.tab_log = QWidget()
        self.setup_log_tab()
        self.tabs.addTab(self.tab_log, "執行日誌")

    # ---------------------------
    #  Tab 1: 表格化儀表板
    # ---------------------------
    def setup_monitor_tab(self):
        layout = QVBoxLayout(self.tab_monitor)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        # 標題欄位更新: Bid(賣出), Ask(買入)
        self.table.setHorizontalHeaderLabels(
            ["券商 (Broker)", "Bid (賣出)", "Ask (買入)", "點差 (Spread)", "最後更新", "狀態"])
        self.table.setRowCount(len(self.broker_keys))

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)

        font_price = QFont("Arial", 14)
        font_spread = QFont("Arial", 16, QFont.Weight.Bold)

        for row, key in enumerate(self.broker_keys):
            item_name = QTableWidgetItem(self.brokers_map[key])
            item_name.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_name.setFont(QFont("Microsoft JhengHei", 11, QFont.Weight.Bold))
            self.table.setItem(row, 0, item_name)

            item_bid = QTableWidgetItem("0.00")
            item_bid.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_bid.setForeground(QColor("#4ec9b0"))
            item_bid.setFont(font_price)
            self.table.setItem(row, 1, item_bid)

            item_ask = QTableWidgetItem("0.00")
            item_ask.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_ask.setForeground(QColor("#f44747"))
            item_ask.setFont(font_price)
            self.table.setItem(row, 2, item_ask)

            item_spread = QTableWidgetItem("0.00")
            item_spread.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_spread.setForeground(QColor("#dcdcaa"))
            item_spread.setFont(font_spread)
            self.table.setItem(row, 3, item_spread)

            item_time = QTableWidgetItem("--:--:--")
            item_time.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 4, item_time)

            item_status = QTableWidgetItem("等待中")
            item_status.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_status.setForeground(QColor("gray"))
            self.table.setItem(row, 5, item_status)

        layout.addWidget(self.table)

    # ---------------------------
    #  Tab 2: 側邊欄式設定
    # ---------------------------
    def setup_settings_tab(self):
        layout = QHBoxLayout(self.tab_settings)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.list_brokers = QListWidget()
        self.list_brokers.setFixedWidth(200)
        self.list_brokers.addItems([self.brokers_map[k] for k in self.broker_keys])

        self.stack_settings = QStackedWidget()

        for key in self.broker_keys:
            page = self.create_setting_page(key)
            self.stack_settings.addWidget(page)

        self.list_brokers.currentRowChanged.connect(self.stack_settings.setCurrentIndex)
        self.list_brokers.setCurrentRow(0)

        splitter.addWidget(self.list_brokers)
        splitter.addWidget(self.stack_settings)

        layout.addWidget(splitter)

        btn_layout = QHBoxLayout()
        btn_save = QPushButton("💾 儲存所有設定")
        btn_save.setFixedSize(150, 40)
        btn_save.clicked.connect(self.save_settings)

        main_layout = QVBoxLayout()
        main_layout.addWidget(splitter)
        main_layout.addLayout(btn_layout)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_save)

        if self.tab_settings.layout():
            QWidget().setLayout(self.tab_settings.layout())
        self.tab_settings.setLayout(main_layout)

    def create_setting_page(self, key):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel(f"設定: {self.brokers_map[key]}")
        title.setFont(QFont("Microsoft JhengHei", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #007acc; margin-bottom: 10px;")
        layout.addWidget(title)

        group = QGroupBox("點差警報觸發規則")
        grid = QGridLayout(group)
        grid.addWidget(QLabel("層級"), 0, 0)
        grid.addWidget(QLabel("當點差大於 (Spread >)"), 0, 1)
        grid.addWidget(QLabel("播放音效檔案"), 0, 2)
        grid.addWidget(QLabel("目前狀態"), 0, 4)

        self.setting_inputs[key] = []
        for i in range(3):
            lbl_lvl = QLabel(f"Level {i + 1}")
            lbl_lvl.setStyleSheet("font-weight: bold; color: #aaa;")

            txt_diff = QLineEdit()
            txt_diff.setPlaceholderText("0.50")
            txt_diff.setFixedWidth(80)

            txt_sound = QLineEdit()
            txt_sound.setReadOnly(True)
            txt_sound.setPlaceholderText("無音效")

            btn_browse = QPushButton("選取")
            btn_browse.setFixedSize(60, 25)
            btn_browse.setStyleSheet("background-color: #444; font-size: 12px;")
            btn_browse.clicked.connect(lambda chk, t=txt_sound: self.browse_file(t))

            lbl_status = QLabel("● 待機")
            lbl_status.setStyleSheet("color: gray")
            self.alert_status_labels[(key, i)] = lbl_status

            grid.addWidget(lbl_lvl, i + 1, 0)
            grid.addWidget(txt_diff, i + 1, 1)
            grid.addWidget(txt_sound, i + 1, 2)
            grid.addWidget(btn_browse, i + 1, 3)
            grid.addWidget(lbl_status, i + 1, 4)

            self.setting_inputs[key].append({"diff": txt_diff, "sound": txt_sound})

        layout.addWidget(group)
        return page

    # ---------------------------
    #  Tab 3: 綜合網址 (新增)
    # ---------------------------
    def setup_urls_tab(self):
        layout = QVBoxLayout(self.tab_urls)

        # 使用 QTextBrowser 支援 HTML 連結
        text_browser = QTextBrowser()
        text_browser.setOpenExternalLinks(True)  # 允許點擊連結開啟瀏覽器

        # 準備 HTML 內容
        html_content = """
        <style>
            h2 { color: #007acc; }
            p { margin: 10px 0; font-size: 15px; }
            a { color: #4ec9b0; text-decoration: none; }
            a:hover { text-decoration: underline; color: #9cdcfe; }
        </style>
        <h2>綜合網址清單 (點擊開啟)</h2>
        <p><b>WF (永豐金業):</b> <a href="https://www.wfbullion.com/">https://www.wfbullion.com/</a></p>
        <p><b>IG Markets:</b> <a href="https://www.ig.com/cn/commodities/markets-commodities/gold">https://www.ig.com/cn/commodities/markets-commodities/gold</a></p>
        <p><b>Oanda:</b> <a href="https://www.oanda.com/bvi-en/cfds/metals/">https://www.oanda.com/bvi-en/cfds/metals/</a></p>
        <p><b>Forex.com:</b> <a href="https://www.forex.com/cn/markets-to-trade/precious-metals/">https://www.forex.com/cn/markets-to-trade/precious-metals/</a></p>
        <p><b>MW801 (英皇金業):</b> <a href="https://www.mw801.com/">https://www.mw801.com/</a></p>
        <p><b>Axi:</b> <a href="https://www.axi.com/int/trade/cfds/commodities">https://www.axi.com/int/trade/cfds/commodities</a></p>
        <p><b>Capital.com:</b> <a href="https://capital.com/zh-hant/markets/commodities">https://capital.com/zh-hant/markets/commodities</a></p>
        <p><b>KVB Plus:</b> <a href="https://www.kvbplus.com/prime/product/commodities">https://www.kvbplus.com/prime/product/commodities</a></p>
        <p><b>VT Markets:</b> <a href="https://www.vtmarketsglobal.com/precious-metals/?_sasdk=dMTlhZmRkY2IyMTI5NTEtMDA2ODAzZWVkY2Y0MjE3LTI2MDYxYTUxLTEzMjcxMDQtMTlhZmRkY2IyMTMxMTk1">https://www.vtmarketsglobal.com/precious-metals/</a></p>
        <p><b>Mega Fusion:</b> <a href="https://www.mega-fusion.com/tc/trading/instruments/precious-metals">https://www.mega-fusion.com/tc/trading/instruments/precious-metals</a></p>
        """

        text_browser.setHtml(html_content)
        layout.addWidget(text_browser)

    # ---------------------------
    #  Tab 4: 日誌
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
    #  核心邏輯
    # ---------------------------

    def update_realtime_clock(self):
        self.lbl_clock.setText(QTime.currentTime().toString("HH:mm:ss"))

    def browse_file(self, line_edit):
        f, _ = QFileDialog.getOpenFileName(self, "選取音效", "", "Audio (*.wav)")
        if f: line_edit.setText(f)

    @pyqtSlot(str)
    def log_message(self, msg):
        ts = time.strftime("%H:%M:%S")
        self.txt_log.append(f"[{ts}] {msg}")
        self.txt_log.verticalScrollBar().setValue(self.txt_log.verticalScrollBar().maximum())

    def start_monitor(self):
        self.save_settings()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.last_triggered_levels = {}
        self.log_message(">>> 監控系統啟動")

        self.monitor_thread = UnifiedMonitorThread()
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

    def on_price_update(self, source, bid, ask, time_str):
        if source not in self.row_map: return

        row = self.row_map[source]
        spread = abs(ask - bid)

        # 更新表格
        self.table.item(row, 1).setText(f"{bid:.2f}")
        self.table.item(row, 2).setText(f"{ask:.2f}")

        item_spread = self.table.item(row, 3)
        item_spread.setText(f"{spread:.2f}")

        self.table.item(row, 4).setText(time_str)
        self.table.item(row, 5).setText("監控中")
        self.table.item(row, 5).setForeground(QColor("#4ec9b0"))  # Green

        # 處理警報
        self.check_alert(source, spread, row)

    def on_status_update(self, source, msg):
        if source not in self.row_map: return
        row = self.row_map[source]
        item = self.table.item(row, 5)
        item.setText(msg)
        if "錯誤" in msg or "異常" in msg:
            item.setForeground(QColor("#f44747"))  # Red
        else:
            item.setForeground(QColor("gray"))

    def check_alert(self, source, spread, row_idx):
        inputs = self.setting_inputs.get(source, [])
        highest_lvl = -1
        sound_path = None

        # 檢查警報層級
        for i, item in enumerate(inputs):
            try:
                thresh = float(item['diff'].text())
            except:
                thresh = 999.0

            lbl = self.alert_status_labels.get((source, i))
            if thresh > 0 and spread >= thresh:
                lbl.setText("● 觸發")
                lbl.setStyleSheet("color: #ff3333; font-weight: bold;")
                highest_lvl = i
                sound_path = item['sound'].text()
            else:
                lbl.setText("● 待機")
                lbl.setStyleSheet("color: gray;")

        # 視覺反饋
        spread_item = self.table.item(row_idx, 3)
        if highest_lvl >= 0:
            spread_item.setBackground(QColor("#660000"))  # 深紅背景
        else:
            spread_item.setBackground(QColor("#252526"))  # 恢復原色

        # 音效邏輯
        last = self.last_triggered_levels.get(source, -1)
        if highest_lvl > last:
            self.log_message(f"[{source}] 警報觸發! 點差: {spread:.2f}")
            if sound_path and os.path.exists(sound_path):
                threading.Thread(target=self.play_sound, args=(sound_path,), daemon=True).start()

        self.last_triggered_levels[source] = highest_lvl

    def play_sound(self, path):
        try:
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_NODEFAULT)
        except:
            pass

    def on_thread_finished(self):
        self.log_message(">>> 監控已停止")
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.monitor_thread = None

    def save_settings(self):
        data = {}
        for key, inputs in self.setting_inputs.items():
            data[key] = []
            for item in inputs:
                data[key].append({"diff": item['diff'].text(), "sound": item['sound'].text()})
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            self.log_message("設定已保存至硬碟")
        except Exception as e:
            self.log_message(f"儲存失敗: {e}")

    def load_settings(self):
        if not os.path.exists(CONFIG_FILE): return
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for key, tiers in data.items():
                if key in self.setting_inputs:
                    ui_inputs = self.setting_inputs[key]
                    for i, t_data in enumerate(tiers):
                        if i < len(ui_inputs):
                            ui_inputs[i]['diff'].setText(t_data.get('diff', ''))
                            ui_inputs[i]['sound'].setText(t_data.get('sound', ''))
        except:
            pass

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
            self.save_settings()
            event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = GoldMonitorApp()
    window.show()
    sys.exit(app.exec())