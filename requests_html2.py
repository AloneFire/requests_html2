from types import TracebackType
from httpx import Client, AsyncClient, Response, Cookies
from httpx._client import USE_CLIENT_DEFAULT, UseClientDefault
from httpx._models import Response
from httpx._types import (
    AuthTypes,
    CookieTypes,
    HeaderTypes,
    QueryParamTypes,
    RequestExtensions,
    TimeoutTypes,
    URLTypes,
)
from playwright.sync_api import sync_playwright
from playwright.async_api import async_playwright
from typing import Union, Optional, List
import os
from pyquery import PyQuery
from lxml import html as lhtml
from lxml.html.soupparser import fromstring as soup_parse
from urllib.parse import urlparse, urlunparse, urljoin
from contextlib import contextmanager, asynccontextmanager


_Session = Union["HTMLSession", "AsyncHTMLSession"]

# install chromium
os.system("playwright install chromium")

DEFAULT_ENCODING = "utf8"


class QueryList(List):
    def select(self, result_filter=None, first=False, default=None):
        if first:
            if not self:
                return default
            else:
                return result_filter(self[0]) if result_filter else self[0]
        if result_filter:
            return QueryList(map(result_filter, self))

    def where(self, result_filter) -> "QueryList":
        return QueryList(filter(result_filter, self))

    def length(self) -> int:
        return len(self)

    def first(self, default=None):
        return self[0] if self else default


class Element:
    def __init__(
        self, element: lhtml.HtmlElement, url: str, encoding=DEFAULT_ENCODING
    ) -> None:
        self.element = element
        self.url = url
        self._pq = None
        self.encoding = encoding
        self._attrs = {}

    @property
    def html(self):
        return (
            lhtml.tostring(self.element, encoding=self.encoding)
            .decode(self.encoding)
            .strip()
        )

    @property
    def pq(self) -> PyQuery:
        if self._pq is None:
            self._pq = PyQuery(self.element)
        return self._pq

    def find(self, selector: str) -> QueryList["Element"]:
        """ """
        elements = [Element(element=found, url=self.url) for found in self.pq(selector)]
        return QueryList(elements)

    def xpath(
        self,
        selector: str,
    ) -> QueryList["Element"]:
        selected = self.element.xpath(selector)
        elements = [
            Element(
                element=selection,
                url=self.url,
            )
            for selection in selected
        ]
        return QueryList(elements)

    @property
    def text(self) -> str:
        return self.pq.text()

    @property
    def full_text(self) -> str:
        return self.element.text_content()

    @property
    def links(self) -> QueryList[str]:
        """
        页面上找到的所有链接，以原样形式呈现。
        """

        def gen():
            for link in self.find("a"):
                try:
                    href = link.attrs["href"].strip()
                    if (
                        href
                        and not (href.startswith("#"))
                        and not href.startswith(("javascript:", "mailto:"))
                    ):
                        yield href
                except KeyError:
                    pass

        return QueryList(set(gen()))

    def _make_absolute(self, link):
        """
        将给定链接转换为绝对链接
        """

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
    def absolute_links(self) -> QueryList[str]:
        """
        页面上找到的所有链接，以绝对路径形式呈现
        (`learn more <https://www.navegabem.com/absolute-or-relative-links.html>`_).
        """

        def gen():
            for link in self.links:
                yield self._make_absolute(link)

        return QueryList(set(gen()))

    @property
    def base_url(self) -> str:
        """
        The base URL for the page. Supports the ``<base>`` tag
        (`learn more <https://www.w3schools.com/tags/tag_base.asp>`_).
        """

        # Support for <base> tag.
        base = self.find("base").first()
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

    def __repr__(self) -> str:
        attrs = ["{}={}".format(attr, repr(self.attrs[attr])) for attr in self.attrs]
        return "<Element {} {}>".format(repr(self.element.tag), " ".join(attrs))

    @property
    def attrs(self) -> dict:
        """Returns a dictionary of the attributes of the :class:`Element <Element>`
        (`learn more <https://www.w3schools.com/tags/ref_attributes.asp>`_).
        """
        if not self._attrs:
            self._attrs = {k: v for k, v in self.element.items()}

            # Split class and rel up, as there are usually many of them:
            for attr in ["class", "rel"]:
                if attr in self._attrs:
                    self._attrs[attr] = tuple(self._attrs[attr].split())

        return self._attrs


class HTML(Element):
    def __init__(self, html: str, url: str, encoding=DEFAULT_ENCODING) -> None:
        element = soup_parse(html, features="html.parser")
        super().__init__(element=element, url=url, encoding=encoding)


class HTMLCookies(Cookies):
    def to_dict_list(self):
        result = []
        for domain_item in self.jar._cookies.values():
            for path_item in domain_item.values():
                for cookie in path_item.values():
                    cookie_dict = {
                        "name": cookie.name,
                        "value": cookie.value,
                        "domain": cookie.domain,
                        "path": cookie.path,
                        "secure": cookie.secure,
                    }
                    if cookie.expires is not None:
                        cookie_dict["expires"] = cookie.expires
                    if cookie._rest.get("HttpOnly"):
                        cookie_dict["httpOnly"] = cookie._rest["HttpOnly"]
                    elif cookie._rest.get("SameSite"):
                        cookie_dict["sameSite"] = cookie._rest["SameSite"]
                    result.append(cookie_dict)
        return result


