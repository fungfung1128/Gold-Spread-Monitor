from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# 設定 Chrome 選項 (可選：設定無頭模式，不開啟瀏覽器視窗)
chrome_options = Options()
# chrome_options.add_argument("--headless")  # 如果不想看到瀏覽器跳出來，請取消註解這行

# 初始化 WebDriver (請確保已有 chromedriver)
driver = webdriver.Chrome(options=chrome_options)

try:
    # 1.前往目標網址
    url = "https://www.ig.com/cn/commodities/markets-commodities/gold"
    driver.get(url)

    # 2. 等待元素加載 (這是動態網頁，建議使用 WebDriverWait)
    # 我們等待 class 為 'price-ticket__button--sell' 的元素出現
    wait = WebDriverWait(driver, 10)

    # 定位 "賣出價" 元素
    # 邏輯：找到 class 有 'price-ticket__button--sell' 的區塊，再找它底下的 'price-ticket__price'
    sell_price_element = wait.until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, ".price-ticket__button--sell .price-ticket__price")
    ))

    # 定位 "買入價" 元素
    # 邏輯：找到 class 有 'price-ticket__button--buy' 的區塊，再找它底下的 'price-ticket__price'
    buy_price_element = wait.until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, ".price-ticket__button--buy .price-ticket__price")
    ))

    # 3. 取得文字內容
    sell_price = sell_price_element.text
    buy_price = buy_price_element.text

    print(f"賣出價: {sell_price}")
    print(f"買入價: {buy_price}")

except Exception as e:
    print(f"發生錯誤: {e}")

finally:
    # 關閉瀏覽器
    driver.quit()