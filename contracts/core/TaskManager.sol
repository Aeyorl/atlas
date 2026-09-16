// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ITaskManager} from "../interfaces/ITaskManager.sol";
import {IAgentRegistry} from "../interfaces/IAgentRegistry.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/// @title TaskManager
/// @notice Manages the lifecycle of agent tasks: creation, bidding, execution,
///         verification, dispute, and settlement.
/// @dev Implements {ITaskManager}. Task budgets are escrowed in native currency
///      at creation. Bids are restricted to active agents registered in the
///      {AgentRegistry} that declare every required capability. Settlement pays
///      the accepted agent (minus the protocol fee), refunds the unspent budget
///      remainder to the task creator, and pushes a reputation update to the
///      registry. A dispute window between verification and settlement lets the
///      creator challenge the result; a governor resolves disputes.
contract TaskManager is ITaskManager, ReentrancyGuard {
    // ────────────────────────────────
    //  Errors
    // ────────────────────────────────

    error TaskManager__ZeroRegistry();
    error TaskManager__ZeroGovernor();
    error TaskManager__ZeroTaskId();
    error TaskManager__TaskExists();
    error TaskManager__UnknownTask();
    error TaskManager__ZeroEscrow();
    error TaskManager__BudgetMismatch();
    error TaskManager__NoRequiredCapabilities();
    error TaskManager__DeadlineInPast();
    error TaskManager__DeadlinePassed();
    error TaskManager__NotInBidding();
    error TaskManager__NotExecuting();
    error TaskManager__NotVerifying();
    error TaskManager__NotDisputed();
    error TaskManager__NotAssignedAgent();
    error TaskManager__NotCreator();
    error TaskManager__NotGovernor();
    error TaskManager__FeeExceedsBudget();
    error TaskManager__DuplicateBid();
    error TaskManager__BidNotFound();
    error TaskManager__NoCapableAgent();
    error TaskManager__AmbiguousAgent();
    error TaskManager__DisputeWindowOpen();
    error TaskManager__DisputeWindowClosed();
    error TaskManager__TaskNotFailed();
    error TaskManager__FeeTooHigh();
    error TaskManager__PaymentFailed();

    // ────────────────────────────────
    //  Types
    // ────────────────────────────────

    modifier onlyGovernor() {
        if (msg.sender != governor) revert TaskManager__NotGovernor();
        _;
    }

    // ────────────────────────────────
    //  Constants
    // ────────────────────────────────

    uint256 public constant MAX_PROTOCOL_FEE_BPS = 5_000; // 50%
    uint256 public constant DISPUTE_WINDOW = 3 days;

    // ────────────────────────────────
    //  State
    // ────────────────────────────────

    /// @notice Agent registry used for bid eligibility and reputation updates.
    IAgentRegistry public immutable registry;

    /// @notice Governor: verifies task results, resolves disputes, collects
    ///         the protocol fee. In production this should be governed by a
    ///         multisig/DAO or the Guardian committee.
    address public governor;

    /// @notice Protocol fee in basis points, taken from the agent fee on settlement.
    uint256 public protocolFeeBps;

    uint256 private _taskCounter;

    /// @dev taskId => task record
    mapping(bytes32 => Task) private _tasks;

    /// @dev taskId => bids in submission order
    mapping(bytes32 => Bid[]) private _bids;

    /// @dev taskId => escrowed budget still held by this contract
    mapping(bytes32 => uint256) private _escrow;

    /// @dev taskId => bidder => agentId the bidder bids with (resolved at submitBid)
    mapping(bytes32 => mapping(address => bytes32)) private _bidAgentIds;

    /// @dev taskId => timestamp of successful verification (0 = not verified)
    mapping(bytes32 => uint256) private _verifiedAt;

    // ────────────────────────────────
    //  Events (extensions to ITaskManager)
    // ────────────────────────────────

    event TaskSettled(bytes32 indexed taskId, address indexed agent, uint256 agentFee);
    event TaskFailed(bytes32 indexed taskId);
    event EscrowRefunded(bytes32 indexed taskId, uint256 amount);
    event ProtocolFeeUpdated(uint256 oldFeeBps, uint256 newFeeBps);

    // ────────────────────────────────
    //  Constructor
    // ────────────────────────────────

    constructor(address _registry, address _governor) {
        if (_registry == address(0)) revert TaskManager__ZeroRegistry();
        if (_governor == address(0)) revert TaskManager__ZeroGovernor();
        registry = IAgentRegistry(_registry);
        governor = _governor;
        protocolFeeBps = 250; // 2.5%
    }

    // ────────────────────────────────
    //  Task Lifecycle
    // ────────────────────────────────

    /// @inheritdoc ITaskManager
    function createTask(
        bytes32 taskId,
        bytes32[] calldata requiredCapabilities,
        uint256 budget,
        bytes calldata parameters,
        uint256 deadline
    ) external payable override returns (Task memory task) {
        if (taskId == bytes32(0)) revert TaskManager__ZeroTaskId();
        if (_tasks[taskId].creator != address(0)) revert TaskManager__TaskExists();
        if (msg.value == 0) revert TaskManager__ZeroEscrow();
        if (msg.value != budget) revert TaskManager__BudgetMismatch();
        if (requiredCapabilities.length == 0) revert TaskManager__NoRequiredCapabilities();
        if (deadline <= block.timestamp) revert TaskManager__DeadlineInPast();

        _tasks[taskId] = Task({
            taskId: taskId,
            creator: msg.sender,
            requiredCapabilities: requiredCapabilities,
            budget: budget,
            parameters: parameters,
            status: TaskStatus.Bidding,
            assignedAgent: address(0),
            createdAt: block.timestamp,
            deadline: deadline
        });
        _escrow[taskId] = msg.value;
        _taskCounter++;

        emit TaskCreated(taskId, msg.sender, budget);
        return _tasks[taskId];
    }

    /// @inheritdoc ITaskManager
    function submitBid(bytes32 taskId, uint256 fee) external override {
        Task storage t = _requireTask(taskId);
        if (t.status != TaskStatus.Bidding) revert TaskManager__NotInBidding();
        if (block.timestamp > t.deadline) revert TaskManager__DeadlinePassed();
        if (fee > t.budget) revert TaskManager__FeeExceedsBudget();

        Bid[] storage bids = _bids[taskId];
        for (uint256 i = 0; i < bids.length; i++) {
            if (bids[i].bidder == msg.sender) revert TaskManager__DuplicateBid();
        }

        // Resolve and pin the agentId this bidder is bidding with — the
        // bidder must be a registered, active agent declaring every
        // required capability. Resolving here (not at accept time) keeps
        // acceptBid's address-only signature from the interface intact.
        _bidAgentIds[taskId][msg.sender] = _resolveAgentId(t);

        bids.push(Bid({bidder: msg.sender, fee: fee, status: BidStatus.Pending}));

        emit BidSubmitted(taskId, msg.sender, fee);
    }

    /// @inheritdoc ITaskManager
    function acceptBid(bytes32 taskId, address agent) external override {
        Task storage t = _requireTask(taskId);
        if (t.status != TaskStatus.Bidding) revert TaskManager__NotInBidding();
        if (block.timestamp > t.deadline) revert TaskManager__DeadlinePassed();
        if (msg.sender != t.creator && msg.sender != governor) revert TaskManager__NotCreator();

        Bid[] storage bids = _bids[taskId];
        bool found = false;
        for (uint256 i = 0; i < bids.length; i++) {
            if (bids[i].bidder == agent && bids[i].status == BidStatus.Pending) {
                bids[i].status = BidStatus.Accepted;
                found = true;
            } else if (bids[i].status == BidStatus.Pending) {
                bids[i].status = BidStatus.Rejected;
            }
        }
        if (!found) revert TaskManager__BidNotFound();

        t.assignedAgent = agent;
        t.status = TaskStatus.Executing;

        emit BidAccepted(taskId, agent);
    }

    /// @inheritdoc ITaskManager
    function completeTask(bytes32 taskId, bytes calldata result, bytes calldata proof) external override {
        Task storage t = _requireTask(taskId);
        if (t.status != TaskStatus.Executing) revert TaskManager__NotExecuting();
        if (msg.sender != t.assignedAgent) revert TaskManager__NotAssignedAgent();
        if (block.timestamp > t.deadline) revert TaskManager__DeadlinePassed();

        // `proof` is forwarded off-chain (Verifier integration is Phase 2);
        // it is kept in calldata so the interface and event trail stay stable.
        t.status = TaskStatus.Verifying;

        emit TaskCompleted(taskId, result);
    }

    /// @inheritdoc ITaskManager
    function verifyTask(bytes32 taskId, bool valid) external override onlyGovernor {
        Task storage t = _requireTask(taskId);
        if (t.status != TaskStatus.Verifying) revert TaskManager__NotVerifying();

        if (valid) {
            _verifiedAt[taskId] = block.timestamp;
            emit TaskVerified(taskId, msg.sender);
        } else {
            t.status = TaskStatus.Failed;
            _recordReputation(taskId, t.assignedAgent, false);
            emit TaskFailed(taskId);
        }
    }

    /// @inheritdoc ITaskManager
    function disputeTask(bytes32 taskId, bytes calldata evidence) external override {
        Task storage t = _requireTask(taskId);
        if (t.status != TaskStatus.Verifying) revert TaskManager__NotVerifying();
        if (msg.sender != t.creator) revert TaskManager__NotCreator();
        if (_verifiedAt[taskId] == 0 || block.timestamp > _verifiedAt[taskId] + DISPUTE_WINDOW) {
            revert TaskManager__DisputeWindowClosed();
        }

        t.status = TaskStatus.Disputed;

        emit TaskDisputed(taskId, msg.sender);
    }

    /// @notice Settle a verified task after the dispute window has elapsed.
    /// @dev Pays the accepted agent (minus protocol fee), refunds the unused
    ///      budget remainder to the creator, and records a successful
    ///      reputation update in the registry.
    function settleTask(bytes32 taskId) external override nonReentrant {
        Task storage t = _requireTask(taskId);
        if (t.status != TaskStatus.Verifying) revert TaskManager__NotVerifying();
        if (_verifiedAt[taskId] == 0 || block.timestamp <= _verifiedAt[taskId] + DISPUTE_WINDOW) {
            revert TaskManager__DisputeWindowOpen();
        }

        t.status = TaskStatus.Completed;
        _payout(taskId, t);
    }

    // ────────────────────────────────
    //  Dispute Resolution
    // ────────────────────────────────

    /// @notice Resolve a disputed task. If `agentValid`, settle in the agent's
    ///         favor; otherwise refund the full escrow to the creator and mark
    ///         the task Failed.
    function resolveDispute(bytes32 taskId, bool agentValid) external onlyGovernor nonReentrant {
        Task storage t = _requireTask(taskId);
        if (t.status != TaskStatus.Disputed) revert TaskManager__NotDisputed();

        if (agentValid) {
            t.status = TaskStatus.Completed;
            _payout(taskId, t);
        } else {
            t.status = TaskStatus.Failed;
            uint256 escrow = _escrow[taskId];
            _escrow[taskId] = 0;
            _refund(taskId, t.creator, escrow);
            _recordReputation(taskId, t.assignedAgent, false);
            emit TaskFailed(taskId);
        }
    }

    /// @notice Let the creator recover the escrow from a failed task.
    function withdrawEscrow(bytes32 taskId) external nonReentrant {
        Task storage t = _requireTask(taskId);
        if (t.status != TaskStatus.Failed) revert TaskManager__TaskNotFailed();
        if (msg.sender != t.creator) revert TaskManager__NotCreator();

        uint256 escrow = _escrow[taskId];
        if (escrow == 0) revert TaskManager__ZeroEscrow();
        _escrow[taskId] = 0;
        _refund(taskId, t.creator, escrow);
    }

    // ────────────────────────────────
    //  Governor Admin
    // ────────────────────────────────

    /// @notice Update the protocol fee (bounded to MAX_PROTOCOL_FEE_BPS).
    function setProtocolFeeBps(uint256 newFeeBps) external onlyGovernor {
        if (newFeeBps > MAX_PROTOCOL_FEE_BPS) revert TaskManager__FeeTooHigh();
        uint256 old = protocolFeeBps;
        protocolFeeBps = newFeeBps;
        emit ProtocolFeeUpdated(old, newFeeBps);
    }

    /// @notice Transfer governor authority (multisig/DAO rotation).
    function setGovernor(address newGovernor) external onlyGovernor {
        if (newGovernor == address(0)) revert TaskManager__ZeroGovernor();
        governor = newGovernor;
    }

    // ────────────────────────────────
    //  Queries
    // ────────────────────────────────

    /// @inheritdoc ITaskManager
    function getTask(bytes32 taskId) external view override returns (Task memory) {
        return _tasks[taskId];
    }

    /// @inheritdoc ITaskManager
    function getBids(bytes32 taskId) external view override returns (Bid[] memory) {
        return _bids[taskId];
    }

    /// @inheritdoc ITaskManager
    function getTaskCount() external view override returns (uint256) {
        return _taskCounter;
    }

    /// @notice AgentId a given bidder bid with on a task (for off-chain indexing).
    function getBidAgentId(bytes32 taskId, address bidder) external view returns (bytes32) {
        return _bidAgentIds[taskId][bidder];
    }

    /// @notice Escrow still held for a task.
    function getEscrow(bytes32 taskId) external view returns (uint256) {
        return _escrow[taskId];
    }

    // ────────────────────────────────
    //  Internal
    // ────────────────────────────────

    function _requireTask(bytes32 taskId) internal view returns (Task storage t) {
        t = _tasks[taskId];
        if (t.creator == address(0)) revert TaskManager__UnknownTask();
    }

    /// @dev Resolve the caller's single active agent that declares every
    ///      required capability. Multiple eligible agents under one owner is
    ///      ambiguous and rejected — the owner should bid from a dedicated agent.
    function _resolveAgentId(Task storage t) internal view returns (bytes32) {
        bytes32[] memory owned = registry.getAgentByOwner(msg.sender);
        bytes32 resolved;
        for (uint256 i = 0; i < owned.length; i++) {
            IAgentRegistry.AgentRecord memory record = registry.getAgent(owned[i]);
            if (!record.active) continue;
            if (!_hasCapabilities(record.capabilities, t.requiredCapabilities)) continue;
            if (resolved != bytes32(0)) revert TaskManager__AmbiguousAgent();
            resolved = owned[i];
        }
        if (resolved == bytes32(0)) revert TaskManager__NoCapableAgent();
        return resolved;
    }

    function _hasCapabilities(bytes32[] memory declared, bytes32[] memory required)
        internal
        pure
        returns (bool)
    {
        for (uint256 i = 0; i < required.length; i++) {
            bool found = false;
            for (uint256 j = 0; j < declared.length; j++) {
                if (declared[j] == required[i]) {
                    found = true;
                    break;
                }
            }
            if (!found) return false;
        }
        return true;
    }

    /// @dev Pay the accepted agent its fee (minus protocol fee) and refund the
    ///      unspent escrow remainder to the creator. Zeroes the escrow first.
    function _payout(bytes32 taskId, Task storage t) internal {
        uint256 escrow = _escrow[taskId];
        _escrow[taskId] = 0;

        uint256 fee = _acceptedFee(taskId, t.assignedAgent);
        uint256 protocolCut = (fee * protocolFeeBps) / 10_000;
        uint256 agentCut = fee - protocolCut;

        (bool paidAgent, ) = t.assignedAgent.call{value: agentCut}("");
        if (!paidAgent) revert TaskManager__PaymentFailed();

        if (protocolCut > 0) {
            (bool paidProtocol, ) = governor.call{value: protocolCut}("");
            if (!paidProtocol) revert TaskManager__PaymentFailed();
        }

        _refund(taskId, t.creator, escrow - fee);

        emit TaskSettled(taskId, t.assignedAgent, fee);
        _recordReputation(taskId, t.assignedAgent, true);
    }

    /// @dev The fee of the accepted bid for the assigned agent.
    function _acceptedFee(bytes32 taskId, address agent) internal view returns (uint256) {
        Bid[] storage bids = _bids[taskId];
        for (uint256 i = 0; i < bids.length; i++) {
            if (bids[i].bidder == agent && bids[i].status == BidStatus.Accepted) {
                return bids[i].fee;
            }
        }
        revert TaskManager__BidNotFound();
    }

    function _refund(bytes32 taskId, address to, uint256 amount) internal {
        if (amount == 0) return;
        (bool ok, ) = to.call{value: amount}("");
        if (!ok) revert TaskManager__PaymentFailed();
        emit EscrowRefunded(taskId, amount);
    }

    /// @dev Reputation must never block settlement payments; a misconfigured
    ///      registry link is caught and surfaced off-chain via the indexer.
    function _recordReputation(bytes32 taskId, address agent, bool success) internal {
        bytes32 agentId = _bidAgentIds[taskId][agent];
        if (agentId == bytes32(0)) return;
        try registry.updateReputation(agentId, success) {
            // success rate event emitted by the registry
        } catch {
            // settlement stands; reputation update can be replayed by tooling
        }
    }
}
