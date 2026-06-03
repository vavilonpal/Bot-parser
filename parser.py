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
import re

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)

# ============================================================
#   TELEGRAM
# ============================================================
TELEGRAM_TOKEN = '8664437815:AAF5TjvMm7IxIvUpLCcS9XpUDwlM_wOw7Bs'
PRIMARY_CHAT_ID = '1834103343'
SECONDARY_CHAT_ID = '1858170014'

# ============================================================
#   ФИЛЬТРЫ ЦЕН  (бот отправит только если цена в диапазоне)
# ============================================================
PRICE_EUR_MIN = 150  # €  минимум
PRICE_EUR_MAX = 300  # €  максимум
PRICE_USD_MIN = 200  # $  минимум
PRICE_USD_MAX = 350  # $  максимум
PRICE_MDL_MIN = 3000  # лей минимум
PRICE_MDL_MAX = 6000  # лей максимум

# ============================================================
#   ФИЛЬТРЫ 999.MD
#   Районы Кишинёва:
#     Центр=894, Ботаника=902, Рышкановка=900, Чеканы=12900,
#     Буюканы=12885, Телецентр=13859, Скулянка=12912
# ============================================================
PRICE_999_MIN = 150  # € от
PRICE_999_MAX = 300  # € до
DISTRICTS_999 = "894,902"  # районы через запятую

URL_999 = (
    "https://999.md/ru/list/real-estate/apartments-and-rooms"
    "?appl=1&applied=1"
    "&ef=2203,32,30,6,9441"
    "&eo=12912,12885,12900,13859"
    "&o_33_1=912"
    "&o_2203_795=18895"
    "&o_32_9_12900_13859=15667"
    "&sort=yes&sort_type=date_desc"
    f"&from_6_2={PRICE_999_MIN}&to_6_2={PRICE_999_MAX}&unit_6_2=eur"
    "&from_9441_2=200&to_9441_2=400&unit_9441_2=eur"
    f"&o_30_241={DISTRICTS_999}"
)

# ============================================================
#   ФИЛЬТРЫ MAKLER.MD
#   Комнаты: 2802=1 комната, 2803=2 комнаты, 2804=3 комнаты
#   Валюта:  5=USD, 2=EUR, 3=MDL
#   Районы Кишинёва:
#     Центр=1024, Ботаника=1025, Рышкановка=1026,
#     Буюканы=1030, Чеканы=1023
# ============================================================
PRICE_MAKLER_MIN = 200  # от
PRICE_MAKLER_MAX = 400  # до
CURRENCY_MAKLER = 5  # 5=USD
ROOMS_MAKLER = 2802  # 1 комната
DISTRICTS_MAKLER = [1024, 1025, 1026, 1030, 1023]

_dist = "".join(f"&district[]={d}" for d in DISTRICTS_MAKLER)
URL_MAKLER = (
    "https://makler.md/ru/real-estate/real-estate-for-rent/apartments-for-rent"
    f"?list&city[]=28{_dist}"
    f"&field_432[]={ROOMS_MAKLER}"
    "&field_372[]=2666&field_372[]=2667"
    f"&price_min={PRICE_MAKLER_MIN}&price_max={PRICE_MAKLER_MAX}"
    f"&currency_id={CURRENCY_MAKLER}"
    "&order=date&direction=desc"
)

# ============================================================
#   ПРОЧИЕ НАСТРОЙКИ
# ============================================================
SEEN_IDS_FILE = "seen_ids.txt"
SEEN_IDS_FILE_MAKLER = "seen_ids_makler.txt"
SCROLL_PAUSE_TIME = 1.5
MAX_SCROLLS = 4
PAGE_LOAD_TIMEOUT = 20  # секунд ждать загрузки страницы
LOOP_INTERVAL = 60  # секунд между итерациями

# ============================================================

bot = Bot(token=TELEGRAM_TOKEN)


def make_driver():
    chrome_path = ChromeDriverManager().install()
    service = Service(chrome_path)
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    )
    return webdriver.Chrome(service=service, options=options)


def scroll_page(driver):
    for _ in range(MAX_SCROLLS):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(SCROLL_PAUSE_TIME)


# --- Цена ---

def extract_price(price_str):
    digits = ''.join(c for c in price_str if c.isdigit())
    return int(digits) if digits else 0


def is_price_acceptable(price_str):
    price = extract_price(price_str)
    low = price_str.lower()
    if '€' in low or 'eur' in low:
        result = PRICE_EUR_MIN <= price <= PRICE_EUR_MAX
    elif '$' in low or 'usd' in low:
        result = PRICE_USD_MIN <= price <= PRICE_USD_MAX
    elif any(c in low for c in ('mdl', 'лей', 'lei')):
        result = PRICE_MDL_MIN <= price <= PRICE_MDL_MAX
    else:
        result = False
    logging.info(f"Цена '{price_str}' -> {price}, подходит={result}")
    return result


# --- Telegram ---

async def send_ads_to_telegram(ad):
    if not is_price_acceptable(ad['price']):
        logging.info(f"Пропущено (цена): {ad['price']}")
        return False
    message = f"🏠 {ad['title']}\n💰 {ad['price']}\n🔗 {ad['link']}"
    try:
        await bot.send_message(chat_id=PRIMARY_CHAT_ID, text=message)
        ## await bot.send_message(chat_id=SECONDARY_CHAT_ID, text=message)
        logging.info(f"Отправлено: {ad['id']}")
        return True
    except Exception as e:
        logging.error(f"Ошибка Telegram: {e}")
    return False


