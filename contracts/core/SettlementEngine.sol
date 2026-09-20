// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ISettlementEngine} from "../interfaces/ISettlementEngine.sol";
import {ITaskManager} from "../interfaces/ITaskManager.sol";
import {IVerifier} from "../interfaces/IVerifier.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/// @title SettlementEngine
/// @notice Protocol treasury: holds task escrow, executes settlement payouts,
///         splits protocol fees, and manages per-task agent bonds.
/// @dev Implements {ISettlementEngine}. The {TaskManager} owns the task
///      lifecycle and forwards all value here:
///      - TaskManager.createTask forwards the budget via {depositEscrow}.
///      - TaskManager.settleTask / resolveDispute(agentValid=true) trigger
///        {settle}, which pays the accepted agent, splits the protocol fee
///        (governor share + optional guardian share), and refunds the unspent
///        budget remainder to the creator.
///      - TaskManager.resolveDispute(agentValid=false) and withdrawEscrow
///        trigger {refundCreator}, returning the full escrow on failure paths
///        (guardian-resolved dispute outcomes included).
///      ZK verification (Phase 2): when a verifier is configured via
///      {setVerifier}, `settle` requires a valid ZK execution proof for the
///      task before paying out. The proof arrives in the `verification`
///      payload as `abi.encode(proof, publicInputs)` and is checked against
///      the pluggable {IVerifier}; `publicInputs[0]` must equal the task id,
///      binding every proof to exactly one task. With no verifier configured
///      (V1 mode), settlement proceeds on governor verification alone.
contract SettlementEngine is ISettlementEngine, ReentrancyGuard {
    // ────────────────────────────────
    //  Errors
    // ────────────────────────────────

    error SettlementEngine__ZeroGovernor();
    error SettlementEngine__ZeroTaskManager();
    error SettlementEngine__NotTaskManager();
    error SettlementEngine__NotGovernor();
    error SettlementEngine__ZeroAmount();
    error SettlementEngine__AlreadyFunded();
    error SettlementEngine__UnknownOrEmptyEscrow();
    error SettlementEngine__TaskNotCompleted();
    error SettlementEngine__AlreadySettled();
    error SettlementEngine__FeeExceedsEscrow();
    error SettlementEngine__UnknownTask();
    error SettlementEngine__NoBond();
    error SettlementEngine__TaskNotTerminal();
    error SettlementEngine__GuardianShareTooHigh();
    error SettlementEngine__PaymentFailed();
    error SettlementEngine__VerifierNotConfigured();
    error SettlementEngine__VerificationPayloadMalformed();
    error SettlementEngine__ProofTaskMismatch();
    error SettlementEngine__ResultHashNotRecorded();
    error SettlementEngine__InvalidProof();

    // ────────────────────────────────
    //  Modifiers
    // ────────────────────────────────

    modifier onlyTaskManager() {
        if (msg.sender != address(taskManager)) revert SettlementEngine__NotTaskManager();
        _;
    }

    modifier onlyGovernor() {
        if (msg.sender != governor) revert SettlementEngine__NotGovernor();
        _;
    }

    // ────────────────────────────────
    //  State
    // ────────────────────────────────

    /// @notice Task lifecycle contract — sole authority over escrow flows.
    /// @dev Set post-deploy (TaskManager's constructor needs the engine first).
    ITaskManager public taskManager;

    /// @notice Governance: collects the protocol fee share, slashes bonds,
    ///         rotates admin params. Multisig/DAO in production.
    address public governor;

    /// @notice Recipient of the guardian fee share (guardian committee vault).
    /// @dev Zero address until the guardian committee module ships; with
    ///      guardianShareBps = 0 the entire protocol cut goes to the governor.
    address public guardianTreasury;

    /// @notice Guardian share of the protocol cut, in basis points (0..10_000).
    uint256 public guardianShareBps;

    /// @dev taskId => escrowed budget held by this contract
    mapping(bytes32 => uint256) private _escrow;

    /// @dev taskId => settlement record (zeroed `settled` = not settled)
    mapping(bytes32 => Settlement) private _settlements;

    /// @dev taskId => whether escrow was fully refunded on a failure path
    mapping(bytes32 => bool) private _refunded;

    /// @dev taskId => bonder => bonded amount
    mapping(bytes32 => mapping(address => uint256)) private _bonds;

    /// @notice Pluggable ZK proof verifier (Nive Verifier). Zero address =
    ///         disabled: settle() then trusts governor verification alone.
    IVerifier public verifier;

    /// @dev taskId => whether a valid ZK proof was verified at settle time
    mapping(bytes32 => bool) private _proofVerified;

    // ────────────────────────────────
    //  Events (extensions to ISettlementEngine)
    // ────────────────────────────────

    event EscrowDeposited(bytes32 indexed taskId, address indexed funder, uint256 amount);
    event CreatorRefunded(bytes32 indexed taskId, address indexed creator, uint256 amount);
    event BondReleased(bytes32 indexed taskId, address indexed agent, uint256 amount);
    event GuardianTreasuryUpdated(address indexed oldTreasury, address indexed newTreasury);
    event GuardianShareUpdated(uint256 oldBps, uint256 newBps);
    event VerifierUpdated(address indexed oldVerifier, address indexed newVerifier);
    event ProofVerified(bytes32 indexed taskId, address indexed verifier);

    // ────────────────────────────────
    //  Constructor
    // ────────────────────────────────

    constructor(address _governor) {
        if (_governor == address(0)) revert SettlementEngine__ZeroGovernor();
        governor = _governor;
    }

    // ────────────────────────────────
    //  Admin
    // ────────────────────────────────

    /// @notice Wire the TaskManager allowed to move escrow.
    /// @dev Post-deploy call; deployment is circular otherwise.
    function setTaskManager(address newTaskManager) external onlyGovernor {
        if (newTaskManager == address(0)) revert SettlementEngine__ZeroTaskManager();
        taskManager = ITaskManager(newTaskManager);
    }

    /// @notice Set the recipient of the guardian fee share.
    function setGuardianTreasury(address newTreasury) external onlyGovernor {
        address old = guardianTreasury;
        guardianTreasury = newTreasury;
        emit GuardianTreasuryUpdated(old, newTreasury);
    }

    /// @notice Set the guardian share of the protocol cut (bounded to 100%).
    function setGuardianShareBps(uint256 newBps) external onlyGovernor {
        if (newBps > 10_000) revert SettlementEngine__GuardianShareTooHigh();
        uint256 old = guardianShareBps;
        guardianShareBps = newBps;
        emit GuardianShareUpdated(old, newBps);
    }

    /// @notice Configure the ZK proof verifier used to gate settlement.
    /// @dev Pass the zero address to disable proof enforcement (V1 mode).
    ///      Implementations are invoked via staticcall from settle(), so they
    ///      must be side-effect free.
    function setVerifier(address newVerifier) external onlyGovernor {
        address old = address(verifier);
        verifier = IVerifier(newVerifier);
        emit VerifierUpdated(old, newVerifier);
    }

    /// @notice Transfer governor authority (multisig/DAO rotation).
    function setGovernor(address newGovernor) external onlyGovernor {
        if (newGovernor == address(0)) revert SettlementEngine__ZeroGovernor();
        governor = newGovernor;
    }

    // ────────────────────────────────
    //  Escrow (TaskManager-controlled)
    // ────────────────────────────────

    /// @notice Receive a task budget from TaskManager.createTask.
    function depositEscrow(bytes32 taskId) external payable onlyTaskManager nonReentrant {
        if (msg.value == 0) revert SettlementEngine__ZeroAmount();
        if (_escrow[taskId] != 0 || _settlements[taskId].settled || _refunded[taskId]) {
            revert SettlementEngine__AlreadyFunded();
        }
        _escrow[taskId] = msg.value;
        emit EscrowDeposited(taskId, msg.sender, msg.value);
    }

    /// @notice Return the full remaining escrow to the creator on a failure
    ///         path (failed task, lost dispute, escrow withdrawal).
    function refundCreator(bytes32 taskId) external onlyTaskManager nonReentrant {
        uint256 escrow = _escrow[taskId];
        if (escrow == 0) revert SettlementEngine__UnknownOrEmptyEscrow();
        _escrow[taskId] = 0;
        _refunded[taskId] = true;

        address creator = taskManager.getTask(taskId).creator;
        if (creator == address(0)) revert SettlementEngine__UnknownTask();

        _pay(creator, escrow);
        emit CreatorRefunded(taskId, creator, escrow);
    }

    /// @notice Execute settlement for a Completed task: pay the accepted
    ///         agent, split the protocol fee, refund the budget remainder,
    ///         and release the assigned agent's bond.
    /// @dev Only the TaskManager may call this, after it has enforced the
    ///      dispute window / dispute resolution rules. When a ZK verifier is
    ///      configured, `verification` must carry
    ///      `abi.encode(proof, publicInputs)` for a valid execution proof
    ///      whose first public input is `uint256(taskId)`.
    function settle(bytes32 taskId, bytes calldata verification) external override onlyTaskManager nonReentrant {
        // Settled check first: settle() zeroes escrow, so a replay would
        // otherwise surface as the less precise empty-escrow error.
        if (_settlements[taskId].settled) revert SettlementEngine__AlreadySettled();

        _verifyProof(taskId, verification);

        uint256 escrow = _escrow[taskId];
        if (escrow == 0) revert SettlementEngine__UnknownOrEmptyEscrow();

        ITaskManager.Task memory task = taskManager.getTask(taskId);
        if (task.status != ITaskManager.TaskStatus.Completed) revert SettlementEngine__TaskNotCompleted();

        uint256 fee = _acceptedFee(taskId, task.assignedAgent);
        if (fee > escrow) revert SettlementEngine__FeeExceedsEscrow();

        uint256 protocolCut = (fee * taskManager.protocolFeeBps()) / 10_000;
        uint256 guardianCut = (protocolCut * guardianShareBps) / 10_000;
        uint256 protocolNet = protocolCut - guardianCut;
        uint256 agentCut = fee - protocolCut;

        // Zero accounting before any external call (CEI).
        _escrow[taskId] = 0;
        Settlement storage s = _settlements[taskId];
        s.taskId = taskId;
        s.agent = task.assignedAgent;
        s.creator = task.creator;
        s.agentFee = agentCut;
        s.guardianFee = guardianCut;
        s.protocolFee = protocolNet;
        s.settled = true;

        // Release the assigned agent's bond, if one was posted.
        uint256 bond = _bonds[taskId][task.assignedAgent];
        if (bond > 0) {
            _bonds[taskId][task.assignedAgent] = 0;
            _pay(task.assignedAgent, bond);
            emit BondReleased(taskId, task.assignedAgent, bond);
        }

        _pay(task.assignedAgent, agentCut);
        emit PaymentSettled(taskId, task.assignedAgent, agentCut);

        if (protocolNet > 0) {
            _pay(governor, protocolNet);
        }
        if (guardianCut > 0) {
            // guardianTreasury defaults to the governor until the committee
            // module exists, so the earmarked share is never stranded.
            _pay(guardianTreasury == address(0) ? governor : guardianTreasury, guardianCut);
        }
        emit FeeDistributed(taskId, guardianCut, protocolNet);

        uint256 remainder = escrow - fee;
        if (remainder > 0) {
            _pay(task.creator, remainder);
            emit CreatorRefunded(taskId, task.creator, remainder);
        }
    }

    // ────────────────────────────────
    //  Bonds
    // ────────────────────────────────

    /// @notice Post (or top up) a bond for a task. Returned automatically to
    ///         the assigned agent on successful settlement; withdrawable once
    ///         the task reaches a terminal state; slashable by governance.
    function postBond(bytes32 taskId) external payable override nonReentrant {
        if (msg.value == 0) revert SettlementEngine__ZeroAmount();
        _bonds[taskId][msg.sender] += msg.value;
        emit BondPosted(taskId, msg.sender, msg.value);
    }

    /// @notice Slash a bonded amount on a task, paying it to the task creator
    ///         as failure compensation. Slashes at most the bonded amount.
    function slash(bytes32 taskId, address agent, uint256 amount) external override onlyGovernor nonReentrant {
        uint256 bond = _bonds[taskId][agent];
        if (bond == 0) revert SettlementEngine__NoBond();

        address creator = taskManager.getTask(taskId).creator;
        if (creator == address(0)) revert SettlementEngine__UnknownTask();

        uint256 cut = amount > bond ? bond : amount;
        _bonds[taskId][agent] = bond - cut;
        _pay(creator, cut);
        emit BondSlash(taskId, agent, cut);
    }

    /// @notice Withdraw your bond once the task is terminal (settled or
    ///         creator-refunded). Successful settlement auto-releases the
    ///         assigned agent's bond; this covers other bonders and
    ///         failure paths.
    function withdrawBond(bytes32 taskId) external nonReentrant {
        uint256 bond = _bonds[taskId][msg.sender];
        if (bond == 0) revert SettlementEngine__NoBond();

        // A task that was never created on the TaskManager can never reach a
        // terminal state — treat it as claimable instead of trapping the bond.
        bool taskExists = taskManager.getTask(taskId).taskId != bytes32(0);
        if (taskExists && !_settlements[taskId].settled && !_refunded[taskId]) {
            revert SettlementEngine__TaskNotTerminal();
        }

        _bonds[taskId][msg.sender] = 0;
        _pay(msg.sender, bond);
        emit BondReleased(taskId, msg.sender, bond);
    }

    // ────────────────────────────────
    //  Queries
    // ────────────────────────────────

    /// @inheritdoc ISettlementEngine
    function getSettlement(bytes32 taskId) external view override returns (Settlement memory) {
        return _settlements[taskId];
    }

    /// @notice Escrow still held for a task.
    function getEscrow(bytes32 taskId) external view returns (uint256) {
        return _escrow[taskId];
    }

    /// @notice Bond posted by `agent` on `taskId`.
    function getBond(bytes32 taskId, address agent) external view returns (uint256) {
        return _bonds[taskId][agent];
    }

    /// @notice Whether settlement of `taskId` was gated by a valid ZK proof.
    function hasProofVerified(bytes32 taskId) external view returns (bool) {
        return _proofVerified[taskId];
    }

    // ────────────────────────────────
    //  Internal
    // ────────────────────────────────

    /// @dev The fee of the accepted bid for the assigned agent.
    function _acceptedFee(bytes32 taskId, address agent) internal view returns (uint256) {
        ITaskManager.Bid[] memory bids = taskManager.getBids(taskId);
        for (uint256 i = 0; i < bids.length; i++) {
            if (bids[i].bidder == agent && bids[i].status == ITaskManager.BidStatus.Accepted) {
                return bids[i].fee;
            }
        }
        revert SettlementEngine__UnknownTask();
    }

    function _pay(address to, uint256 amount) internal {
        (bool ok, ) = to.call{value: amount}("");
        if (!ok) revert SettlementEngine__PaymentFailed();
    }

    /// @dev ZK proof gate for settle(). No-op while no verifier is configured
    ///      (V1 governor-trust mode). When configured, `verification` must be
    ///      `abi.encode(bytes proof, uint256[] publicInputs)` and the proof
    ///      must be bound to the task via the canonical 128-bit limb layout:
    ///
    ///        publicInputs[0] = taskId_lo  (low 128 bits of taskId)
    ///        publicInputs[1] = taskId_hi  (high 128 bits of taskId)
    ///        publicInputs[2] = resultHash_lo (optional, low 128 bits)
    ///        publicInputs[3] = resultHash_hi (optional, high 128 bits)
    ///
    ///      Both 128-bit limbs are always < r, so they survive Groth16 scalar
    ///      reduction unchanged and reconstruct the exact 256-bit id. This
    ///      matters for soundness: binding the RAW id (>= r about 60% of the
    ///      time) would verify a statement over (id mod r), and an attacker
    ///      could mint a second task id congruent mod r and replay one
    ///      legitimate proof to settle both tasks. It also keeps inputs
    ///      compatible with provers that reject >= r (snarkjs checkField).
    function _verifyProof(bytes32 taskId, bytes calldata verification) internal {
        if (address(verifier) == address(0)) return;

        // Explicit guard: abi.decode on empty data would revert generically.
        if (verification.length == 0) revert SettlementEngine__VerificationPayloadMalformed();

        bytes memory proof;
        uint256[] memory publicInputs;
        (proof, publicInputs) = abi.decode(verification, (bytes, uint256[]));

        // Canonical task binding: exactly [taskId_lo, taskId_hi, ...]
        // with both limbs reconstructing the full 256-bit task id.
        if (
            publicInputs.length < 2
                || publicInputs[0] > type(uint128).max
                || publicInputs[1] > type(uint128).max
                || (publicInputs[1] << 128 | publicInputs[0]) != uint256(taskId)
        ) {
            revert SettlementEngine__ProofTaskMismatch();
        }
        // Optional result binding: when the circuit commits to a result
        // hash, it must occupy limbs [2..3] and reconstruct the exact value
        // the TaskManager recorded at completion (sha256 — matching the
        // circuit's statement, see TaskManager.getResultHash).
        if (publicInputs.length != 0 && publicInputs.length != 2 && publicInputs.length != 4) {
            revert SettlementEngine__ProofTaskMismatch();
        }
        if (publicInputs.length == 4) {
            bytes32 recordedHash = taskManager.getResultHash(taskId);
            if (
                publicInputs[2] > type(uint128).max
                    || publicInputs[3] > type(uint128).max
                    || (publicInputs[3] << 128 | publicInputs[2]) != uint256(recordedHash)
            ) {
                revert SettlementEngine__ProofTaskMismatch();
            }
            if (recordedHash == bytes32(0)) {
                revert SettlementEngine__ResultHashNotRecorded();
            }
            if (publicInputs[2] == 0 && publicInputs[3] == 0) {
                revert SettlementEngine__InvalidProof();
            }
        }

        bool valid = verifier.verifyProof(proof, publicInputs);
        if (!valid) revert SettlementEngine__InvalidProof();

        _proofVerified[taskId] = true;
        emit ProofVerified(taskId, address(verifier));
    }
}
