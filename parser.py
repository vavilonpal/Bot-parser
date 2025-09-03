import logging
import time
import asyncio
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
from telegram import Bot
from selenium.common.exceptions import TimeoutException

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)

TELEGRAM_TOKEN = '7169698899:AAELmsw_gIOF-YBLXCeG0SjpGCnjol4txsI'
PRIMARY_CHAT_ID = '962929346'
SECONDARY_CHAT_ID = '1017188788'
bot = Bot(token=TELEGRAM_TOKEN)

SEEN_IDS_FILE = "seen_ids.txt"
SEEN_IDS_FILE_MAKLER = "seen_ids_makler.txt"

SCROLL_PAUSE_TIME = 1.0
MAX_SCROLLS = 3


def extract_price(price_str):
    digits = ''.join(c for c in price_str if c.isdigit())
    price = int(digits) if digits else 0
    logging.debug(f"extract_price: '{price_str}' -> {price}")
    return price


def is_price_acceptable(price_str):
    price = extract_price(price_str)
    low = price_str.lower()
    if '€' in low:
        result = 150 <= price <= 300
    elif '$' in low:
        result = 200 <= price <= 350
    elif any(cur in low for cur in ('mdl', 'лей', 'lei')):
        result = 3000 <= price <= 6000
    else:
        result = False
    logging.info(f"is_price_acceptable: '{price_str}' -> {price}, acceptable={result}")
    return result


async def send_ads_to_telegram(ad):
    logging.info(f"send_ads_to_telegram: проверка объявления {ad['id']}")
    if is_price_acceptable(ad['price']):
        message = f"🏠 {ad['title']}\n💰 {ad['price']}\n🔗 {ad['link']}"
        try:
            await bot.send_message(chat_id=PRIMARY_CHAT_ID, text=message)
            await bot.send_message(chat_id=SECONDARY_CHAT_ID, text=message)
            logging.info(f"Сообщение отправлено: {ad['id']} всем чатам")
            return True
        except Exception as e:
            logging.error(f"Ошибка при отправке в Telegram: {e}")
    else:
        logging.info(f"Объявление пропущено (цена не подходит): {ad['price']}")
    return False


def load_seen_ids():
    try:
        with open(SEEN_IDS_FILE, "r") as f:
            ids = set(line.strip() for line in f)
        logging.info(f"Loaded {len(ids)} seen IDs")
        return ids
    except FileNotFoundError:
        logging.info("No seen IDs file found, starting fresh")
        return set()


def save_seen_id(ad_id):
    with open(SEEN_IDS_FILE, "a") as f:
        f.write(f"{ad_id}\n")
    logging.debug(f"Saved ad ID: {ad_id}")

def load_seen_ids_makler():
    try:
        with open(SEEN_IDS_FILE_MAKLER, "r") as f:
            return set(line.strip() for line in f)
    except FileNotFoundError:
        return set()

def save_seen_id_makler(ad_id):
    with open(SEEN_IDS_FILE_MAKLER, "a") as f:
        f.write(ad_id + "\n")

def parse_ads():
    chrome_path = ChromeDriverManager(driver_version="136.0.7103.92").install()
    service = Service(chrome_path)
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(service=service, options=options)

    url = (
        'https://999.md/ru/list/real-estate/apartments-and-rooms?appl=1&applied=1&ef=2203,32,30,6,9441&eo=12912,12885,12900,13859&o_33_1=912&o_2203_795=18895&o_32_9_12900_13859=15667&sort=yes&sort_type=date_desc&to_6_2=320&unit_6_2=eur&from_6_2=150&from_9441_2=200&unit_9441_2=eur&to_9441_2=400&o_30_241=894,902'
    )

    logging.info(f"Parsing ads from: {url}")
    driver.get(url)

    wait = WebDriverWait(driver, 10)
    try:
        wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'div.AdPhoto_wrapper__gAOIH')))
    except Exception as e:
        logging.error(f"Timeout waiting for ads to load: {e}")

    for _ in range(MAX_SCROLLS):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(SCROLL_PAUSE_TIME)

    soup = BeautifulSoup(driver.page_source, 'html.parser')
    ads = []
    items = soup.select('div.AdPhoto_wrapper__gAOIH')
    logging.info(f"Found {len(items)} ad items on page")
    for node in items:
        try:
            title_el = node.select_one('a.AdPhoto_info__link__OwhY6')
            price_el = node.select_one('span.AdPrice_price__2L3eA')
            img_el = node.select_one('img')
            if not (title_el and price_el and img_el):
                continue
            href = title_el.get('href', '')
            path = href.split('?')[0]
            ad_id = path.strip('/').split('/')[-1]
            link = href if href.startswith('http') else f"https://999.md{href}"
            price_text = price_el.get_text(strip=True)
            img_src = img_el.get('src') or img_el.get('data-src')
            ads.append({
                'id': ad_id,
                'title': title_el.get_text(strip=True),
                'price': price_text,
                'link': link,
                'image': img_src
            })
        except Exception as e:
            logging.warning(f"Failed parsing ad node: {e}")
    logging.info(f"Total ads parsed: {len(ads)}")
    driver.quit()
    return ads




