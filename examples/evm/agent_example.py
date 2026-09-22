"""Example: EVM agent registration."""
from nive import NiveClient

print(NiveClient(ecosystem="evm").create_task(["ANALYSIS"], 10, {"chain": "base"}).task_id)
