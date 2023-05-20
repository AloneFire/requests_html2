import sys
import asyncio
from urllib.parse import urlparse, urlunparse, urljoin
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures._base import TimeoutError
from functools import partial
from typing import Set, Union, List, MutableMapping, Optional

import pyppeteer
import requests
from requests.cookies import cookiejar_from_dict
import http.cookiejar
from pyquery import PyQuery

from fake_useragent import UserAgent
from lxml.html.clean import Cleaner
import lxml
from lxml import etree
from lxml.html import HtmlElement
from lxml.html import tostring as lxml_html_tostring
from lxml.html.soupparser import fromstring as soup_parse
from parse import search as parse_search
from parse import findall, Result
from w3lib.encoding import html_to_unicode

DEFAULT_ENCODING = "utf-8"
DEFAULT_URL = "https://example.org/"
DEFAULT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) AppleWebKit/603.3.8 (KHTML, like Gecko) Version/10.1.2 Safari/603.3.8"
# 分页导航元素
DEFAULT_NEXT_SYMBOL = ["next", "more", "older", "下一页"]

cleaner = Cleaner()
cleaner.javascript = True
cleaner.style = True

useragent = None


class FindQueryList(list):
    def select(self, result_filter=None, first=False, default=None):
        if first:
            if not self:
                return default
            else:
                return result_filter(self[0]) if result_filter else self[0]
        if result_filter:
            return FindQueryList(map(result_filter, self))

    def where(self, result_filter):
        return FindQueryList(filter(result_filter, self))


# Typing.
_Find = Union[FindQueryList["Element"], "Element"]
_XPath = Union[FindQueryList[str], FindQueryList["Element"], str, "Element"]
_Result = Union[List["Result"], "Result"]
_HTML = Union[str, bytes]
_BaseHTML = str
_UserAgent = str
_DefaultEncoding = str
_URL = str
_RawHTML = bytes
_Encoding = str
_LXML = HtmlElement
_Text = str
_Search = Result
_Containing = Union[str, List[str]]
_Links = FindQueryList[str]
_Attrs = MutableMapping
_Next = Union["HTML", List[str]]
_NextSymbol = List[str]

# Sanity checking.
try:
    assert sys.version_info.major == 3
    assert sys.version_info.minor > 5
except AssertionError:
    raise RuntimeError("Requests-HTML requires Python 3.6+!")


class MaxRetries(Exception):
    def __init__(self, message):
        self.message = message