# --- Seen IDs ---

def load_seen_ids(path):
    try:
        with open(path, "r") as f:
            ids = set(line.strip() for line in f if line.strip())
        logging.info(f"Загружено {len(ids)} ID из {path}")
        return ids
    except FileNotFoundError:
        return set()


def save_seen_id(path, ad_id):
    with open(path, "a") as f:
        f.write(f"{ad_id}\n")


# --- Парсер 999.md ---

def parse_ads_999():
    logging.info("999.md: открываю страницу")

    driver = make_driver()

    try:
        driver.get(URL_999)

        wait = WebDriverWait(driver, 10)

        wait.until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR,
                 'a.styles_advert__photo__link__SnL_t')
            )
        )

        soup = BeautifulSoup(driver.page_source, 'html.parser')

        ads = []

        items = soup.select(
            'a.styles_advert__photo__link__SnL_t'
        )

        logging.info(f"999.md: {len(items)} карточек")

        for node in items:
            try:
                href = node.get('href', '')

                ad_id = (
                    href.strip('/')
                    .split('/')[-1]
                    .split('?')[0]
                )

                link = (
                    href
                    if href.startswith('http')
                    else f"https://999.md{href}"
                )

                # Заголовок
                title_node = node.select_one('h4')

                title = (
                    title_node.get_text(strip=True)
                    if title_node else ''
                )

                # Цена
                price_node = node.select_one(
                    'span.styles_price__text__VPLPL'
                )

                price = (
                    price_node.get_text(strip=True)
                    if price_node else '0'
                )

                ads.append({
                    'id': ad_id,
                    'title': title,
                    'price': price,
                    'link': link
                })

            except Exception as e:
                logging.warning(f"999.md parse error: {e}")

        return ads

    finally:
        driver.quit()


# --- Парсер makler.md ---

def parse_makler_ads():
    logging.info(f"makler.md: открываю страницу")
    driver = make_driver()
    try:
        driver.get(URL_MAKLER)
        wait = WebDriverWait(driver, PAGE_LOAD_TIMEOUT)

        for sel in [
            'article.ls-detail_item',
            'article[class*="ls-detail"]',
            'div.ls-detail article',
            'div[class*="listing"] article',
            'article',
        ]:
            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                logging.info(f"makler.md: карточки найдены по '{sel}'")
                break
            except TimeoutException:
                continue

        scroll_page(driver)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
    finally:
        driver.quit()

    # Ищем контейнер с карточками
    container = soup.find('div', class_='ls-detail')
    articles = container.find_all('article') if container else []
    if not articles:
        articles = soup.select('article[class*="ls-detail"]')
    if not articles:
        articles = soup.find_all('article')

    logging.info(f"makler.md: найдено {len(articles)} карточек")
    ads = []

    for art in articles:
        try:
            title_el = (
                    art.select_one('h3 a') or
                    art.select_one('h2 a') or
                    art.select_one('a[class*="title"]') or
                    art.select_one('a[href*="/ru/real-estate/"]')
            )
            if not title_el: continue

            href = title_el.get('href', '')
            ad_id = href.strip('/').split('/')[-1]
            link = href if href.startswith('http') else f"https://makler.md{href}"

            price_el = (
                    art.select_one('[class*="price"]') or
                    art.select_one('[class*="Price"]')
            )
            price = price_el.get_text(strip=True) if price_el else '0'

            ads.append({'id': ad_id, 'title': title_el.get_text(strip=True),
                        'price': price, 'link': link})
        except Exception as e:
            logging.warning(f"makler.md: {e}")

    logging.info(f"makler.md: итого {len(ads)} объявлений")
    return ads


# --- Основной цикл ---

async def main():
    logging.info("=== Итерация 999.md ===")
    seen_999 = load_seen_ids(SEEN_IDS_FILE)

    for ad in parse_ads_999():
        link = ad.get("link", "")
        match = re.search(r"\d+", link)

        # 1. Проверяем, удалось ли вообще найти ID в ссылке
        if not match:
            logging.warning(f"Не удалось найти ID в ссылке: {link}")
            continue

        ad_id = ad.get("id", "")

        # 2. Проверяем, видели ли мы ИМЕННО ЭТОТ ad_id
        if ad_id not in seen_999:
            if await send_ads_to_telegram(ad):
                # 3. Сохраняем ИМЕННО ad_id, а не ad['id']
                save_seen_id(SEEN_IDS_FILE, ad_id)
                seen_999.add(ad_id)
                logging.info(f"Объявление {ad_id} успешно отправлено и сохранено.")

    logging.info("=== Итерация makler.md ===")
    seen_makler = load_seen_ids(SEEN_IDS_FILE_MAKLER)
    for ad in parse_makler_ads():
        if ad['id'] not in seen_makler:
            if await send_ads_to_telegram(ad):
                save_seen_id(SEEN_IDS_FILE_MAKLER, ad['id'])
                seen_makler.add(ad['id'])


async def main_loop():
    while True:
        try:
            await main()
        except Exception as e:
            logging.error(f"Ошибка в main_loop: {e}", exc_info=True)
        logging.info(f"Sleeping {LOOP_INTERVAL}s...")
        await asyncio.sleep(LOOP_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main_loop())
