export type Ecosystem = "robinhood-chain" | "evm" | "virtuals";

export type TaskStatus =
  | "Pending"
  | "Bidding"
  | "Executing"
  | "Verifying"
  | "Completed"
  | "Failed"
  | "Disputed";

export interface ContractsConfig {
  registry: string;
  taskManager: string;
  settlement: string;
  bridge?: string;
  core?: string;
}

export interface AgentRecord {
  agentId: string;
  owner: string;
  uri: string;
  capabilities: string[];
  executionWallet: string;
  minFeeWei: bigint;
  active: boolean;
  totalTasks: number;
  successfulTasks: number;
}

export interface TaskRecord {
  taskId: string;
  creator: string;
  requiredCapabilities: string[];
  budgetWei: bigint;
  parameters: string;
  status: TaskStatus;
  assignedAgent: string;
  createdAt: number;
  deadline: number;
}

export interface BidRecord {
  bidder: string;
  feeWei: bigint;
  status: "Pending" | "Accepted" | "Rejected";
}

export interface SettlementRecord {
  taskId: string;
  agent: string;
  creator: string;
  agentFeeWei: bigint;
  guardianFeeWei: bigint;
  protocolFeeWei: bigint;
  settled: boolean;
}

export interface TxReceipt {
  txHash: string;
  status: string;
  blockNumber: number;
  gasUsed: bigint;
}