def parse_makler_ads():
    chrome_path = ChromeDriverManager(driver_version="136.0.7103.92").install()
    service = Service(chrome_path)
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(service=service, options=options)

    safe_url = (
        "https://makler.md/ru/real-estate/real-estate-for-rent/apartments-for-rent?list&city[]=28&district[]=1024&district[]=1025&district[]=1026&district[]=1030&district[]=1023&field_432[]=2802&field_372[]=2666&field_372[]=2667&price_min=200&price_max=400&currency_id=5&order=date&direction=desc&list=false"
    )

    logging.info(f"Parsing Makler ads from: {safe_url}")
    driver.get(safe_url)

    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "noscript"))
        )
        noscripts = driver.find_elements(By.TAG_NAME, "noscript")

        raw_html = "".join(ns.get_attribute("innerHTML") for ns in noscripts)
        soup = BeautifulSoup(raw_html, "html.parser")
    except TimeoutException:
        logging.warning("Timeout waiting for <noscript>, парсим page_source")
        soup = BeautifulSoup(driver.page_source, "html.parser")
    finally:
        driver.quit()

    container = soup.find("div", class_="ls-detail")
    if not container:
        logging.warning("Не нашёл контейнер .ls-detail на странице")
        return []

    articles = container.find_all("article")
    logging.info(f"Makler: найдено {len(articles)} объявлений")
    ads = []
    for art in articles:
        try:
            img_el = art.select_one(".ls-detail_imgBlock img")
            img_src = img_el["src"] if img_el else None

            time_el = art.select_one(".ls-detail_controlsBlock .ls-detail_time")
            time_str = time_el.get_text(strip=True) if time_el else ""

            title_el = art.select_one(".ls-detail_infoBlock h3.ls-detail_antTitle a")
            title = title_el.get_text(strip=True)
            href  = title_el["href"]
            ad_id = href.strip("/").split("/")[-1]
            link  = href if href.startswith("http") else f"https://makler.md{href}"

            desc_p = art.select_one(".ls-detail_infoBlock p")
            description = " ".join(desc_p.stripped_strings) if desc_p else ""

            data_block = art.select_one(".ls-detail_infoBlock .ls-detail_anData")
            price_el = data_block.select_one(".ls-detail_price") if data_block else None
            price = price_el.get_text(strip=True) if price_el else ""
            spans = data_block.find_all("span") if data_block else []
            phone = spans[1].get_text(strip=True) if len(spans) > 1 else ""

            ads.append({
                "id":          ad_id,
                "title":       title,
                "time":        time_str,
                "description": description,
                "price":       price,
                "phone":       phone,
                "link":        link,
                "image":       img_src,
            })
        except Exception as e:
            logging.warning(f"Ошибка парсинга одного объявления: {e}")
    return ads

async def main():
    logging.info("=== Новая итерация для 999.md ===")
    seen_999 = load_seen_ids()
    ads_999  = parse_ads()
    for ad in ads_999:
        if ad['id'] not in seen_999:
            logging.info(f"999.md: новое объявление {ad['id']}")
            if await send_ads_to_telegram(ad):
                save_seen_id(ad['id'])
        else:
            logging.debug(f"999.md: уже было {ad['id']}")

    logging.info("=== Новая итерация для makler.md ===")
    seen_makler = load_seen_ids_makler()
    ads_makler  = parse_makler_ads()
    for ad in ads_makler:
        if ad['id'] not in seen_makler:
            logging.info(f"makler.md: новое объявление {ad['id']}")
            if await send_ads_to_telegram(ad):
                save_seen_id_makler(ad['id'])
        else:
            logging.debug(f"makler.md: уже было {ad['id']}")

async def main_loop():
    while True:
        try:
            await main()
        except Exception as e:
            logging.error(f"Error in main_loop: {e}")
        logging.info("Sleeping for 60 seconds before next iteration")
        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main_loop())
