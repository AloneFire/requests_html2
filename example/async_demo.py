import asyncio
from requests_html2 import AsyncHTMLSession
from pprint import pprint


async def main():
    async with AsyncHTMLSession(browser_launch_args={"headless": False}) as session:
        resp = await session.get("https://www.smzdm.com/jingxuan/")
        async with resp.async_render(reload=True) as page:
            print(resp.html.xpath("/html/head/title").first().text)
            print("=" * 80)
            for _ in range(3):
                await page.keyboard.press("PageDown")
                await asyncio.sleep(1)
            await resp.async_refresh_html()

        top10 = resp.html.find(".feed-hot-card")[30:40]
        for good in top10:
            pprint(
                {
                    "title": good.find(".feed-hot-title").select(
                        lambda e: e.text, first=True, default=""
                    ),
                    "tips": good.find(".z-highlight").select(
                        lambda e: e.text, first=True, default=""
                    ),
                    "img": good.find(".feed-hot-pic img").select(
                        lambda e: e.attrs.get("src", ""), first=True
                    ),
                    "link": good.find("a").select(
                        lambda e: e.links.first(), first=True, default=""
                    ),
                }
            )


if __name__ == "__main__":
    asyncio.run(main())
