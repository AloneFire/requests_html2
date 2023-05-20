# requests_html2
> HTML Parsing for Humans
> 项目衍生自[requests-html](https://github.com/kennethreitz/requests-html)
> 用法请参考`example`以及[requests-html](https://github.com/kennethreitz/requests-html)文档

相比于[requests-html](https://github.com/kennethreitz/requests-html)有如下改进：
- 浏览器渲染相关操作更灵活
- 增加全局cookie、proxy设置
- 元素操作优化，对于元素查找`find()`、`xpath()`的返回结果，参照linq增加筛选`select()`、`where()`
## Install
```
pip install requests-html2
```
## Quick Start

```python
from requests_html2 import HTMLSession
session = HTMLSession()
r = session.get('https://python.org/')
```