# 本地运行与版本验证

## 1) 安装依赖
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2) 验证代码版本
```bash
python main.py --version
```

## 3) 启动应用
```bash
python main.py
```

## 4) 可选调试模式
```bash
SATIMG_DEBUG=1 python main.py
```
