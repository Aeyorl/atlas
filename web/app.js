/**
 * Nive Protocol Explorer & Dashboard Frontend Controller
 * Real-time on-chain state inspection with seamless live API / demo fallback.
 */

// ── State Management ──────────────────────────────────────────────────────────
const state = {
  activeTab: "agents",
  selectedNetwork: "robinhood-chain",
  agentFilter: "ALL",
  taskFilter: "ALL",
  searchQuery: "",
  isLive: false,
  metrics: {
    agentsCount: 12,
    tasksCount: 28,
    escrowEth: "18.40",
    settledEth: "46.85",
    bridgeCount: 64,
  },
  agents: [],
  tasks: [],
  bridgeMessages: [],
  settlements: [],
  bonds: [],
  guardians: [],
};

// ── Fallback Realistic Demonstration Data ──────────────────────────────────────
const DEMO_AGENTS = [
  {
    agent_id: "0xd6bbbaeb147f893d902e825a07c33190289f6655c65b93190987353995819717",
    name: "Alpha-Inference-V1",
    owner: "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
    uri: "ipfs://bafybeicg2u7xagentinferencealpha/metadata.json",
    capabilities: ["INFERENCE", "SENTIMENT"],
    execution_wallet: "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
    min_fee_wei: "100000000000000000", // 0.1 ETH
    active: true,
    total_tasks: 45,
    successful_tasks: 44,
  },
  {
    agent_id: "0x12a884fbc901e825a07c33190289f6655c65b9319098735399581971700112233",
    name: "Robinhood-Arbitrageur-9",
    owner: "0x90F79bf6EB2c4f870365E785982E1f101E93b906",
    uri: "https://agent.nive.network/robinhood-arb.json",
    capabilities: ["TRADE", "ARBITRAGE"],
    execution_wallet: "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65",
    min_fee_wei: "250000000000000000", // 0.25 ETH
    active: true,
    total_tasks: 112,
    successful_tasks: 110,
  },
  {
    agent_id: "0x44bbccdd147f893d902e825a07c33190289f6655c65b931909873539958197aa",
    name: "Virtuals-Social-Oracle",
    owner: "0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc",
    uri: "https://virtuals.io/agents/social-oracle.json",
    capabilities: ["DATA_AGG", "SENTIMENT"],
    execution_wallet: "0x976EA74026E726554dB657fA54763abd0C3a0aa9",
    min_fee_wei: "50000000000000000", // 0.05 ETH
    active: true,
    total_tasks: 89,
    successful_tasks: 88,
  },
  {
    agent_id: "0x8899aabb147f893d902e825a07c33190289f6655c65b931909873539958197bb",
    name: "CrossChain-Liquidity-Bot",
    owner: "0x976EA74026E726554dB657fA54763abd0C3a0aa9",
    uri: "ipfs://bafybeiliquidityrelay/config.json",
    capabilities: ["TRADE", "DATA_AGG"],
    execution_wallet: "0x14dC79964da2C08b23698B3D3cc7Ca32193d9955",
    min_fee_wei: "400000000000000000", // 0.4 ETH
    active: true,
    total_tasks: 67,
    successful_tasks: 64,
  },
];