class HTMLResponse(Response):
    def __init__(self, session: _Session, status_code: int, **kwargs):
        super().__init__(status_code=status_code, **kwargs)
        self.session = session
        self._html = None
        self.page = None

    @property
    def html(self) -> HTML:
        if self._html is None:
            self._html = HTML(self.content, str(self.url))
        return self._html

    @classmethod
    def from_httpx_response(
        cls, session: _Session, response: Response
    ) -> "HTMLResponse":
        obj = cls(session=session, status_code=response.status_code)
        for k, v in response.__dict__.items():
            setattr(obj, k, v)
        return obj

    @property
    def cookies(self) -> HTMLCookies:
        if not hasattr(self, "_cookies"):
            self._cookies = HTMLCookies()
            self._cookies.extract_cookies(self)
        return self._cookies

    @contextmanager
    def render(self, reload=False, **kwargs):
        try:
            context = self.session.browser.new_context()
            if self.cookies:
                context.add_cookies(self.cookies.to_dict_list())
            page = context.new_page()
            if reload:
                page.goto(str(self.url), **kwargs)
            else:
                page.goto(f"data:text/html,{self.content}", **kwargs)
            self.page = page
            self.refresh_html()
            yield page
        finally:
            self.page = None
            page.close()
            context.close()

    def refresh_html(self, encoding=DEFAULT_ENCODING):
        if self.page:
            self._content = self.page.content()
            self._html = HTML(self.content, str(self.url), encoding=encoding)

    @asynccontextmanager
    async def async_render(self, reload=False, **kwargs):
        browser = await self.session.browser
        context = await browser.new_context()
        try:
            if self.cookies:
                await context.add_cookies(self.cookies.to_dict_list())
            page = await context.new_page()
            if reload:
                await page.goto(str(self.url), **kwargs)
            else:
                await page.goto(f"data:text/html,{self.content}", **kwargs)
            self.page = page
            await self.async_refresh_html()
            yield page
        finally:
            self.page = None
            await page.close()
            await context.close()

    async def async_refresh_html(self, encoding=DEFAULT_ENCODING):
        if self.page:
            self._content = await self.page.content()
            self._html = HTML(self.content, str(self.url), encoding=encoding)


class HTMLSession(Client):
    _playwright = None
    _browser = None

    def __init__(self, browser_launch_args: dict = {}, **kwargs):
        self.browser_launch_args = browser_launch_args
        super().__init__(**kwargs)

    @property
    def browser(self):
        if self._browser is None:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(**self.browser_launch_args)
        return self._browser

    def __exit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        if self._browser:
            self._browser.close()
            self._playwright.stop()
            self._browser = None
            self._playwright = None
        return super().__exit__(exc_type, exc_value, traceback)

    def close(self) -> None:
        if self._browser:
            self._browser.close()
            self._playwright.stop()
            self._browser = None
            self._playwright = None
        return super().close()

    def request(self, *args, **kwargs) -> HTMLResponse:
        response = super().request(*args, **kwargs)
        return HTMLResponse.from_httpx_response(session=self, response=response)

    def get(
        self,
        url: URLTypes,
        *,
        params: Optional[QueryParamTypes] = None,
        headers: Optional[HeaderTypes] = None,
        cookies: Optional[CookieTypes] = None,
        auth: Union[AuthTypes, UseClientDefault] = USE_CLIENT_DEFAULT,
        follow_redirects: Union[bool, UseClientDefault] = USE_CLIENT_DEFAULT,
        timeout: Union[TimeoutTypes, UseClientDefault] = USE_CLIENT_DEFAULT,
        extensions: Optional[RequestExtensions] = None,
    ) -> HTMLResponse:
        """
        Send a `GET` request.

        **Parameters**: See `httpx.request`.
        """
        return self.request(
            "GET",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            auth=auth,
            follow_redirects=follow_redirects,
            timeout=timeout,
            extensions=extensions,
        )


class AsyncHTMLSession(AsyncClient):
    _playwright = None
    _browser = None

    def __init__(self, browser_launch_args: dict = {}, **kwargs):
        self.browser_launch_args = browser_launch_args
        super().__init__(**kwargs)

    @property
    async def browser(self):
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                **self.browser_launch_args
            )
        return self._browser

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        if self._browser:
            await self._browser.close()
            await self._playwright.stop()
            self._browser = None
            self._playwright = None
        return await super().__aexit__(exc_type, exc_value, traceback)

    async def aclose(self) -> None:
        if self._browser:
            await self._browser.close()
            await self._playwright.stop()
            self._browser = None
            self._playwright = None
        return await super().aclose()

    async def request(self, *args, **kwargs) -> HTMLResponse:
        response = await super().request(*args, **kwargs)
        return HTMLResponse.from_httpx_response(session=self, response=response)

    async def get(
        self,
        url: URLTypes,
        *,
        params: Optional[QueryParamTypes] = None,
        headers: Optional[HeaderTypes] = None,
        cookies: Optional[CookieTypes] = None,
        auth: Union[AuthTypes, UseClientDefault] = USE_CLIENT_DEFAULT,
        follow_redirects: Union[bool, UseClientDefault] = USE_CLIENT_DEFAULT,
        timeout: Union[TimeoutTypes, UseClientDefault] = USE_CLIENT_DEFAULT,
        extensions: Optional[RequestExtensions] = None,
    ) -> HTMLResponse:
        """
        Send a `GET` request.

        **Parameters**: See `httpx.request`.
        """
        return await self.request(
            "GET",
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            auth=auth,
            follow_redirects=follow_redirects,
            timeout=timeout,
            extensions=extensions,
        )
