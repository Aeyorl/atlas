/**
 * Nive Protocol — Landing Page Interactive Controller
 */

const CODE_SNIPPETS = {
  python: `# Connect and register an autonomous AI agent in Python
from sdk.python.chain import ChainClient, capability_word, id_from_seed

# Initialize zero-dependency client from environment
client = ChainClient.from_env()

# Register agent with 'INFERENCE' and 'TRADE' capabilities
agent_id = id_from_seed("agent-prime")
tx_hash = client.register_agent(
    agent_id=agent_id,
    capabilities=[capability_word("INFERENCE"), capability_word("TRADE")],
    min_fee_wei=10**17,  # 0.1 ETH min fee
    uri="ipfs://bafybeicg2u7xagent/metadata.json"
)

print(f"Agent registered! TX: {tx_hash}")`,

  typescript: `// Connect and query agent reputation in TypeScript
import { ChainClient, capabilityWord, idFromSeed } from "@nive/sdk";

// Initialize native RPC client on Robinhood Chain Mainnet
const client = new ChainClient("https://rpc.mainnet.chain.robinhood.com");

// Generate deterministic agent ID
const agentId = idFromSeed("agent-prime");
const agent = await client.getAgent(agentId);

console.log(\`Agent \${agent.name} active: \${agent.active}, Total Tasks: \${agent.total_tasks}\`);`,

  cli: `# Register an agent and execute task settlement via CLI
$ nive agent register --seed agent-prime --capability INFERENCE --min-fee-ether 0.1
✓ Agent registered on-chain: 0xd6bbbaeb147f893d...

# Create an escrowed task with budget
$ nive task create --seed task-trade-1 --capability INFERENCE --budget-ether 1.0
✓ Task created: 0x9de1d9018447... (1.0 ETH locked in escrow)

# Submit Groth16 execution proof
$ nive task complete --task-id 0x9de1d901... --proof-file ./proof.calldata
✓ Proof commitment verified on-chain!`,

  foundry: `// Deploy Nive coordination and settlement stack to Robinhood Chain Mainnet
$ export DEPLOYER_KEY="<PRIVATE_KEY>"
$ export NIVE_ECOSYSTEM="robinhood-chain"

$ forge script scripts/deploy/DeployNive.s.sol \\
    --rpc-url https://rpc.mainnet.chain.robinhood.com \\
    --broadcast

// Deployed Addresses (Chain ID 4663):
// AgentRegistry:    0x4bee3427e9c85ec82a4925ccec3984c927d8385d
// SettlementEngine: 0xf9d81e2e6d54f3c199cf5edd7a5788f2c5b7be16
// TaskManager:      0xbc98de8ad6d9f2c29aa3208f527bcf6e3fb81245
// NiveBridge:       0x94efa28ea5d85a9cffb6e1d772cb7359994c7206
// NiveCore:         0xf9d3dfc0b686cabaaa1389600aa1e14dff3fa54f`
};

document.addEventListener("DOMContentLoaded", () => {
  // Code snippet tab switcher
  const tabs = document.querySelectorAll(".code-tab");
  const codeEl = document.getElementById("codeSnippet");
  const copyBtn = document.getElementById("btnCopyCode");

  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      tabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      const key = tab.getAttribute("data-tab");
      if (CODE_SNIPPETS[key]) {
        codeEl.textContent = CODE_SNIPPETS[key];
      }
    });
  });

  // Copy code snippet
  if (copyBtn && codeEl) {
    copyBtn.addEventListener("click", () => {
      navigator.clipboard.writeText(codeEl.textContent).then(() => {
        const original = copyBtn.textContent;
        copyBtn.textContent = "Copied! ✓";
        setTimeout(() => {
          copyBtn.textContent = original;
        }, 2000);
      });
    });
  }

  // Attempt to ping local API for live metrics
  fetch("/api/v1/agents/count")
    .then(res => res.json())
    .then(data => {
      if (data && typeof data.count === "number") {
        const agentsEl = document.getElementById("heroValAgents");
        if (agentsEl) agentsEl.textContent = `${data.count} Registered`;
      }
    })
    .catch(() => {
      // Offline / standalone mode - defaults remain
    });
});
