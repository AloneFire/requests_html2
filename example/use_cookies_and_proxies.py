from requests_html2 import HTMLSession
import re
from pprint import pprint

# 使用的搜索查询以查找GitHub上的keyworld
query = "{query keyworld}"
match_regex = r"{match regex}"
# 我们查询的GitHub搜索页面的URL
url = f"https://github.com/search?q={query}&type=code"
# 设定代理
proxies = {
    "http": "{server}",
    "https": "{server}",
}

cookies_str = """
{cookies}
"""

session = HTMLSession(
    proxies=proxies,
    browser_args={
        "headless": False,
        "defaultViewport": None,
        "userDataDir": "temp/",
        "args": ["--no-sandbox", f"--proxy-server={proxies['https']}"],
    },
    cookies={
        i.split("=", 1)[0].strip(): i.split("=", 1)[1].strip()
        for i in cookies_str.split(";")
    },
)

# 获取搜索页面的HTML内容
response = session.get(url)
response.html.render(keep_page=True, send_cookies_session=True, timeout=15)
cards = response.html.find("div[data-testid=results-list]>div")
data = []
for card in cards:
    codes = [c.full_text for c in card.find("table td>span")]
    codes = "\n".join(codes)
    links = card.find("div>div>a").select(lambda e: e.absolute_links.select(first=True))
    keys = re.findall(match_regex, codes, re.MULTILINE)
    if keys:
        item = {
            "name": card.find("button", first=True).attrs.get("aria-label"),
            "repository": links[0] if len(links) == 2 else "",
            "file": links[1] if len(links) == 2 else "",
            "results": keys,
        }
        data.append(item)

pprint(data)