class BaseParser:
    """一个基本的HTML/元素解析器。
    :param element: 解析的基础元素。
    :param default_encoding: 默认使用的编码。
    :param html: 用于解析的HTML（可选）。
    :param url: HTML来源的URL，用于``absolute_links``。
    """

    def __init__(
        self,
        *,
        element,
        default_encoding: _DefaultEncoding = None,
        html: _HTML = None,
        url: _URL,
    ) -> None:
        self.element = element
        self.url = url
        self.skip_anchors = True
        self.default_encoding = default_encoding
        self._encoding = None
        self._html = html.encode(DEFAULT_ENCODING) if isinstance(html, str) else html
        self._lxml = None
        self._pq = None

    @property
    def raw_html(self) -> _RawHTML:
        """HTML内容的字节表示
        (`learn more <http://www.diveintopython3.net/strings.html>`_).
        """
        if self._html:
            return self._html
        else:
            return (
                etree.tostring(self.element, encoding="unicode")
                .strip()
                .encode(self.encoding)
            )

    @property
    def html(self) -> _BaseHTML:
        """HTML内容的Unicode表示
        (`learn more <http://www.diveintopython3.net/strings.html>`_).
        """
        if self._html:
            return self.raw_html.decode(self.encoding, errors="replace")
        else:
            return etree.tostring(self.element, encoding="unicode").strip()

    @html.setter
    def html(self, html: str) -> None:
        self._html = html.encode(self.encoding)

    @raw_html.setter
    def raw_html(self, html: bytes) -> None:
        """Property setter for self.html."""
        self._html = html

    @property
    def encoding(self) -> _Encoding:
        """要使用的编码字符串, extracted from the HTML and
        :class:`HTMLResponse <HTMLResponse>` headers.
        """
        if self._encoding:
            return self._encoding

        # Scan meta tags for charset.
        if self._html:
            self._encoding = html_to_unicode(self.default_encoding, self._html)[0]
            # Fall back to requests' detected encoding if decode fails.
            try:
                self.raw_html.decode(self.encoding, errors="replace")
            except UnicodeDecodeError:
                self._encoding = self.default_encoding

        return self._encoding if self._encoding else self.default_encoding

    @encoding.setter
    def encoding(self, enc: str) -> None:
        """Property setter for self.encoding."""
        self._encoding = enc

    @property
    def pq(self) -> PyQuery:
        """`PyQuery <https://pythonhosted.org/pyquery/>`_ representation
        of the :class:`Element <Element>` or :class:`HTML <HTML>`.
        """
        if self._pq is None:
            self._pq = PyQuery(self.lxml)

        return self._pq

    @property
    def lxml(self) -> HtmlElement:
        """`lxml <http://lxml.de>`_ representation of the
        :class:`Element <Element>` or :class:`HTML <HTML>`.
        """
        if self._lxml is None:
            try:
                self._lxml = soup_parse(self.html, features="html.parser")
            except ValueError:
                self._lxml = lxml.html.fromstring(self.raw_html)

        return self._lxml

    @property
    def text(self) -> _Text:
        """The text content of the
        :class:`Element <Element>` or :class:`HTML <HTML>`.
        """
        return self.pq.text()

    @property
    def full_text(self) -> _Text:
        """The full text content (including links) of the
        :class:`Element <Element>` or :class:`HTML <HTML>`.
        """
        return self.lxml.text_content()

    def find(
        self,
        selector: str = "*",
        *,
        containing: _Containing = None,
        clean: bool = False,
        first: bool = False,
        _encoding: str = None,
    ) -> _Find:
        """根据CSS选择器返回,
        :class:`Element <Element>` 对象列表或单个对象.

        :param selector: CSS选择器.
        :param clean: 是否排除 ``<script>`` and ``<style>`` tags.
        :param containing: 指定包含的文本，仅返回包含提供文本的元素
        :param first: 是否仅返回第一个结果
        :param _encoding: 编码格式

        Example CSS Selectors:

        - ``a``
        - ``a.someClass``
        - ``a#someID``
        - ``a[target=_blank]``

        See W3School's `CSS Selectors Reference
        <https://www.w3schools.com/cssref/css_selectors.asp>`_
        for more details.

        If ``first`` is ``True``, only returns the first
        :class:`Element <Element>` found.
        """

        # Convert a single containing into a list.
        if isinstance(containing, str):
            containing = [containing]

        encoding = _encoding or self.encoding
        elements = [
            Element(element=found, url=self.url, default_encoding=encoding)
            for found in self.pq(selector)
        ]

        if containing:
            elements_copy = elements.copy()
            elements = []

            for element in elements_copy:
                if any([c.lower() in element.full_text.lower() for c in containing]):
                    elements.append(element)

            elements.reverse()

        # Sanitize the found HTML.
        if clean:
            elements_copy = elements.copy()
            elements = []

            for element in elements_copy:
                element.raw_html = lxml_html_tostring(cleaner.clean_html(element.lxml))
                elements.append(element)

        return _get_first_or_list(elements, first)

    def xpath(
        self,
        selector: str,
        *,
        clean: bool = False,
        first: bool = False,
        _encoding: str = None,
    ) -> _XPath:
        """根据XPath选择器返回
        :class:`Element <Element>` 对象列表或单个对象.

        :param selector: XPath选择器.
        :param clean: 是否排除 ``<script>`` and ``<style>`` tags.
        :param first: 是否仅返回第一个结果
        :param _encoding: 编码格式

        If a sub-selector is specified (e.g. ``//a/@href``), a simple
        list of results is returned.

        See W3School's `XPath Examples
        <https://www.w3schools.com/xml/xpath_examples.asp>`_
        for more details.

        If ``first`` is ``True``, only returns the first
        :class:`Element <Element>` found.
        """
        selected = self.lxml.xpath(selector)

        elements = [
            Element(
                element=selection,
                url=self.url,
                default_encoding=_encoding or self.encoding,
            )
            if not isinstance(selection, etree._ElementUnicodeResult)
            else str(selection)
            for selection in selected
        ]

        # Sanitize the found HTML.
        if clean:
            elements_copy = elements.copy()
            elements = []

            for element in elements_copy:
                element.raw_html = lxml_html_tostring(cleaner.clean_html(element.lxml))
                elements.append(element)

        return _get_first_or_list(elements, first)

    def search(self, template: str) -> Result:
        """根据模板搜索返回解析结果
        Search the :class:`Element <Element>` for the given Parse template.
        :param template: The Parse template to use.
        """

        return parse_search(template, self.html)

    def search_all(self, template: str) -> _Result:
        """根据模板搜索返回所有结果
        Search the :class:`Element <Element>` (multiple times) for the given parse
        template.

        :param template: The Parse template to use.
        """
        return [r for r in findall(template, self.html)]

    @property
    def links(self) -> _Links:
        """页面上找到的所有链接，以原样形式呈现。"""

        def gen():
            for link in self.find("a"):
                try:
                    href = link.attrs["href"].strip()
                    if (
                        href
                        and not (href.startswith("#") and self.skip_anchors)
                        and not href.startswith(("javascript:", "mailto:"))
                    ):
                        yield href
                except KeyError:
                    pass

        return FindQueryList(set(gen()))

    def _make_absolute(self, link):
        """将给定链接转换为绝对链接。"""

        # Parse the link with stdlib.
        parsed = urlparse(link)._asdict()

        # If link is relative, then join it with base_url.
        if not parsed["netloc"]:
            return urljoin(self.base_url, link)

        # Link is absolute; if it lacks a scheme, add one from base_url.
        if not parsed["scheme"]:
            parsed["scheme"] = urlparse(self.base_url).scheme

            # Reconstruct the URL to incorporate the new scheme.
            parsed = (v for v in parsed.values())
            return urlunparse(parsed)

        # Link is absolute and complete with scheme; nothing to be done here.
        return link

    @property
    def absolute_links(self) -> _Links:
        """页面上找到的所有链接，以绝对路径形式呈现
        (`learn more <https://www.navegabem.com/absolute-or-relative-links.html>`_).
        """

        def gen():
            for link in self.links:
                yield self._make_absolute(link)

        return FindQueryList(set(gen()))

    @property
    def base_url(self) -> _URL:
        """The base URL for the page. Supports the ``<base>`` tag
        (`learn more <https://www.w3schools.com/tags/tag_base.asp>`_)."""

        # Support for <base> tag.
        base = self.find("base", first=True)
        if base:
            result = base.attrs.get("href", "").strip()
            if result:
                return result

        # Parse the url to separate out the path
        parsed = urlparse(self.url)._asdict()

        # Remove any part of the path after the last '/'
        parsed["path"] = "/".join(parsed["path"].split("/")[:-1]) + "/"

        # Reconstruct the url with the modified path
        parsed = (v for v in parsed.values())
        url = urlunparse(parsed)

        return url


