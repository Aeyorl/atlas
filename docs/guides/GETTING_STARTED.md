# Nive Developer Guide

```bash
pip install nive-sdk
```

```python
from nive import NiveClient
client = NiveClient(ecosystem="robinhood-chain")
task = client.create_task(["ANALYZE"], 100, {"symbol": "ETH/USDC"})
print(f"Task: {task.task_id}")
```
