# requests_html2
> HTML Parsing for Humans
> 项目衍生自[requests-html](https://github.com/kennethreitz/requests-html)
> 用法请参考`example`以及requests-html文档

## Quick Start

```python
from requests_html2 import HTMLSession
session = HTMLSession()
r = session.get('https://python.org/')
```