class Element(BaseParser):
    """An element of HTML.

    :param element: The element from which to base the parsing upon.
    :param url: The URL from which the HTML originated, used for ``absolute_links``.
    :param default_encoding: Which encoding to default to.
    """

    __slots__ = [
        "element",
        "url",
        "skip_anchors",
        "default_encoding",
        "_encoding",
        "_html",
        "_lxml",
        "_pq",
        "_attrs",
        "session",
    ]

    def __init__(
        self, *, element, url: _URL, default_encoding: _DefaultEncoding = None
    ) -> None:
        super(Element, self).__init__(
            element=element, url=url, default_encoding=default_encoding
        )
        self.element = element
        self.tag = element.tag
        self.lineno = element.sourceline
        self._attrs = None

    def __repr__(self) -> str:
        attrs = ["{}={}".format(attr, repr(self.attrs[attr])) for attr in self.attrs]
        return "<Element {} {}>".format(repr(self.element.tag), " ".join(attrs))

    @property
    def attrs(self) -> _Attrs:
        """Returns a dictionary of the attributes of the :class:`Element <Element>`
        (`learn more <https://www.w3schools.com/tags/ref_attributes.asp>`_).
        """
        if self._attrs is None:
            self._attrs = {k: v for k, v in self.element.items()}

            # Split class and rel up, as there are usually many of them:
            for attr in ["class", "rel"]:
                if attr in self._attrs:
                    self._attrs[attr] = tuple(self._attrs[attr].split())

        return self._attrs