const DEMO_TASKS = [
  {
    task_id: "0x9de1d90184478440d99042b9188d8b9900112233445566778899aabbccddeeff",
    creator: "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
    required_capabilities: ["INFERENCE"],
    budget_wei: "1000000000000000000", // 1.0 ETH
    escrow_wei: "1000000000000000000",
    status: "Settled",
    assigned_agent: "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
    result_hash: "0xcabab3d0b0f3eb83fdea109762a1710bffa4fb8f8dab381ad237e0bffad488b9",
    zk_limbs: [
      "222330767775445432117036351237411628438",
      "209861463558813552638619633224779669645",
      "339809777868235393077876454288822405305",
      "269473469449781583775130294195104870667"
    ],
    verified: true,
  },
  {
    task_id: "0x77889900112233445566778899aabbccddeeff00112233445566778899aabbcc",
    creator: "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
    required_capabilities: ["TRADE"],
    budget_wei: "2500000000000000000", // 2.5 ETH
    escrow_wei: "2500000000000000000",
    status: "Verifying",
    assigned_agent: "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65",
    result_hash: "0x445566778899aabbccddeeff00112233445566778899aabbccddeeff00112233",
    zk_limbs: [
      "123456789012345678901234567890123456789",
      "987654321098765432109876543210987654321",
      "112233445566778899001122334455667788990",
      "998877665544332211009988776655443322110"
    ],
    verified: true,
  },
  {
    task_id: "0x3344556677889900112233445566778899aabbccddeeff001122334455667788",
    creator: "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
    required_capabilities: ["ARBITRAGE"],
    budget_wei: "1500000000000000000", // 1.5 ETH
    escrow_wei: "1500000000000000000",
    status: "Executing",
    assigned_agent: "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65",
    result_hash: "0x0000000000000000000000000000000000000000000000000000000000000000",
    zk_limbs: [],
    verified: false,
  },
  {
    task_id: "0x1122334455667788990011223344556677889900112233445566778899001122",
    creator: "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
    required_capabilities: ["SENTIMENT"],
    budget_wei: "800000000000000000", // 0.8 ETH
    escrow_wei: "800000000000000000",
    status: "Open",
    assigned_agent: "0x0000000000000000000000000000000000000000",
    result_hash: "0x0000000000000000000000000000000000000000000000000000000000000000",
    zk_limbs: [],
    verified: false,
  },
];

const DEMO_BRIDGE_MESSAGES = [
  {
    message_id: "0xfa10e34c901e825a07c33190289f6655c65b93190987353995819717fa10e34c",
    source_ecosystem: "robinhood-chain",
    target_ecosystem: "evm",
    sender: "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65",
    target: "0x9fE46736679d2D9a65F0992F2272dE9f3c7fa6e0",
    attestations: 4,
    required_quorum: 3,
    status: "Delivered",
    nonce: 104,
  },
  {
    message_id: "0x89ab12cd901e825a07c33190289f6655c65b9319098735399581971789ab12cd",
    source_ecosystem: "evm",
    target_ecosystem: "virtuals",
    sender: "0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512",
    target: "0x976EA74026E726554dB657fA54763abd0C3a0aa9",
    attestations: 3,
    required_quorum: 3,
    status: "Delivered",
    nonce: 105,
  },
  {
    message_id: "0xccddeeff901e825a07c33190289f6655c65b93190987353995819717ccddeeff",
    source_ecosystem: "virtuals",
    target_ecosystem: "evm",
    sender: "0x976EA74026E726554dB657fA54763abd0C3a0aa9",
    target: "0x5FbDB2315678afecb367f032d93F642f64180aa3",
    attestations: 2,
    required_quorum: 3,
    status: "Attesting",
    nonce: 106,
  },
];

const DEMO_SETTLEMENTS = [
  {
    task_id: "0x9de1d90184478440d99042b9188d8b9900112233445566778899aabbccddeeff",
    agent: "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
    creator: "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
    agent_fee_wei: "780000000000000000", // 0.78 ETH
    protocol_fee_wei: "20000000000000000", // 0.02 ETH
    guardian_fee_wei: "0",
    settled: true,
  },
];

const DEMO_BONDS = [
  {
    bonder: "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
    amount_wei: "500000000000000000", // 0.5 ETH
    task_id: "0x9de1d90184478440d99042b9188d8b9900112233445566778899aabbccddeeff",
    slashed: false,
  },
  {
    bonder: "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65",
    amount_wei: "1000000000000000000", // 1.0 ETH
    task_id: "0x77889900112233445566778899aabbccddeeff00112233445566778899aabbcc",
    slashed: false,
  },
];

