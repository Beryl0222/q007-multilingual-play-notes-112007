# 家园多语游戏记录的语言证据与观察安排

青谷养育站的合成分轮听记、时段和沟通授权。姓名只用合成代号，资料只服务于游戏安排。

资料为 UTF-8 JSON。各类原始记录按编号分组，字段约定见 [资料格式](data/资料格式.md)。资料浏览命令会原样输出记录，添加 `--list` 可只查看各类数量。

使用 Python 3.11，命令只依赖标准库。请在项目根目录运行。

```sh
python3 inspect_records.py data/records.json --list
python3 -m unittest discover -s tests -v
```