class HTML(BaseParser):
    """An HTML document, ready for parsing.

    :param url: The URL from which the HTML originated, used for ``absolute_links``.
    :param html: HTML from which to base the parsing upon (optional).
    :param default_encoding: Which encoding to default to.
    """

    def __init__(
        self,
        *,
        session: Union["HTMLSession", "AsyncHTMLSession"] = None,
        url: str = DEFAULT_URL,
        html: _HTML,
        default_encoding: str = DEFAULT_ENCODING,
        async_: bool = False,
    ) -> None:
        # Convert incoming unicode HTML into bytes.
        if isinstance(html, str):
            html = html.encode(DEFAULT_ENCODING)

        pq = PyQuery(html)
        super(HTML, self).__init__(
            element=pq("html") or pq.wrapAll("<html></html>")("html"),
            html=html,
            url=url,
            default_encoding=default_encoding,
        )
        self.session = session or async_ and AsyncHTMLSession() or HTMLSession()
        self.page = None
        self.next_symbol = DEFAULT_NEXT_SYMBOL

    def __repr__(self) -> str:
        return f"<HTML url={self.url!r}>"

    def next(self, fetch: bool = False, next_symbol: _NextSymbol = None) -> _Next:
        """
        根据``next_symbol``(下一页的关键词列表)尝试查找下一页（如果有）。
        如果  fetch  是  True （默认值），则返回下一页的HTML对象。 如果  fetch  是  False ，则只返回下一页的URL。
        Attempts to find the next page, if there is one. If ``fetch``
        is ``True`` (default), returns :class:`HTML <HTML>` object of
        next page. If ``fetch`` is ``False``, simply returns the next URL.

        """
        if next_symbol is None:
            next_symbol = self.next_symbol

        def get_next():
            candidates = self.find("a", containing=next_symbol)

            for candidate in candidates:
                if candidate.attrs.get("href"):
                    # Support 'next' rel (e.g. reddit).
                    if "next" in candidate.attrs.get("rel", []):
                        return candidate.attrs["href"]

                    # Support 'next' in classnames.
                    for _class in candidate.attrs.get("class", []):
                        if "next" in _class:
                            return candidate.attrs["href"]

                    if "page" in candidate.attrs["href"]:
                        return candidate.attrs["href"]

            try:
                # Resort to the last candidate.
                return candidates[-1].attrs["href"]
            except IndexError:
                return None

        __next = get_next()
        if __next:
            url = self._make_absolute(__next)
        else:
            return None

        if fetch:
            return self.session.get(url)
        else:
            return url

    def __iter__(self):
        next = self

        while True:
            yield next
            try:
                next = next.next(fetch=True, next_symbol=self.next_symbol).html
            except AttributeError:
                break

    def __next__(self):
        return self.next(fetch=True, next_symbol=self.next_symbol).html

    def __aiter__(self):
        return self

    async def __anext__(self):
        while True:
            url = self.next(fetch=False, next_symbol=self.next_symbol)
            if not url:
                break
            response = await self.session.get(url)
            return response.html

    def add_next_symbol(self, next_symbol):
        """增加翻页检索关键词"""
        self.next_symbol.append(next_symbol)

    async def _async_render(
        self,
        *,
        url: str,
        script: str = None,
        scrolldown,
        sleep: int,
        wait: float,
        reload,
        content: Optional[str],
        timeout: Union[float, int],
        keep_page: bool,
        cookies: list = [{}],
    ):
        """处理页面创建和JavaScript渲染。. Internal use for render/arender methods."""
        try:
            # pyppeteer 创建新标签页
            page = await self.browser.newPage()

            # 页面加载前等待
            await asyncio.sleep(wait)

            if cookies:
                for cookie in cookies:
                    if cookie:
                        await page.setCookie(cookie)

            # Load the given page (GET request, obviously.)
            if reload:
                await page.goto(url, options={"timeout": int(timeout * 1000)})
            else:
                await page.goto(
                    f"data:text/html,{self.html}",
                    options={"timeout": int(timeout * 1000)},
                )

            result = None
            if script:
                result = await page.evaluate(script)

            if scrolldown:
                for _ in range(scrolldown):
                    await page._keyboard.down("PageDown")
                    await asyncio.sleep(sleep)
            else:
                await asyncio.sleep(sleep)

            if scrolldown:
                await page._keyboard.up("PageDown")

            # Return the content of the page, JavaScript evaluated.
            content = await page.content()
            if not keep_page:
                await page.close()
                page = None
            return content, result, page
        except TimeoutError:
            await page.close()
            page = None
            return None

    def _convert_cookiejar_to_render(self, session_cookiejar):
        """
        Convert HTMLSession.cookies:cookiejar[] for browser.newPage().setCookie
        """
        # |  setCookie(self, *cookies:dict) -> None
        # |      Set cookies.
        # |
        # |      ``cookies`` should be dictionaries which contain these fields:
        # |
        # |      * ``name`` (str): **required**
        # |      * ``value`` (str): **required**
        # |      * ``url`` (str)
        # |      * ``domain`` (str)
        # |      * ``path`` (str)
        # |      * ``expires`` (number): Unix time in seconds
        # |      * ``httpOnly`` (bool)
        # |      * ``secure`` (bool)
        # |      * ``sameSite`` (str): ``'Strict'`` or ``'Lax'``
        cookie_render = {}

        def __convert(cookiejar, key):
            try:
                v = eval("cookiejar." + key)
                if not v:
                    kv = ""
                else:
                    kv = {key: v}
            except:
                kv = ""
            return kv

        keys = [
            "name",
            "value",
            "url",
            "domain",
            "path",
            "sameSite",
            "expires",
            "httpOnly",
            "secure",
        ]
        for key in keys:
            cookie_render.update(__convert(session_cookiejar, key))
        return cookie_render

    def _convert_cookiesjar_to_render(self):
        """
        Convert HTMLSession.cookies for browser.newPage().setCookie
        Return a list of dict
        """
        cookies_render = []
        if isinstance(self.session.cookies, http.cookiejar.CookieJar):
            for cookie in self.session.cookies:
                convert = self._convert_cookiejar_to_render(cookie)
                convert["url"] = self.url
                cookies_render.append(convert)
        return cookies_render

    def render(
        self,
        retries: int = 8,
        script: str = None,
        wait: float = 0.2,
        scrolldown=False,
        sleep: int = 0,
        reload: bool = True,
        timeout: Union[float, int] = 8.0,
        keep_page: bool = False,
        cookies: list = [{}],
        send_cookies_session: bool = False,
    ):
        """重新加载，带有JavaScript执行的版本的响应。
        :param retries: 在Chromium中重试加载页面的次数。
        :param script: 页面加载时要执行的JavaScript（可选）。
        :param wait: 在加载页面前等待的秒数（可选）。
        :param scrolldown: 如果提供，整数，表示要向下滚动的次数。.
        :param sleep: 滚动一次停顿或者加载完成后等待的时长，等待页面Ajax请求加载完成，整数秒数
        :param reload: 如果`False`  ，则不会从浏览器加载内容，而是将从内存提供内容。
        :param keep_page: 如果`True` ，将允许您通过`r.html.page`与浏览器页面交互。

        :param send_cookies_session: If ``True`` send ``HTMLSession.cookies`` convert.
        :param cookies: If not ``empty`` send ``cookies``.

        If ``scrolldown`` is specified, the page will scrolldown the specified
        number of times, after sleeping the specified amount of time
        (e.g. ``scrolldown=10, sleep=1``).

        If just ``sleep`` is provided, the rendering will wait *n* seconds, before
        returning.

        If ``script`` is specified, it will execute the provided JavaScript at
        runtime. Example:

        .. code-block:: python

            script = \"\"\"
                () => {
                    return {
                        width: document.documentElement.clientWidth,
                        height: document.documentElement.clientHeight,
                        deviceScaleFactor: window.devicePixelRatio,
                    }
                }
            \"\"\"

        Returns the return value of the executed  ``script``, if any is provided:

        .. code-block:: python

            >>> r.html.render(script=script)
            {'width': 800, 'height': 600, 'deviceScaleFactor': 1}

        Warning: the first time you run this method, it will download
        Chromium into your home directory (``~/.pyppeteer``).
        """

        self.browser = (
            self.session.browser
        )  # Automatically create a event loop and browser
        content = None

        # Automatically set Reload to False, if example URL is being used.
        if self.url == DEFAULT_URL:
            reload = False

        if send_cookies_session:
            cookies = self._convert_cookiesjar_to_render()

        for i in range(retries):
            if not content:
                try:
                    content, result, page = self.session.loop.run_until_complete(
                        self._async_render(
                            url=self.url,
                            script=script,
                            sleep=sleep,
                            wait=wait,
                            content=self.html,
                            reload=reload,
                            scrolldown=scrolldown,
                            timeout=timeout,
                            keep_page=keep_page,
                            cookies=cookies,
                        )
                    )
                except TypeError:
                    pass
            else:
                break

        if not content:
            raise MaxRetries("Unable to render the page. Try increasing timeout")

        html = HTML(
            url=self.url,
            html=content.encode(DEFAULT_ENCODING),
            default_encoding=DEFAULT_ENCODING,
        )
        self.__dict__.update(html.__dict__)
        self.page = page
        return result

    async def arender(
        self,
        retries: int = 8,
        script: str = None,
        wait: float = 0.2,
        scrolldown=False,
        sleep: int = 0,
        reload: bool = True,
        timeout: Union[float, int] = 8.0,
        keep_page: bool = False,
        cookies: list = [{}],
        send_cookies_session: bool = False,
    ):
        """Async version of render. Takes same parameters."""

        self.browser = await self.session.browser
        content = None

        # Automatically set Reload to False, if example URL is being used.
        if self.url == DEFAULT_URL:
            reload = False

        if send_cookies_session:
            cookies = self._convert_cookiesjar_to_render()

        for _ in range(retries):
            if not content:
                try:
                    content, result, page = await self._async_render(
                        url=self.url,
                        script=script,
                        sleep=sleep,
                        wait=wait,
                        content=self.html,
                        reload=reload,
                        scrolldown=scrolldown,
                        timeout=timeout,
                        keep_page=keep_page,
                        cookies=cookies,
                    )
                except TypeError:
                    pass
            else:
                break

        if not content:
            raise MaxRetries("Unable to render the page. Try increasing timeout")

        html = HTML(
            url=self.url,
            html=content.encode(DEFAULT_ENCODING),
            default_encoding=DEFAULT_ENCODING,
        )
        self.__dict__.update(html.__dict__)
        self.page = page
        return result