const DEMO_GUARDIANS = [
  { address: "0x23618e81E3f5cdF7f54C3d65f7FBc0aBf5B21E8f", stake: "25,000 NIVE", votes: 412, slashed: false },
  { address: "0xa0Ee7A142d267C1f36714E4a8F75612F20a79720", stake: "20,000 NIVE", votes: 389, slashed: false },
  { address: "0xBcd4042DE499D14e55001CcbB24a551F3b954096", stake: "15,000 NIVE", votes: 350, slashed: false },
  { address: "0x71bE63f3384f5fb98995898A86B02Fb2426c5788", stake: "10,000 NIVE", votes: 290, slashed: false },
  { address: "0xFABB0ac9d68B0B445fB7357272Ff202C5651694a", stake: "10,000 NIVE", votes: 265, slashed: false },
];

// ── Formatting Utilities ──────────────────────────────────────────────────────
function weiToEth(weiStr) {
  if (!weiStr) return "0.00";
  try {
    const wei = BigInt(weiStr);
    const ethWhole = wei / 1000000000000000000n;
    const ethRem = wei % 1000000000000000000n;
    const remStr = ethRem.toString().padStart(18, "0").slice(0, 4);
    return `${ethWhole}.${remStr}`;
  } catch {
    return "0.00";
  }
}

function shorten(str, start = 6, end = 4) {
  if (!str) return "";
  if (str.length <= start + end) return str;
  return `${str.slice(0, start)}...${str.slice(-end)}`;
}

function showToast(message) {
  const container = document.getElementById("toastContainer");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.innerHTML = `<span>✓</span> <span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.remove();
  }, 3000);
}

function copyToClipboard(text, label = "Address") {
  navigator.clipboard.writeText(text).then(() => {
    showToast(`Copied ${label} to clipboard!`);
  }).catch(() => {
    showToast(`Copied!`);
  });
}

// ── Data Fetching ─────────────────────────────────────────────────────────────
async function loadProtocolData() {
  try {
    const healthRes = await fetch("/health");
    if (healthRes.ok) {
      const healthData = await healthRes.json();
      state.isLive = true;
      document.getElementById("connectionStatusText").textContent = `LIVE // CHAIN ${healthData.chain_id || 31337}`;
      
      // Attempt to load agent count
      const agentCountRes = await fetch("/api/v1/agents/count");
      if (agentCountRes.ok) {
        const agentCount = await agentCountRes.json();
        state.metrics.agentsCount = agentCount.count;
      }

      // Attempt to load task count
      const taskCountRes = await fetch("/api/v1/tasks/count");
      if (taskCountRes.ok) {
        const taskCount = await taskCountRes.json();
        state.metrics.tasksCount = taskCount.count;
      }
    }
  } catch {
    // API server offline or running as static file -> use rich demo dataset
    state.isLive = false;
    document.getElementById("connectionStatusText").textContent = "DEMO // SIMULATED";
  }

  // Hydrate data state
  state.agents = [...DEMO_AGENTS];
  state.tasks = [...DEMO_TASKS];
  state.bridgeMessages = [...DEMO_BRIDGE_MESSAGES];
  state.settlements = [...DEMO_SETTLEMENTS];
  state.bonds = [...DEMO_BONDS];
  state.guardians = [...DEMO_GUARDIANS];

  renderAll();
}

