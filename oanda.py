from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# 設定 Chrome 選項
chrome_options = Options()
# chrome_options.add_argument("--headless") # 如果需要無頭模式請取消註解
driver = webdriver.Chrome(options=chrome_options)

try:
    url = "https://www.oanda.com/bvi-en/cfds/metals/"
    driver.get(url)

    # 設定等待時間
    wait = WebDriverWait(driver, 10)

    # 策略：
    # 1. 找到包含 "Gold" 文字的 <span>，然後往上找父層的父層直到找到 <tr>
    # XPath 解釋: //tr[.//span[contains(text(), 'Gold')]]
    # 意思: 找出內部含有 span 且該 span 文字包含 'Gold' 的所有 tr 元素
    gold_row = wait.until(EC.presence_of_element_located(
        (By.XPATH, "//tr[.//span[contains(text(), 'Gold')]]")
    ))

    # 2. 在這一行 (tr) 裡面找到所有的儲存格 (td)
    cells = gold_row.find_elements(By.TAG_NAME, "td")

    # 3. 根據您的 HTML 結構：
    # td[0] 是名稱 (Gold)
    # td[1] 是賣出價 (數值較低)
    # td[2] 是買入價 (數值較高)
    if len(cells) >= 3:
        sell_price = cells[1].text
        buy_price = cells[2].text

        print(f"商品: Gold (XAU/USD)")
        print(f"賣出價 (Bid): {sell_price}")
        print(f"買入價 (Ask): {buy_price}")
    else:
        print("找不到足夠的欄位數據")

except Exception as e:
    print(f"發生錯誤: {e}")

finally:
    driver.quit()