
import modal
from pydantic import BaseModel
import pathlib
import asyncio


class Column(BaseModel):
    date: str
    team1: str
    score1: int
    team2: str
    score2: int


class ResultTable(BaseModel):
    results: list[Column]


VOLUME_DIR = "/cache-vol"
REPORTS_DIR = pathlib.Path(VOLUME_DIR, "SERIE_A")
DB_PATH = pathlib.Path(VOLUME_DIR, "serie_a.db")
URL = "https://www.diretta.it/serie-a"


app = modal.App("seria-a-scores")


datasette_image = modal.Image.debian_slim(
    python_version="3.10"
).run_commands(  # Doesn't work with 3.11 yet
    "apt-get update",
    "apt-get install -y software-properties-common",
    "apt-add-repository non-free",
    "apt-add-repository contrib",
    "pip install playwright==1.42.0",
    "playwright install-deps chromium",
    "playwright install chromium",
).pip_install(
    ["html2text", "openai", "sqlite-utils", "datasette~=0.63.2"]
)


volume = modal.Volume.from_name(
    "serie-a-scores", create_if_missing=True,
)


@app.function(image=datasette_image)
async def get_webpage_as_markdown(url):
    from playwright.async_api import async_playwright
    import html2text

    print(f"Reading from {url}...")
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(url)

        # Get the HTML content of the page
        content = await page.content()

        await browser.close()

    # Convert HTML to Markdown
    h = html2text.HTML2Text()
    h.ignore_links = False
    markdown = h.handle(content)
    print("Done!")
    return markdown


@app.function(
    image=datasette_image,
    secrets=[modal.Secret.from_name("openai_fantabot_key")],
)
async def get_scores(content) -> ResultTable:
    from openai import OpenAI
    import os

    query = f"Give me the result for all matches contained in tnis markdown content: {content}"
    query += "The structure should be a table with the following columns: date (DD.MM.YYYY), team1, score1, team2, score2"

    client = OpenAI(api_key=os.environ["OPENAI_FANTABOT_API_KEY"])
    completion = client.beta.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a football reporter. The year is 2024"},
            {"role": "user", "content": query},
        ],
        response_format=ResultTable,
    )
    message = completion.choices[0].message
    if not message.parsed:
        raise ValueError(message.refusal)
    return message.parsed


@app.function(
    image=datasette_image,
    volumes={VOLUME_DIR: volume},
    timeout=900,
)
async def prep_db(records):
    import sqlite_utils

    # If the Volume is then subsequently modified by a commit operation in another running container,
    # that Volume modification won’t become available until the original container does a .reload()
    # see https://modal.com/docs/guide/volumes
    volume.reload()
    print("Loading score records...")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite_utils.Database(DB_PATH)
    if not db["results"].exists():
        table = db.create_table("results", {
            "date": str,
            "team1": str,
            "score1": int,
            "team2": str,
            "score2": int,
        }, pk=("team1", "team2"))
    else:
        table = db["results"]

    for record in records.results:
        table.upsert({
            "date": record.date,
            "team1": record.team1,
            "score1": record.score1,
            "team2": record.team2,
            "score2": record.score2,
        }, pk=("team1", "team2"))

    print("Syncing DB with volume.")
    volume.commit()
    db.close()


@app.function(schedule=modal.Period(hours=1), timeout=1000)
async def refresh_db():
    from datetime import datetime

    print(f"Running scheduled refresh at {datetime.now()}")
    main()
    volume.commit()
    print("Volume changes committed.")


@app.function()
def main():
    markdown_content = get_webpage_as_markdown.remote(url=URL)
    records = get_scores.remote(content=markdown_content)
    prep_db.remote(records=records)


@app.function(
    image=datasette_image,
    volumes={VOLUME_DIR: volume},
    allow_concurrent_inputs=16,
)
@modal.asgi_app()
def ui():
    from datasette.app import Datasette

    ds = Datasette(files=[DB_PATH], settings={"sql_time_limit_ms": 10000})
    asyncio.run(ds.invoke_startup())
    return ds.app()


@app.local_entrypoint()
def run():
    print("Getting data...")
    main.remote()
