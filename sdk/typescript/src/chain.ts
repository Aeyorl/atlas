/**
 * Contract-backed ChainClient for Nive Protocol in TypeScript.
 * Works across Node.js, browsers, and Edge runtimes via native fetch.
 */
import {
  capabilityWord,
  idFromSeed,
  keccak256,
} from "./crypto.ts";
import type {
  AgentRecord,
  BidRecord,
  ContractsConfig,
  SettlementRecord,
  TaskRecord,
  TaskStatus,
} from "./types.ts";

const TASK_STATUSES: Record<number, TaskStatus> = {
  0: "Pending",
  1: "Bidding",
  2: "Executing",
  3: "Verifying",
  4: "Completed",
  5: "Failed",
  6: "Disputed",
};

export class ChainClient {
  public readonly rpcUrl: string;
  public readonly contracts: ContractsConfig;
  public readonly signerAddress?: string;
  private readonly sendTransactionHandler?: (tx: {
    to: string;
    data: string;
    value?: bigint;
    gas?: bigint;
  }) => Promise<string>;

  constructor(options: {
    rpcUrl: string;
    contracts: ContractsConfig;
    signerAddress?: string;
    sendTransaction?: (tx: {
      to: string;
      data: string;
      value?: bigint;
      gas?: bigint;
    }) => Promise<string>;
  }) {
    this.rpcUrl = options.rpcUrl;
    this.contracts = options.contracts;
    this.signerAddress = options.signerAddress;
    this.sendTransactionHandler = options.sendTransaction;
  }

  // ── JSON-RPC Transport ──────────────────────────────────────────