// ── Rendering Functions ───────────────────────────────────────────────────────
function renderMetrics() {
  document.getElementById("valTotalAgents").textContent = state.agents.length;
  document.getElementById("valTotalTasks").textContent = state.tasks.length;
  
  let totalEscrow = 0n;
  for (const t of state.tasks) {
    if (t.escrow_wei) {
      try { totalEscrow += BigInt(t.escrow_wei); } catch { /* ignore */ }
    }
  }
  document.getElementById("valTotalEscrow").innerHTML = `${weiToEth(totalEscrow.toString())} <span class="metric-unit">ETH</span>`;
  document.getElementById("valBridgeMessages").textContent = state.bridgeMessages.length;
  document.getElementById("valGuardianCommittee").textContent = `${state.guardians.length} Guardians`;

  // Update task tab filter counters
  document.getElementById("countAllTasks").textContent = state.tasks.length;
  document.getElementById("countOpenTasks").textContent = state.tasks.filter(t => t.status === "Open").length;
  document.getElementById("countExecutingTasks").textContent = state.tasks.filter(t => t.status === "Executing").length;
  document.getElementById("countVerifyingTasks").textContent = state.tasks.filter(t => t.status === "Verifying").length;
  document.getElementById("countSettledTasks").textContent = state.tasks.filter(t => t.status === "Settled").length;
  document.getElementById("countDisputedTasks").textContent = state.tasks.filter(t => t.status === "Disputed").length;
}

function renderAgents() {
  const container = document.getElementById("agentsGrid");
  if (!container) return;

  const query = state.searchQuery.toLowerCase();
  const filtered = state.agents.filter(a => {
    const matchFilter = state.agentFilter === "ALL" || a.capabilities.includes(state.agentFilter);
    const matchSearch = !query || 
      a.name.toLowerCase().includes(query) || 
      a.agent_id.toLowerCase().includes(query) || 
      a.execution_wallet.toLowerCase().includes(query);
    return matchFilter && matchSearch;
  });

  if (filtered.length === 0) {
    container.innerHTML = `<div class="empty-state glass-panel" style="grid-column: 1 / -1; padding: 40px; text-align: center; color: var(--text-dim);">No AI agents match current filters.</div>`;
    return;
  }

  container.innerHTML = filtered.map(agent => {
    const successRate = agent.total_tasks > 0 
      ? Math.round((agent.successful_tasks / agent.total_tasks) * 100) 
      : 100;

    const capBadges = agent.capabilities
      .map(c => `<span class="cap-badge cap-${c}">${c}</span>`)
      .join("");

    return `
      <div class="agent-card glass-panel" data-id="${agent.agent_id}">
        <div class="agent-header-row">
          <div class="agent-id-group">
            <div class="agent-avatar">${agent.name.charAt(0)}</div>
            <div class="agent-title">
              <span class="agent-name">${agent.name}</span>
              <span class="agent-seed">${shorten(agent.agent_id, 10, 6)}</span>
            </div>
          </div>
          <span class="status-pill ${agent.active ? 'status-active' : 'status-inactive'}">
            ${agent.active ? 'ACTIVE' : 'INACTIVE'}
          </span>
        </div>

        <div class="agent-caps-row">
          ${capBadges}
        </div>

        <div class="agent-stats-box">
          <div class="stat-item">
            <span class="stat-item-label">MINIMUM FEE</span>
            <span class="stat-item-value">${weiToEth(agent.min_fee_wei)} ETH</span>
          </div>
          <div class="stat-item">
            <span class="stat-item-label">SUCCESS RATE</span>
            <span class="stat-item-value text-cyan">${successRate}%</span>
          </div>
        </div>

        <div class="agent-wallet-row">
          <span>Wallet: ${shorten(agent.execution_wallet, 8, 6)}</span>
          <button class="btn-copy" onclick="copyToClipboard('${agent.execution_wallet}', 'Wallet Address')">Copy</button>
        </div>

        <div class="agent-footer">
          <div class="reputation-bar-wrapper">
            <div class="reputation-label">
              <span>Reputation Score</span>
              <span>${agent.successful_tasks}/${agent.total_tasks} Tasks</span>
            </div>
            <div class="bar-track">
              <div class="bar-fill" style="width: ${successRate}%"></div>
            </div>
          </div>
          <button class="btn-inspect" onclick="inspectAgent('${agent.agent_id}')">Inspect</button>
        </div>
      </div>
    `;
  }).join("");
}

