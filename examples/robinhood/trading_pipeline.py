"""
Example: Cross-ecosystem trading signal pipeline.
Agents on Virtuals → EVM → Robinhood Chain.
"""
from nive import NiveClient

class TradingPipeline:
    def __init__(self):
        self.rh = NiveClient(ecosystem="robinhood-chain")
        self.evm = NiveClient(ecosystem="evm")
        self.virt = NiveClient(ecosystem="virtuals")

    def run(self, symbol="ETH/USDC"):
        return {
            "sentiment": self.virt.create_task(["SENTIMENT"], 20, {"symbol": symbol}).task_id,
            "analysis": self.evm.create_task(["ANALYSIS"], 30, {"symbol": symbol}).task_id,
            "execution": self.rh.create_task(["TRADE"], 50, {"symbol": symbol}).task_id,
            "ecosystems": ["virtuals", "evm", "robinhood-chain"],
        }

if __name__ == "__main__":
    print(TradingPipeline().run())