class HTMLResponse(requests.Response):
    """An HTML-enabled :class:`requests.Response <requests.Response>` object.
    Effectively the same, but with an intelligent ``.html`` property added.
    """

    def __init__(self, session: Union["HTMLSession", "AsyncHTMLSession"]) -> None:
        super(HTMLResponse, self).__init__()
        self._html = None  # type: HTML
        self.session = session

    @property
    def html(self) -> HTML:
        if not self._html:
            self._html = HTML(
                session=self.session,
                url=self.url,
                html=self.content,
                default_encoding=self.encoding,
            )

        return self._html

    @classmethod
    def _from_response(
        cls, response, session: Union["HTMLSession", "AsyncHTMLSession"]
    ):
        html_r = cls(session=session)
        html_r.__dict__.update(response.__dict__)
        return html_r


def mock_user_agent(style=None) -> _UserAgent:
    """
    生成 FakeUserAgent
    Returns an apparently legit user-agent, if not requested one of a specific
    style. Defaults to a Chrome-style User-Agent.
    """
    global useragent
    if (not useragent) and style:
        useragent = UserAgent()

    return useragent[style] if style and style != "default" else DEFAULT_USER_AGENT


def _get_first_or_list(l, first=False):
    if first:
        try:
            return l[0]
        except IndexError:
            return None
    else:
        return FindQueryList(l)