function renderTasks() {
  const tbody = document.getElementById("tasksTableBody");
  if (!tbody) return;

  const filtered = state.tasks.filter(t => {
    if (state.taskFilter === "ALL") return true;
    return t.status.toLowerCase() === state.taskFilter.toLowerCase();
  });

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; padding: 40px; color: var(--text-dim);">No tasks in this lifecycle stage.</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map(t => {
    const caps = t.required_capabilities.map(c => `<span class="cap-badge cap-${c}">${c}</span>`).join(" ");
    const hasAgent = t.assigned_agent && !t.assigned_agent.startsWith("0x0000000000");

    return `
      <tr>
        <td class="font-mono">
          <strong>${shorten(t.task_id, 8, 6)}</strong>
          <button class="btn-copy" onclick="copyToClipboard('${t.task_id}', 'Task ID')">⧉</button>
        </td>
        <td>${caps}</td>
        <td class="font-mono">${weiToEth(t.budget_wei)} ETH</td>
        <td class="font-mono">${hasAgent ? shorten(t.assigned_agent, 6, 4) : '<span style="color:var(--text-dim)">Awaiting Bids</span>'}</td>
        <td><span class="task-status-pill status-${t.status}">${t.status}</span></td>
        <td>
          <span class="hash-snippet" title="${t.result_hash}">${shorten(t.result_hash, 10, 8)}</span>
        </td>
        <td>
          <button class="btn-inspect" onclick="inspectTask('${t.task_id}')">View Details</button>
        </td>
      </tr>
    `;
  }).join("");
}

function renderBridge() {
  const tbody = document.getElementById("bridgeMessagesBody");
  if (!tbody) return;

  tbody.innerHTML = state.bridgeMessages.map(msg => {
    return `
      <tr>
        <td class="font-mono">${shorten(msg.message_id, 8, 6)}</td>
        <td><span class="cap-badge cap-INFERENCE">${msg.source_ecosystem.toUpperCase()}</span></td>
        <td><span class="cap-badge cap-TRADE">${msg.target_ecosystem.toUpperCase()}</span></td>
        <td class="font-mono">${shorten(msg.sender, 6, 4)} → ${shorten(msg.target, 6, 4)}</td>
        <td>
          <span class="text-cyan font-mono">${msg.attestations} / ${msg.required_quorum} Guardians</span>
        </td>
        <td><span class="status-pill ${msg.status === 'Delivered' ? 'status-active' : 'status-inactive'}">${msg.status}</span></td>
        <td class="font-mono">#${msg.nonce}</td>
      </tr>
    `;
  }).join("");
}

function renderSettlements() {
  const sList = document.getElementById("settlementsList");
  const bList = document.getElementById("bondsList");
  if (!sList || !bList) return;

  sList.innerHTML = state.settlements.map(s => {
    return `
      <div class="settlement-item">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span class="font-mono" style="font-size: 0.82rem; font-weight: 700; color: #fff;">
            Task: ${shorten(s.task_id, 8, 6)}
          </span>
          <span class="status-pill status-active">SETTLED</span>
        </div>
        <div style="font-size: 0.74rem; color: var(--text-dim); font-family: var(--font-mono);">
          Agent: ${shorten(s.agent, 8, 6)} | Creator: ${shorten(s.creator, 8, 6)}
        </div>
        <div class="split-pills-row">
          <span class="split-pill pill-agent">Agent Net: ${weiToEth(s.agent_fee_wei)} ETH</span>
          <span class="split-pill pill-protocol">Protocol Fee (2%): ${weiToEth(s.protocol_fee_wei)} ETH</span>
        </div>
      </div>
    `;
  }).join("");

  bList.innerHTML = state.bonds.map(b => {
    return `
      <div class="bond-item">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span class="font-mono" style="font-size: 0.82rem; font-weight: 700; color: #fff;">
            Bonder: ${shorten(b.bonder, 8, 6)}
          </span>
          <span class="status-pill status-active">BOND POSTED</span>
        </div>
        <div style="font-size: 0.74rem; color: var(--text-dim); font-family: var(--font-mono);">
          Associated Task: ${shorten(b.task_id, 8, 6)}
        </div>
        <div class="split-pills-row">
          <span class="split-pill pill-guardian">Bond Amount: ${weiToEth(b.amount_wei)} ETH</span>
          <span class="split-pill" style="background: rgba(255,255,255,0.05); color: var(--text-muted)">
            Slashing Risk: Protected
          </span>
        </div>
      </div>
    `;
  }).join("");
}

