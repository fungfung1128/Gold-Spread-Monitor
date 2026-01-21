# -*- coding: utf-8 -*-
"""
XAUUSD 點差監控專業版 v11.8 (全背景靜默執行版)
修改記錄：
1. [設定] 強制所有瀏覽器（包含 WF）進入 Headless (無頭) 模式，不再彈出視窗。
2. [保留] 圖片載入功能開啟，確保 WF 在背景也能正確渲染報價。
3. [移除] 移除 KVB 配置。
"""

import sys
import os
import json
import time
import threading
import re
import datetime
import winsound
import math

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QTextEdit, QTabWidget, QGridLayout,
                             QFileDialog, QMessageBox, QTableWidget,
                             QTableWidgetItem, QHeaderView, QSplitter,
                             QListWidget, QStackedWidget, QFrame, QGroupBox, QTextBrowser,
                             QCheckBox)
from PyQt6.QtCore import pyqtSignal, QThread, Qt, QTimer, QTime, pyqtSlot, QSize, QMutex
from PyQt6.QtGui import QFont, QColor, QBrush, QIcon

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# --- 設定檔名稱 ---
CONFIG_FILE = "monitor_config_v11.json"

# --- 效能設定 ---
WORKER_COUNT = 2  # 啟動 2 個瀏覽器分工
HEADLESS_MODE = True  # 開啟隱藏模式 (全站點適用)


# ==========================================
#  輔助與邏輯
# ==========================================

def parse_price(price_str):
    try:
        if not price_str: return 0.0
        first_part = str(price_str).replace(',', '').strip().split('\n')[0].split(' ')[0]
        clean_str = re.sub(r'[^\d.]', '', first_part)
        if clean_str.count('.') > 1:
            parts = clean_str.split('.')
            clean_str = f"{parts[0]}.{parts[1]}"
        return float(clean_str) if clean_str else 0.0
    except:
        return 0.0


