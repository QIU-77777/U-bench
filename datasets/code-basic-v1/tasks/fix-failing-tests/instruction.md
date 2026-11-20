/workspace 下有一个小型 Python 包 `cart`（购物车与价格工具），单元测试在 `/workspace/tests/test_cart.py`。当前有测试失败，原因是包的源码里存在 bug。

请修复 `cart` 包的源码，使测试全部通过，并保证各函数的行为与其文档字符串一致。不要修改 `tests/` 目录下的现有测试。

运行测试的命令：

```
cd /workspace && python -m pytest tests -q
```
