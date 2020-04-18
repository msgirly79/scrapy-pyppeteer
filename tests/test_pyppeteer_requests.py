import subprocess
from tempfile import NamedTemporaryFile

import pyppeteer
import pytest
from scrapy import Spider
from scrapy.http import Request, Response
from scrapy.utils.test import get_crawler

from scrapy_pyppeteer.download_handler import ScrapyPyppeteerDownloadHandler
from scrapy_pyppeteer.page import PageCoroutine, NavigationPageCoroutine

from tests.mockserver import MockServer


@pytest.mark.asyncio
async def test_basic_response():
    handler = ScrapyPyppeteerDownloadHandler(get_crawler())
    await handler._launch_browser()

    with MockServer() as server:
        req = Request(server.urljoin("/index.html"), meta={"pyppeteer": True})
        resp = await handler._download_request(req, Spider("foo"))

    assert isinstance(resp, Response)
    assert resp.request is req
    assert resp.url == req.url
    assert resp.status == 200
    assert "pyppeteer" in resp.flags
    assert resp.css("a::text").getall() == ["Lorem Ipsum", "Infinite Scroll"]

    await handler.browser.close()


@pytest.mark.asyncio
async def test_page_coroutine_navigation():
    handler = ScrapyPyppeteerDownloadHandler(get_crawler())
    await handler._launch_browser()

    with MockServer() as server:
        req = Request(
            url=server.urljoin("/index.html"),
            meta={
                "pyppeteer": True,
                "pyppeteer_page_coroutines": [NavigationPageCoroutine("click", "a.lorem_ipsum")],
            },
        )
        resp = await handler._download_request(req, Spider("foo"))

    assert isinstance(resp, Response)
    assert resp.request is req
    assert resp.url == server.urljoin("/lorem_ipsum.html")
    assert resp.status == 200
    assert "pyppeteer" in resp.flags
    assert resp.css("title::text").get() == "Lorem Ipsum"
    text = resp.css("p::text").get()
    assert text == "Lorem ipsum dolor sit amet, consectetur adipiscing elit."

    await handler.browser.close()


@pytest.mark.asyncio
async def test_page_coroutine_infinite_scroll():
    handler = ScrapyPyppeteerDownloadHandler(get_crawler())
    await handler._launch_browser()

    with MockServer() as server:
        req = Request(
            url=server.urljoin("/scroll.html"),
            meta={
                "pyppeteer": True,
                "pyppeteer_page_coroutines": [
                    PageCoroutine("waitForSelector", "div.quote"),  # first 10 quotes
                    PageCoroutine("evaluate", "window.scrollBy(0, 2000)"),
                    PageCoroutine("waitForSelector", "div.quote:nth-child(11)"),  # 2nd request
                    PageCoroutine("evaluate", "window.scrollBy(0, 2000)"),
                    PageCoroutine("waitForSelector", "div.quote:nth-child(21)"),  # 3rd request
                ],
            },
        )
        resp = await handler._download_request(req, Spider("foo"))

    assert isinstance(resp, Response)
    assert resp.request is req
    assert resp.url == server.urljoin("/scroll.html")
    assert resp.status == 200
    assert "pyppeteer" in resp.flags
    assert len(resp.css("div.quote")) == 30

    await handler.browser.close()


@pytest.mark.asyncio
async def test_page_coroutine_screenshot_pdf():
    def get_mimetype(file):
        return subprocess.run(
            ["file", "--mime-type", "--brief", file.name],
            stdout=subprocess.PIPE,
            universal_newlines=True,
        ).stdout.strip()

    image_file = NamedTemporaryFile()
    pdf_file = NamedTemporaryFile()
    handler = ScrapyPyppeteerDownloadHandler(get_crawler())
    await handler._launch_browser()

    with MockServer() as server:
        req = Request(
            url=server.urljoin("/index.html"),
            meta={
                "pyppeteer": True,
                "pyppeteer_page_coroutines": [
                    PageCoroutine("screenshot", options={"path": image_file.name, "type": "png"}),
                    PageCoroutine("pdf", options={"path": pdf_file.name}),
                ],
            },
        )
        await handler._download_request(req, Spider("foo"))
        assert get_mimetype(image_file) == "image/png"
        assert get_mimetype(pdf_file) == "application/pdf"
        image_file.close()
        pdf_file.close()

    await handler.browser.close()


@pytest.mark.asyncio
async def test_page_coroutine_timeout():
    crawler = get_crawler(settings_dict={"PYPPETEER_NAVIGATION_TIMEOUT": 1000})
    handler = ScrapyPyppeteerDownloadHandler(crawler)
    await handler._launch_browser()

    with MockServer() as server:
        req = Request(
            url=server.urljoin("/index.html"),
            meta={
                "pyppeteer": True,
                "pyppeteer_page_coroutines": [NavigationPageCoroutine("click", selector="h1")],
            },
        )
        with pytest.raises(pyppeteer.errors.TimeoutError):
            await handler._download_request(req, Spider("foo"))

    await handler.browser.close()


@pytest.mark.asyncio
async def test_page_to_callback():
    handler = ScrapyPyppeteerDownloadHandler(get_crawler())
    await handler._launch_browser()

    async def callback(self, response, page: pyppeteer.page.Page):
        pass

    with MockServer() as server:
        req = Request(server.urljoin("/index.html"), callback, meta={"pyppeteer": True})
        resp = await handler._download_request(req, Spider("foo"))

    page = resp.request.cb_kwargs["page"]
    assert isinstance(page, pyppeteer.page.Page)
    assert (await page.title()) == "Awesome site"

    await page.close()
    await handler.browser.close()