class BaseSession(requests.Session):
    """会话，用于Cookie持久性和连接池等功能
    A consumable session, for cookie persistence and connection pooling,
    amongst other things.

    """

    def __init__(
        self,
        user_agent: str = None,
        mock_browser_style: str = None,
        verify: bool = True,
        browser_args: dict = {"headless": True, "args": ["--no-sandbox"]},
        cookies: dict = {},
        proxies: dict = {},
    ):
        """
        :param user_agent: 设置 User-Agent
        :param mock_browser_style: Mock User-Agent （set 'default' use DEFAULT_USER_AGENT）
        :param verify: 控制是否验证证书
        :param browser_args: 浏览器初始化参数
            -  headless ：设置是否为无头模式，默认为  True 。
            -  defaultViewport：设置默认窗口大小
            -  args ：设置 Chrome 启动时的参数列表，传入一个 List。
            -  executablePath ：设置可执行文件的路径。
            -  slowMo ：将操作延迟指定毫秒数，用于调试。
            -  timeout ：设置等待 Chrome 实例启动的时间。
            -  dumpio ：设置是否将 stdout 和 stderr 导入到父进程的 stdout 和 stderr 中。
            -  userDataDir ：设置用户数据目录的位置。
        :param cookies: 设置cookie
        :param proxies: 设置代理
        """
        super().__init__()

        # Mock a web browser's user agent.

        if mock_browser_style:
            self.headers["User-Agent"] = user_agent(mock_browser_style)

        if user_agent:
            self.headers["User-Agent"] = user_agent

        if cookies:
            self.cookies = cookiejar_from_dict(cookies)

        if proxies:
            self.proxies = proxies

        self.hooks["response"].append(self.response_hook)
        self.verify = verify

        self.__browser_args = browser_args

    def response_hook(self, response, **kwargs) -> HTMLResponse:
        """Change response encoding and replace it by a HTMLResponse."""
        if not response.encoding:
            response.encoding = DEFAULT_ENCODING
        return HTMLResponse._from_response(response, self)

    @property
    async def browser(self):
        if not hasattr(self, "_browser"):
            # pyppeteer 初始化浏览器实例
            self._browser = await pyppeteer.launch(
                ignoreHTTPSErrors=not (self.verify), **self.__browser_args
            )
        return self._browser

    def get(self, url, **kwargs) -> HTMLResponse:
        r"""Sends a GET request. Returns :class:`Response` object.

        :param url: URL for the new :class:`Request` object.
        :param \*\*kwargs: Optional arguments that ``request`` takes.
        :rtype: requests.Response
        """

        kwargs.setdefault("allow_redirects", True)
        return self.request("GET", url, **kwargs)

    def post(self, url, data=None, json=None, **kwargs) -> HTMLResponse:
        r"""Sends a POST request. Returns :class:`Response` object.

        :param url: URL for the new :class:`Request` object.
        :param data: (optional) Dictionary, list of tuples, bytes, or file-like
            object to send in the body of the :class:`Request`.
        :param json: (optional) json to send in the body of the :class:`Request`.
        :param \*\*kwargs: Optional arguments that ``request`` takes.
        :rtype: requests.Response
        """
        return self.request("POST", url, data=data, json=json, **kwargs)