  public async rpcCall<T = any>(method: string, params: any[]): Promise<T> {
    const res = await fetch(this.rpcUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: Date.now(),
        method,
        params,
      }),
    });
    if (!res.ok) {
      throw new Error(`RPC HTTP error ${res.status}: ${res.statusText}`);
    }
    const data = (await res.json()) as any;
    if (data.error) {
      throw new Error(`RPC error ${data.error.code}: ${data.error.message}`);
    }
    return data.result as T;
  }

  public async ethCall(to: string, data: string): Promise<string> {
    return this.rpcCall<string>("eth_call", [{ to, data }, "latest"]);
  }

  public async chainId(): Promise<number> {
    const hex = await this.rpcCall<string>("eth_chainId", []);
    return Number.parseInt(hex, 16);
  }

  private selector(signature: string): string {
    return keccak256(signature).slice(0, 10);
  }

  private padWord(val: string | bigint | number | boolean): string {
    if (typeof val === "boolean") {
      return (val ? 1n : 0n).toString(16).padStart(64, "0");
    }
    if (typeof val === "bigint" || typeof val === "number") {
      return BigInt(val).toString(16).padStart(64, "0");
    }
    if (val.startsWith("0x")) {
      return val.slice(2).padStart(64, "0");
    }
    return val.padStart(64, "0");
  }

  // ── AgentRegistry ───────────────────────────────────────────────

  public async getAgent(agentId: string): Promise<AgentRecord> {
    const data = this.selector("getAgent(bytes32)") + this.padWord(agentId);
    const raw = await this.ethCall(this.contracts.registry, data);
    const clean = raw.replace(/^0x/, "");
    // Stripping potential 0x20 struct wrapper
    const slice = clean.length > 64 * 7 ? clean.slice(64) : clean;

    const words = [];
    for (let i = 0; i < slice.length; i += 64) {
      words.push(slice.slice(i, i + 64));
    }

    const agentHex = "0x" + words[0];
    const owner = "0x" + words[1].slice(24);
    const execWallet = "0x" + words[2].slice(24);
    const minFee = BigInt("0x" + words[3]);
    const active = BigInt("0x" + words[4]) === 1n;
    const totalTasks = Number(BigInt("0x" + words[5]));
    const successfulTasks = Number(BigInt("0x" + words[6]));

    return {
      agentId: agentHex,
      owner,
      uri: "",
      capabilities: [],
      executionWallet: execWallet,
      minFeeWei: minFee,
      active,
      totalTasks,
      successfulTasks,
    };
  }

  public async getAgentCount(): Promise<number> {
    const data = this.selector("getAgentCount()");
    const raw = await this.ethCall(this.contracts.registry, data);
    return Number(BigInt(raw));
  }

  public async isAgentActive(agentId: string): Promise<boolean> {
    const data = this.selector("isActive(bytes32)") + this.padWord(agentId);
    const raw = await this.ethCall(this.contracts.registry, data);
    return BigInt(raw) === 1n;
  }

  // ── TaskManager ─────────────────────────────────────────────────

  public async getTask(taskId: string): Promise<TaskRecord> {
    const data = this.selector("getTask(bytes32)") + this.padWord(taskId);
    const raw = await this.ethCall(this.contracts.taskManager, data);
    const clean = raw.replace(/^0x/, "");
    const slice = clean.length > 64 * 7 ? clean.slice(64) : clean;

    const words = [];
    for (let i = 0; i < slice.length; i += 64) {
      words.push(slice.slice(i, i + 64));
    }

    const taskHex = "0x" + words[0];
    const creator = "0x" + words[1].slice(24);
    const budgetWei = BigInt("0x" + words[2]);
    const statusNum = Number(BigInt("0x" + words[3]));
    const assignedAgent = "0x" + words[4].slice(24);
    const createdAt = Number(BigInt("0x" + words[5]));
    const deadline = Number(BigInt("0x" + words[6]));

    return {
      taskId: taskHex,
      creator,
      requiredCapabilities: [],
      budgetWei,
      parameters: "",
      status: TASK_STATUSES[statusNum] || "Pending",
      assignedAgent,
      createdAt,
      deadline,
    };
  }

  public async getTaskCount(): Promise<number> {
    const data = this.selector("getTaskCount()");
    const raw = await this.ethCall(this.contracts.taskManager, data);
    return Number(BigInt(raw));
  }

  public async getResultHash(taskId: string): Promise<string> {
    const data = this.selector("getResultHash(bytes32)") + this.padWord(taskId);
    return this.ethCall(this.contracts.taskManager, data);
  }

  public async protocolFeeBps(): Promise<number> {
    const data = this.selector("protocolFeeBps()");
    const raw = await this.ethCall(this.contracts.taskManager, data);
    return Number(BigInt(raw));
  }

  // ── SettlementEngine ────────────────────────────────────────────

  public async getEscrow(taskId: string): Promise<bigint> {
    const data = this.selector("getEscrow(bytes32)") + this.padWord(taskId);
    const raw = await this.ethCall(this.contracts.settlement, data);
    return BigInt(raw);
  }

  public async getSettlement(taskId: string): Promise<SettlementRecord> {
    const data = this.selector("getSettlement(bytes32)") + this.padWord(taskId);
    const raw = await this.ethCall(this.contracts.settlement, data);
    let clean = raw.replace(/^0x/, "");
    if (clean.length >= 64 * 8 && clean.startsWith("0000000000000000000000000000000000000000000000000000000000000020")) {
      clean = clean.slice(64);
    }
    const words = [];
    for (let i = 0; i < clean.length; i += 64) {
      words.push(clean.slice(i, i + 64));
    }
    return {
      taskId: "0x" + words[0],
      agent: "0x" + words[1].slice(24),
      creator: "0x" + words[2].slice(24),
      agentFeeWei: BigInt("0x" + words[3]),
      guardianFeeWei: BigInt("0x" + words[4]),
      protocolFeeWei: BigInt("0x" + words[5]),
      settled: BigInt("0x" + words[6]) === 1n,
    };
  }

  public async getBond(taskId: string, bonder: string): Promise<bigint> {
    const data =
      this.selector("getBond(bytes32,address)") +
      this.padWord(taskId) +
      this.padWord(bonder);
    const raw = await this.ethCall(this.contracts.settlement, data);
    return BigInt(raw);
  }

  public async hasProofVerified(taskId: string): Promise<boolean> {
    const data = this.selector("hasProofVerified(bytes32)") + this.padWord(taskId);
    const raw = await this.ethCall(this.contracts.settlement, data);
    return BigInt(raw) === 1n;
  }
}