class BrowserWorker(QThread):
    log_signal = pyqtSignal(str)
    price_signal = pyqtSignal(str, float, float, str)
    status_signal = pyqtSignal(str, str)
    finished_signal = pyqtSignal()

    def __init__(self, worker_id, assigned_sites):
        super().__init__()
        self.worker_id = worker_id
        self.assigned_sites = assigned_sites
        self.running = True
        self.driver = None

    def setup_driver(self):
        chrome_options = Options()

        # [關鍵修改] 全域隱藏視窗設定
        if HEADLESS_MODE:
            chrome_options.add_argument("--headless=new")

        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--mute-audio")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

        # 保持圖片載入開啟 (註解掉這行)，確保 WF 在背景也能讀取數據
        # chrome_options.add_argument("--blink-settings=imagesEnabled=false")

        # 使用 normal 策略確保 JS 完整執行
        chrome_options.page_load_strategy = 'normal'

        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.set_page_load_timeout(60)

    def run(self):
        try:
            # 顯示目前模式
            mode_str = "背景靜默模式" if HEADLESS_MODE else "顯示視窗模式"
            self.log_signal.emit(
                f"[Worker-{self.worker_id}] 啟動引擎 [{mode_str}]，負責: {list(self.assigned_sites.keys())}")

            self.setup_driver()
            wait = WebDriverWait(self.driver, 10)

            site_keys = list(self.assigned_sites.keys())
            if not site_keys: return

            first_key = site_keys[0]
            self.driver.get(self.assigned_sites[first_key]["url"])
            self.assigned_sites[first_key]["handle"] = self.driver.current_window_handle

            for key in site_keys[1:]:
                if not self.running: break
                self.driver.execute_script(f"window.open('{self.assigned_sites[key]['url']}', '_blank');")
                self.driver.switch_to.window(self.driver.window_handles[-1])
                self.assigned_sites[key]["handle"] = self.driver.current_window_handle
                time.sleep(1)

            self.log_signal.emit(f"[Worker-{self.worker_id}] 就緒，開始輪詢。")

            while self.running:
                for key in site_keys:
                    if not self.running: break
                    try:
                        self.driver.switch_to.window(self.assigned_sites[key]["handle"])
                        self.scrape_site(key, wait)
                    except Exception as e:
                        self.status_signal.emit(key, "連線/切換異常")

                    QThread.msleep(50)

                for _ in range(5):
                    if not self.running: break
                    QThread.msleep(100)

        except Exception as e:
            self.log_signal.emit(f"[Worker-{self.worker_id}] 核心錯誤: {str(e)}")
        finally:
            self.stop_driver()
            self.finished_signal.emit()

    def scrape_site(self, key, wait):
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        try:
            bid, ask = 0.0, 0.0
            method_name = f"scrape_{key}"
            if hasattr(self, method_name):
                func = getattr(self, method_name)
                bid, ask = func(wait)
            else:
                self.status_signal.emit(key, "未定義解析")
                return

            if bid > 0 and ask > 0:
                self.price_signal.emit(key, bid, ask, now_str)
                self.status_signal.emit(key, "監控中")
            else:
                self.status_signal.emit(key, "數據異常")

        except Exception as e:
            try:
                self.driver.switch_to.default_content()
            except:
                pass

    # ==========================
    #  各網站解析邏輯
    # ==========================
    def scrape_WF(self, wait):
        """
        WF 即使在 Headless 模式下，只要圖片載入開啟且 page_load_strategy 為 normal，
        通常仍可抓取到文字。
        """
        try:
            # 尋找報價跑馬燈容器
            el = wait.until(EC.visibility_of_element_located((By.ID, "pm-llg")))

            # 溫柔捲動
            self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", el)

            text = self.driver.execute_script("return arguments[0].innerText;", el)
            lines = text.strip().split('\n')

            # WF 格式: 名稱 / 代碼 / Bid / Ask
            if len(lines) > 3:
                return parse_price(lines[2]), parse_price(lines[3])
        except:
            pass
        return 0.0, 0.0

    def scrape_IG(self, wait):
        bid_el = wait.until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, ".price-ticket__button--sell .price-ticket__price")))
        ask_el = wait.until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, ".price-ticket__button--buy .price-ticket__price")))
        return parse_price(bid_el.text), parse_price(ask_el.text)

    def scrape_Forex(self, wait):
        row = wait.until(EC.presence_of_element_located((By.XPATH, "//tr[.//a[@title='XAU USD']]")))
        return parse_price(row.find_element(By.CSS_SELECTOR, ".mp__td--Bid").text), \
            parse_price(row.find_element(By.CSS_SELECTOR, ".mp__td--Offer").text)

    def scrape_MW(self, wait):
        return parse_price(wait.until(EC.presence_of_element_located((By.ID, "XAUUSD1"))).text), \
            parse_price(wait.until(EC.presence_of_element_located((By.ID, "XAUUSD2"))).text)

    def scrape_Axi(self, wait):
        row = wait.until(EC.presence_of_element_located((By.ID, "XAUUSD"))).find_element(By.XPATH, "./ancestor::tr")
        cells = row.find_elements(By.CLASS_NAME, "price")
        return parse_price(cells[0].text), parse_price(cells[1].text)

    def scrape_Capital(self, wait):
        btn = wait.until(EC.presence_of_element_located(
            (By.XPATH, "//span[contains(text(), 'Gold Spot') or contains(text(), '現貨黃金')]/ancestor::button")))
        txt = self.driver.execute_script("return arguments[0].innerText;", btn).split('\n')
        return parse_price(txt[2]), parse_price(txt[3])

    def scrape_VT(self, wait):
        row = wait.until(EC.presence_of_element_located((By.XPATH, "//td[@data-symbol='XAUUSD']/ancestor::tr")))
        bid_el = row.find_element(By.XPATH, ".//td[contains(@class, 'bid_text')]")
        ask_el = row.find_element(By.XPATH, ".//td[contains(@class, 'ask_text')]")
        b_val, a_val = bid_el.get_attribute("data"), ask_el.get_attribute("data")
        return parse_price(b_val if b_val else bid_el.text), parse_price(a_val if a_val else ask_el.text)

    def scrape_Markets(self, wait):
        bid_el = wait.until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, ".instrument-buttons .cta-sell span[data-sell]")))
        ask_el = wait.until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, ".instrument-buttons .cta-buy span[data-buy]")))
        return parse_price(bid_el.text), parse_price(ask_el.text)

    def scrape_IFC(self, wait):
        bid_el = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".current_instrument_bid")))
        ask_el = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".current_instrument_ask")))
        return parse_price(bid_el.text), parse_price(ask_el.text)

    def scrape_CMC(self, wait):
        bid_el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "span[data-jsonfeed='sell']")))
        ask_el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "span[data-jsonfeed='buy']")))
        return parse_price(bid_el.text), parse_price(ask_el.text)

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
#  UI 樣式與設計
# ==========================================

DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #1e1e1e;
    color: #e0e0e0;
    font-family: "Segoe UI", "Microsoft JhengHei", sans-serif;
}
QTabWidget::pane { border: 1px solid #3c3c3c; background: #2b2b2b; }
QTabBar::tab { background: #3c3c3c; color: #aaa; padding: 8px 20px; border-top-left-radius: 4px; border-top-right-radius: 4px; margin-right: 2px; }
QTabBar::tab:selected { background: #007acc; color: white; font-weight: bold; }
QTableWidget { background-color: #252526; gridline-color: #3c3c3c; border: none; font-size: 15px; }
QTableWidget::item { padding: 5px; border-bottom: 1px solid #333; }
QHeaderView::section { background-color: #333337; color: #cccccc; padding: 6px; border: none; font-weight: bold; }
QPushButton { background-color: #0e639c; color: white; border: none; padding: 8px 15px; border-radius: 4px; font-weight: bold; }
QPushButton:hover { background-color: #1177bb; }
QPushButton:disabled { background-color: #444; color: #888; }
QLineEdit { background-color: #3c3c3c; color: white; border: 1px solid #555; padding: 4px; border-radius: 2px; }
QListWidget { background-color: #252526; border: 1px solid #3c3c3c; }
QListWidget::item { padding: 10px; }
QListWidget::item:selected { background-color: #37373d; border-left: 3px solid #007acc; }
QGroupBox { border: 1px solid #555; border-radius: 5px; margin-top: 20px; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; color: #007acc; }
QTextBrowser { background-color: #252526; color: #e0e0e0; border: none; font-size: 14px; padding: 10px; }
QCheckBox { spacing: 5px; }
QCheckBox::indicator { width: 18px; height: 18px; border: 1px solid #555; background: #252526; border-radius: 3px; }
QCheckBox::indicator:checked { background: #007acc; border: 1px solid #007acc; image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSJ3aGl0ZSIgc3Ryb2tlLXdpZHRoPSIzIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwb2x5bGluZSBwb2ludHM9IjIwIDYgOSAxNyA0IDEyIi8+PC9zdmc+); }
"""


class GoldMonitorApp(QMainWindow):
    audio_log_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("XAUUSD點差監控")
        self.resize(1150, 720)
        self.setStyleSheet(DARK_STYLESHEET)

        self.workers = []
        self.setting_inputs = {}
        self.alert_status_labels = {}
        self.last_triggered_levels = {}
        self.sound_checkboxes = {}
        self.chk_all_sound = None

        # 定義全站點資料 (已移除 KVB)
        self.all_sites_config = {
            "WF": {"url": "https://www.wfbullion.com/mq.html", "handle": None, "name": "永豐金業"},
            "IG": {"url": "https://www.ig.com/cn/commodities/markets-commodities/gold", "handle": None,
                   "name": "IG Markets"},
            "Forex": {"url": "https://www.forex.com/cn/markets-to-trade/precious-metals/", "handle": None,
                      "name": "Forex.com"},
            "MW": {"url": "https://www.mw801.com/", "handle": None, "name": "英皇金業"},
            "Axi": {"url": "https://www.axi.com/int/trade/cfds/commodities", "handle": None, "name": "Axi"},
            "Capital": {"url": "https://capital.com/zh-hant/markets/commodities", "handle": None,
                        "name": "Capital.com"},
            "VT": {
                "url": "https://www.vtmarketsglobal.com/precious-metals/?_sasdk=dMTlhZmRkY2IyMTI5NTEtMDA2ODAzZWVkY2Y0MjE3LTI2MDYxYTUxLTEzMjcxMDQtMTlhZmRkY2IyMTMxMTk1",
                "handle": None, "name": "VT Markets"},
            "Markets": {"url": "https://www.markets.com/instrument/gold/", "handle": None, "name": "Markets.com"},
            "IFC": {"url": "https://www.ifcmarkets.com/en/trading-conditions/precious-metals/xauusd", "handle": None,
                    "name": "IFC Markets"},
            "CMC": {"url": "https://www.cmcmarkets.com/en-au/instruments/gold-cash", "handle": None,
                    "name": "CMC Markets"},
        }
        self.broker_keys = list(self.all_sites_config.keys())
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

        # Top Bar
        top_bar = QHBoxLayout()
        self.btn_start = QPushButton(" 🚀 啟動監控")
        self.btn_start.setStyleSheet("background-color: #28a745; font-size: 14px;")
        self.btn_start.clicked.connect(self.start_monitor)

        self.btn_stop = QPushButton(" 🛑 停止監控")
        self.btn_stop.setStyleSheet("background-color: #dc3545; font-size: 14px;")
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

        self.tab_monitor = QWidget()
        self.setup_monitor_tab()
        self.tabs.addTab(self.tab_monitor, "即時行情看板")

        self.tab_settings = QWidget()
        self.setup_settings_tab()
        self.tabs.addTab(self.tab_settings, "點差警報設定")

        self.tab_urls = QWidget()
        self.setup_urls_tab()
        self.tabs.addTab(self.tab_urls, "綜合網址")

        self.tab_log = QWidget()
        self.setup_log_tab()
        self.tabs.addTab(self.tab_log, "執行日誌")

    def setup_monitor_tab(self):
        layout = QVBoxLayout(self.tab_monitor)

        # 音效全選控制區
        ctrl_layout = QHBoxLayout()
        ctrl_layout.addStretch()

        self.chk_all_sound = QCheckBox("全選/取消所有音效")
        self.chk_all_sound.setChecked(True)
        self.chk_all_sound.setFont(QFont("Microsoft JhengHei", 10, QFont.Weight.Bold))
        self.chk_all_sound.setStyleSheet("color: #4ec9b0;")
        self.chk_all_sound.clicked.connect(self.toggle_all_sounds)

        ctrl_layout.addWidget(self.chk_all_sound)
        layout.addLayout(ctrl_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["券商 (Broker)", "Bid (賣出)", "Ask (買入)", "點差 (Spread)", "最後更新", "狀態", "音效 (Sound)"])
        self.table.setRowCount(len(self.broker_keys))

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)

        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)

        font_price = QFont("Arial", 14)
        font_spread = QFont("Arial", 16, QFont.Weight.Bold)

        for row, key in enumerate(self.broker_keys):
            item_name = QTableWidgetItem(self.all_sites_config[key]["name"])
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
            item_status.setForeground(QColor("#f44747"))
            self.table.setItem(row, 5, item_status)

            # 音效開關
            container = QWidget()
            chk_layout = QHBoxLayout(container)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk_sound = QCheckBox()
            chk_sound.setChecked(True)
            chk_sound.setToolTip(f"勾選以啟用 [{self.all_sites_config[key]['name']}] 的音效")

            chk_sound.toggled.connect(
                lambda checked, k=key: self.log_message(f"[{self.all_sites_config[k]['name']}] 音效切換: {checked}"))

            chk_layout.addWidget(chk_sound)
            self.table.setCellWidget(row, 6, container)
            self.sound_checkboxes[key] = chk_sound

        layout.addWidget(self.table)

    def toggle_all_sounds(self, checked):
        action = "開啟" if checked else "關閉"
        self.log_message(f"--- 執行批量操作: {action}所有音效 ---")
        for key, chk in self.sound_checkboxes.items():
            if chk.isChecked() != checked:
                chk.setChecked(checked)

    def setup_settings_tab(self):
        layout = QVBoxLayout(self.tab_settings)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.list_brokers = QListWidget()
        self.list_brokers.setFixedWidth(200)
        self.list_brokers.addItems([self.all_sites_config[k]["name"] for k in self.broker_keys])

        self.stack_settings = QStackedWidget()
        for key in self.broker_keys:
            self.stack_settings.addWidget(self.create_setting_page(key))

        self.list_brokers.currentRowChanged.connect(self.stack_settings.setCurrentIndex)
        self.list_brokers.setCurrentRow(0)

        splitter.addWidget(self.list_brokers)
        splitter.addWidget(self.stack_settings)

        btn_layout = QHBoxLayout()
        btn_save = QPushButton("💾 儲存所有設定")
        btn_save.setFixedSize(150, 40)
        btn_save.clicked.connect(self.save_settings)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_save)

        layout.addWidget(splitter)
        layout.addLayout(btn_layout)

    def create_setting_page(self, key):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        title = QLabel(f"設定: {self.all_sites_config[key]['name']}")
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

    def setup_urls_tab(self):
        layout = QVBoxLayout(self.tab_urls)
        text_browser = QTextBrowser()
        text_browser.setOpenExternalLinks(True)
        html_content = "<style>h2{color:#007acc;} p{margin:10px 0;font-size:15px;} a{color:#4ec9b0;text-decoration:none;} a:hover{text-decoration:underline;color:#9cdcfe;}</style><h2>綜合網址清單</h2>"
        for k, v in self.all_sites_config.items():
            html_content += f"<p><b>{v['name']}:</b> <a href='{v['url']}'>{v['url']}</a></p>"
        text_browser.setHtml(html_content)
        layout.addWidget(text_browser)

    def setup_log_tab(self):
        layout = QVBoxLayout(self.tab_log)
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setStyleSheet("background-color: #1e1e1e; color: #ccc; font-family: Consolas;")
        layout.addWidget(self.txt_log)
        btn_clear = QPushButton("清除日誌")
        btn_clear.clicked.connect(self.txt_log.clear)
        layout.addWidget(btn_clear)

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
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.last_triggered_levels = {}
        self.log_message(f">>> 監控系統啟動，配置 {WORKER_COUNT} 個並行引擎...")

        keys = list(self.all_sites_config.keys())
        chunk_size = math.ceil(len(keys) / WORKER_COUNT)

        self.workers = []
        for i in range(WORKER_COUNT):
            start_idx = i * chunk_size
            end_idx = start_idx + chunk_size
            worker_keys = keys[start_idx:end_idx]

            if not worker_keys: continue

            worker_sites = {k: self.all_sites_config[k].copy() for k in worker_keys}

            worker = BrowserWorker(i + 1, worker_sites)
            worker.log_signal.connect(self.log_message)
            worker.price_signal.connect(self.on_price_update)
            worker.status_signal.connect(self.on_status_update)
            worker.finished_signal.connect(self.on_worker_finished)
            self.workers.append(worker)
            worker.start()

    def stop_monitor(self):
        self.log_message("正在發送停止信號給所有引擎...")
        self.btn_stop.setEnabled(False)
        for w in self.workers:
            w.stop()

    def on_worker_finished(self):
        all_stopped = all(not w.isRunning() for w in self.workers)
        if all_stopped:
            self.log_message(">>> 所有監控引擎已安全停止")
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.workers.clear()

    def on_price_update(self, source, bid, ask, time_str):
        if source not in self.row_map: return
        row = self.row_map[source]
        spread = abs(ask - bid)

        self.table.item(row, 1).setText(f"{bid:.2f}")
        self.table.item(row, 2).setText(f"{ask:.2f}")
        self.table.item(row, 3).setText(f"{spread:.2f}")
        self.table.item(row, 4).setText(time_str)
        self.table.item(row, 5).setText("監控中")
        self.table.item(row, 5).setForeground(QColor("#4ec9b0"))

        self.check_alert(source, spread, row)

    def on_status_update(self, source, msg):
        if source not in self.row_map: return
        row = self.row_map[source]
        item = self.table.item(row, 5)
        item.setText(msg)
        item.setForeground(QColor("#4ec9b0") if msg == "監控中" else QColor("#f44747"))

    # ==========================================
    #  [關鍵修正] 嚴格的警報檢查邏輯
    # ==========================================
    def check_alert(self, source, spread, row_idx):
        inputs = self.setting_inputs.get(source, [])
        highest_lvl = -1
        sound_path = None

        # 1. 計算最高觸發層級 (UI 更新)
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
                # [修正] 使用 .strip() 確保沒有多餘的空白
                sound_path = item['sound'].text().strip()
            else:
                lbl.setText("● 待機")
                lbl.setStyleSheet("color: gray;")

        spread_item = self.table.item(row_idx, 3)
        spread_item.setBackground(QColor("#660000") if highest_lvl >= 0 else QColor("#252526"))

        last = self.last_triggered_levels.get(source, -1)

        # 2. 獲取音效開關狀態 (Checkbox)
        is_sound_enabled_for_this_broker = True
        if source in self.sound_checkboxes:
            is_sound_enabled_for_this_broker = self.sound_checkboxes[source].isChecked()

        # 3. 判斷是否播放音效 (邏輯順序優化)
        if highest_lvl > last:
            self.log_message(f"[{source}] 警報觸發! 點差: {spread:.2f} (層級 {highest_lvl + 1})")

            # [修正] 優先判斷開關是否開啟
            if is_sound_enabled_for_this_broker:
                # [修正] 只有當路徑存在且確實是檔案時才播放 (過濾掉空字串或無效路徑)
                if sound_path and os.path.isfile(sound_path):
                    threading.Thread(target=self.play_sound, args=(sound_path,), daemon=True).start()
                else:
                    # 如果設定了層級但沒檔案，這是正常的，保持安靜
                    pass
            else:
                self.log_message(f"   -> [{source}] 音效開關已手動關閉，不播放。")

        self.last_triggered_levels[source] = highest_lvl

    def play_sound(self, path):
        try:
            # [修正] 加入 SND_ASYNC 確保非阻塞
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_NODEFAULT | winsound.SND_ASYNC)
        except:
            pass

    def save_settings(self):
        data = {}
        for key, inputs in self.setting_inputs.items():
            is_checked = self.sound_checkboxes[key].isChecked() if key in self.sound_checkboxes else True
            data[key] = {"tiers": [], "sound_enabled": is_checked}
            for item in inputs:
                data[key]["tiers"].append({"diff": item['diff'].text(), "sound": item['sound'].text()})
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            self.log_message("設定(含音效開關)已保存至硬碟")
            QMessageBox.information(self, "成功", "設定已成功儲存！")
        except Exception as e:
            self.log_message(f"儲存失敗: {e}")
            QMessageBox.critical(self, "錯誤", f"儲存設定失敗: {e}")

    def load_settings(self):
        if not os.path.exists(CONFIG_FILE): return
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)

            all_checked = True

            for key, val in data.items():
                tiers = val if isinstance(val, list) else val.get("tiers", [])
                sound_enabled = True if isinstance(val, list) else val.get("sound_enabled", True)

                if key in self.setting_inputs:
                    ui_inputs = self.setting_inputs[key]
                    for i, t_data in enumerate(tiers):
                        if i < len(ui_inputs):
                            ui_inputs[i]['diff'].setText(t_data.get('diff', ''))
                            ui_inputs[i]['sound'].setText(t_data.get('sound', ''))

                if key in self.sound_checkboxes:
                    self.sound_checkboxes[key].setChecked(sound_enabled)
                    if not sound_enabled:
                        all_checked = False

            if self.chk_all_sound:
                self.chk_all_sound.setChecked(all_checked)

        except Exception as e:
            self.log_message(f"讀取設定檔錯誤: {e}")

    def closeEvent(self, event):
        if any(w.isRunning() for w in self.workers):
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