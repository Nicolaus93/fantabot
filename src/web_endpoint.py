
import modal
from pydantic import BaseModel

class Item(BaseModel):
    chat_id: int = 268217449
    message: str


TOKEN = "7584218061:AAEwY8oVvPtC6VJ6eE5LNBvtHcA-oPFfecI"

image = modal.Image.debian_slim().pip_install([
    "httpx",
    "openai",
    "feedparser",
    "playwright==1.42.0",
    "html2text",
]).run_commands(
    "playwright install-deps chromium",
    "playwright install chromium",
)
app = modal.App(
    name="example-telegram-bot",
    image=image,
)


@app.function(image=image)
async def get_news_content(news_link):
    from playwright.async_api import async_playwright
    import html2text

    print(f"Reading from {news_link}...")
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(news_link)

        # Get the HTML content of the page
        content = await page.content()
        await browser.close()

    # Convert HTML to Markdown
    h = html2text.HTML2Text()
    h.ignore_links = False
    return h.handle(content)


@app.function(image=image)
def get_news():
    import feedparser
    from datetime import datetime, timedelta, timezone

    feed_url = "https://www.gazzetta.it/dynamic-feed/rss/section/Calcio/Serie-A.xml"
    feed = feedparser.parse(feed_url)
    current_time = datetime.now(timezone.utc)
    for i, news in enumerate(feed.entries):
        print(news.title)
        given_time = datetime.strptime(news.published, '%a, %d %b %Y %H:%M:%S %z')
        if given_time - current_time < timedelta(minutes=10):
            news_content = get_news_content.remote(news_link=news.link)
            news_summary = get_summary.remote(content=news_content)
            yield news_summary
        if i > 2:
            break


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("openai_fantabot_key")],
)
def get_summary(content):
    import os
    from openai import OpenAI

    print("Getting news summary..")
    query = f"Riassumi le ultime notizie calcistiche contenute in questo articolo: {content}"
    client = OpenAI(api_key=os.environ["OPENAI_FANTABOT_API_KEY"])
    print("Querying gpt-4o-mini..")
    completion = client.beta.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Sei un giornalista sportivo."},
            {"role": "user", "content": query},
        ],
    )
    print("Done!")
    print(completion.choices[0].message.content)
    return completion.choices[0].message.content


@app.function(image=image)
@modal.web_endpoint(method="POST", docs=True)
async def send_tg_msg(item: Item):
    import httpx

    api_url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        for summary in get_news.remote_gen():
            print("Sending news summary..")
            tg_msg = {"chat_id": item.chat_id, "text": summary, "parse_mode": "Markdown"}
            await client.post(api_url, json=tg_msg)


@app.local_entrypoint()
def main():
    print("Getting data...")
    for summary in get_news.remote_gen():
        print("news summary:")
        print(summary)
