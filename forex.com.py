from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# 設定 Chrome 選項
chrome_options = Options()
# chrome_options.add_argument("--headless")  # 若不需顯示視窗可取消註解
driver = webdriver.Chrome(options=chrome_options)

try:
    url = "https://www.forex.com/cn/markets-to-trade/precious-metals/"
    driver.get(url)

    wait = WebDriverWait(driver, 15)

    # --- 定位策略 ---
    # 1. 先找到包含 "XAU USD" 連結的那一行 (tr)
    # XPath 解釋: //tr[.//a[@title='XAU USD']]
    # 意思: 找出內部有一個 <a> 標籤且 title 屬性為 'XAU USD' 的所有 tr 元素
    product_row = wait.until(EC.presence_of_element_located(
        (By.XPATH, "//tr[.//a[@title='XAU USD']]")
    ))

    # 2. 在這一行裡面找賣出價 (Bid)
    # class 為 'mp__td--Bid'
    bid_element = product_row.find_element(By.CSS_SELECTOR, ".mp__td--Bid")

    # 3. 在這一行裡面找買入價 (Offer)
    # class 為 'mp__td--Offer'
    offer_element = product_row.find_element(By.CSS_SELECTOR, ".mp__td--Offer")

    # 4. 取得文字並清理換行符號
    bid_price = bid_element.text.strip()
    ask_price = offer_element.text.strip()

    print("--- Forex.com 黃金價格 (XAU/USD) ---")
    print(f"賣出價 (Bid): {bid_price}")
    print(f"買入價 (Ask): {ask_price}")


except Exception as e:
    print(f"發生錯誤: {e}")

finally:
    driver.quit()