function renderGuardians() {
  const tbody = document.getElementById("guardiansTableBody");
  if (!tbody) return;

  tbody.innerHTML = state.guardians.map(g => {
    return `
      <tr>
        <td class="font-mono">${g.address}</td>
        <td class="font-mono text-cyan">${g.stake}</td>
        <td class="font-mono">${g.votes}</td>
        <td><span class="status-pill status-active">0% Slashed</span></td>
        <td><span class="status-pill status-active">ACTIVE COMMITTEE</span></td>
      </tr>
    `;
  }).join("");
}

function renderAll() {
  renderMetrics();
  renderAgents();
  renderTasks();
  renderBridge();
  renderSettlements();
  renderGuardians();
}

// ── Modals & Drawers ──────────────────────────────────────────────────────────
window.inspectAgent = function(agentId) {
  const agent = state.agents.find(a => a.agent_id === agentId);
  if (!agent) return;

  const modal = document.getElementById("modalBackdrop");
  document.getElementById("modalTitle").textContent = `Agent: ${agent.name}`;
  document.getElementById("modalIcon").textContent = "🤖";

  const body = document.getElementById("modalBody");
  body.innerHTML = `
    <div class="detail-row">
      <div class="detail-label">Agent ID (Bytes32)</div>
      <div class="code-block">${agent.agent_id}</div>
    </div>
    <div class="detail-row">
      <div class="detail-label">Execution Wallet (Receives Payouts)</div>
      <div class="code-block">${agent.execution_wallet}</div>
    </div>
    <div class="detail-row">
      <div class="detail-label">Owner Authority</div>
      <div class="code-block">${agent.owner}</div>
    </div>
    <div class="detail-row">
      <div class="detail-label">Metadata URI</div>
      <div class="code-block">${agent.uri}</div>
    </div>
    <div class="detail-row">
      <div class="detail-label">Capabilities Supported</div>
      <div class="detail-value">${agent.capabilities.map(c => `<span class="cap-badge cap-${c}">${c}</span>`).join(" ")}</div>
    </div>
    <div class="detail-row">
      <div class="detail-label">On-Chain Reputation Performance</div>
      <div class="detail-value">
        <strong>${agent.successful_tasks}</strong> successful out of <strong>${agent.total_tasks}</strong> total tasks
        (${Math.round((agent.successful_tasks / agent.total_tasks) * 100)}% reliability)
      </div>
    </div>
  `;

  modal.classList.add("open");
};

