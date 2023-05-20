from requests_html2 import HTMLSession
from pprint import pprint

DEBUG = False

# 会话初始化
session = HTMLSession(
    browser_args={
        "headless": not DEBUG,
        "defaultViewport": None,
        "autoClose": True,
        "args": ["--no-sandbox", "--user-data-dir=./temp/"],
    }
)

resp = session.get("https://www.smzdm.com/")
if DEBUG:
    # 浏览器渲染
    resp.html.render(keep_page=True, reload=False)
data = [
    {
        "name": item.find(".feed-block-title", first=True).text,
        "price": item.find(".z-highlight").select(
            lambda e: e.text, first=True, default=""
        ),
        "platform": item.find(".article-mall").select(
            lambda e: e.text, first=True, default=""
        ),
        "image": item.find(".z-feed-img img", first=True).attrs.get("src"),
        "detail": item.find(".z-feed-img a").select(
            lambda e: e.attrs["href"]
            if e.attrs.get("href") and e.attrs["href"] != "javascript:;"
            else "",
            first=True,
            default="",
        ),
        "link": item.find(".feed-link-btn-inner a").select(
            lambda e: e.attrs.get("href"), first=True, default=""
        ),
    }
    for item in resp.html.find("#feed-main-list>li")
]
pprint(data)
