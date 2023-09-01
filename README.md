![Python Version](https://img.shields.io/badge/python-%3E%3D3.9-green)
# requests_html2
> HTML Parsing for Humans
> 项目衍生自[requests-html](https://github.com/kennethreitz/requests-html)
> 用法参考[expample](example/)

相比于[requests-html](https://github.com/kennethreitz/requests-html)有如下改进：
- async 请求改用[httpx](https://github.com/encode/httpx)
- 浏览器渲染改用[playwright](https://github.com/microsoft/playwright-python)
- 元素操作优化，对于元素查找`find()`、`xpath()`的返回结果，参照linq增加筛选`select()`、`where()`
## Install
```
pip install requests-html2
```
## Quick Start

```python
from requests_html2 import HTMLSession
with HTMLSession() as session:
    response = session.get('https://python.org/')
    print(response.html)
```