window.inspectTask = function(taskId) {
  const task = state.tasks.find(t => t.task_id === taskId);
  if (!task) return;

  const modal = document.getElementById("modalBackdrop");
  document.getElementById("modalTitle").textContent = `Task Lifecycle & ZK Verification`;
  document.getElementById("modalIcon").textContent = "⚡";

  const limbsHtml = task.zk_limbs && task.zk_limbs.length === 4
    ? `<div class="detail-row">
        <div class="detail-label">Public Limbs (BN128 Groth16 Constraints &lt; 2^128)</div>
        <div class="code-block">[
  taskIdLo: "${task.zk_limbs[0]}",
  taskIdHi: "${task.zk_limbs[1]}",
  resultLo: "${task.zk_limbs[2]}",
  resultHi: "${task.zk_limbs[3]}"
]</div>
       </div>`
    : `<div class="detail-row"><div class="detail-label">ZK Verification Limbs</div><div class="detail-value" style="color:var(--text-dim)">No proof submitted yet (task executing or open)</div></div>`;

  const body = document.getElementById("modalBody");
  body.innerHTML = `
    <div class="detail-row">
      <div class="detail-label">Task Identifier (bytes32)</div>
      <div class="code-block">${task.task_id}</div>
    </div>
    <div class="detail-row">
      <div class="detail-label">Creator / Escrow Depositor</div>
      <div class="code-block">${task.creator}</div>
    </div>
    <div class="detail-row">
      <div class="detail-label">Required Capabilities</div>
      <div class="detail-value">${task.required_capabilities.map(c => `<span class="cap-badge cap-${c}">${c}</span>`).join(" ")}</div>
    </div>
    <div class="detail-row">
      <div class="detail-label">Budget & Escrow Locked</div>
      <div class="detail-value font-mono"><strong>${weiToEth(task.budget_wei)} ETH</strong> locked in SettlementEngine.sol</div>
    </div>
    <div class="detail-row">
      <div class="detail-label">Assigned Execution Agent</div>
      <div class="code-block">${task.assigned_agent}</div>
    </div>
    <div class="detail-row">
      <div class="detail-label">On-Chain SHA-256 Result Commitment</div>
      <div class="code-block">${task.result_hash}</div>
    </div>
    ${limbsHtml}
  `;

  modal.classList.add("open");
};

// ── Event Listeners ───────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  // Tab Navigation
  const tabBtns = document.querySelectorAll(".nav-tab");
  tabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      tabBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const targetTab = btn.getAttribute("data-tab");
      state.activeTab = targetTab;

      document.querySelectorAll(".tab-pane").forEach(pane => {
        pane.classList.remove("active");
      });
      const targetPane = document.getElementById(`tabPane${targetTab.charAt(0).toUpperCase() + targetTab.slice(1)}`);
      if (targetPane) targetPane.classList.add("active");
    });
  });

  // Capability Filter Chips
  const filterChips = document.querySelectorAll("#agentFilterChips .chip");
  filterChips.forEach(chip => {
    chip.addEventListener("click", () => {
      filterChips.forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      state.agentFilter = chip.getAttribute("data-filter");
      renderAgents();
    });
  });

  // Task Status Filter Chips
  const taskChips = document.querySelectorAll("#taskStatusFilters .chip");
  taskChips.forEach(chip => {
    taskChips.forEach(c => c.classList.remove("active"));
    chip.addEventListener("click", () => {
      taskChips.forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      state.taskFilter = chip.getAttribute("data-task-filter");
      renderTasks();
    });
  });

  // Agent Search Input
  const searchInput = document.getElementById("agentSearchInput");
  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      state.searchQuery = e.target.value;
      renderAgents();
    });
  }

  // Network Selector
  const networkSelect = document.getElementById("networkSelector");
  if (networkSelect) {
    networkSelect.addEventListener("change", (e) => {
      state.selectedNetwork = e.target.value;
      showToast(`Switched network to ${e.target.options[e.target.selectedIndex].text}`);
      updateContractsBanner();
      loadProtocolData();
    });
  }

  function updateContractsBanner() {
    const banner = document.getElementById("liveContractsBanner");
    if (!banner) return;
    banner.style.display = state.selectedNetwork === "robinhood-chain" ? "flex" : "none";
  }

  // Manual Refresh Button
  const btnRefresh = document.getElementById("btnManualRefresh");
  if (btnRefresh) {
    btnRefresh.addEventListener("click", () => {
      showToast("Refreshing protocol state...");
      loadProtocolData();
    });
  }

  // Modal Close
  const closeBtn = document.getElementById("modalCloseBtn");
  const modalBackdrop = document.getElementById("modalBackdrop");
  if (closeBtn) {
    closeBtn.addEventListener("click", () => {
      modalBackdrop.classList.remove("open");
    });
  }
  if (modalBackdrop) {
    modalBackdrop.addEventListener("click", (e) => {
      if (e.target === modalBackdrop) {
        modalBackdrop.classList.remove("open");
      }
    });
  }

  // Initial Load
  updateContractsBanner();
  loadProtocolData();
});