class HTMLSession(BaseSession):
    def __init__(self, **kwargs):
        super(HTMLSession, self).__init__(**kwargs)

    @property
    def browser(self):
        if not hasattr(self, "_browser"):
            self.loop = asyncio.get_event_loop()
            if self.loop.is_running():
                raise RuntimeError(
                    "Cannot use HTMLSession within an existing event loop. Use AsyncHTMLSession instead."
                )
            self._browser = self.loop.run_until_complete(super().browser)
        return self._browser

    def close(self):
        """If a browser was created close it first."""
        if hasattr(self, "_browser"):
            self.loop.run_until_complete(self._browser.close())
        super().close()


class AsyncHTMLSession(BaseSession):
    """An async consumable session."""

    def __init__(
        self, loop=None, workers=None, mock_browser: bool = True, *args, **kwargs
    ):
        """Set or create an event loop and a thread pool.

        :param loop: Asyncio loop to use.
        :param workers: Amount of threads to use for executing async calls.
            If not pass it will default to the number of processors on the
            machine, multiplied by 5."""
        super().__init__(*args, **kwargs)

        self.loop = loop or asyncio.get_event_loop()
        self.thread_pool = ThreadPoolExecutor(max_workers=workers)

    def request(self, *args, **kwargs):
        """Partial original request func and run it in a thread."""
        func = partial(super().request, *args, **kwargs)
        return self.loop.run_in_executor(self.thread_pool, func)

    async def close(self):
        """If a browser was created close it first."""
        if hasattr(self, "_browser"):
            await self._browser.close()
        super().close()

    def run(self, *coros):
        """Pass in all the coroutines you want to run, it will wrap each one
        in a task, run it and wait for the result. Return a list with all
        results, this is returned in the same order coros are passed in."""
        tasks = [asyncio.ensure_future(coro()) for coro in coros]
        done, _ = self.loop.run_until_complete(asyncio.wait(tasks))
        return [t.result() for t in done]
