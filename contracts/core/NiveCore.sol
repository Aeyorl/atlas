// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {INiveCore} from "../interfaces/INiveCore.sol";
import {IAgentRegistry} from "../interfaces/IAgentRegistry.sol";
import {ITaskManager} from "../interfaces/ITaskManager.sol";
import {ISettlementEngine} from "../interfaces/ISettlementEngine.sol";
import {INiveBridge} from "../interfaces/INiveBridge.sol";

/// @title NiveCore
/// @notice Core protocol contract — entry point for all Nive operations
/// @dev This is the main contract that coordinates agent registration, task
///      lifecycle, cross-ecosystem messaging, and economic settlement across
///      Robinhood Chain, EVM ecosystems, and Virtuals Protocol.
contract NiveCore is INiveCore {
    // ────────────────────────────────
    //  State
    // ────────────────────────────────

    /// @dev Protocol version tracking
    bytes32 public constant override VERSION = keccak256("nive-core-v0.1.3");

    /// @dev Supported ecosystems
    bytes32 public constant override ECOSYSTEM_ROBINHOOD = keccak256("robinhood-chain");
    bytes32 public constant override ECOSYSTEM_EVM       = keccak256("evm");
    bytes32 public constant override ECOSYSTEM_VIRTUALS   = keccak256("virtuals");

    /// @dev Guardian configuration
    uint256 public constant override MIN_GUARDIAN_STAKE = 10_000 ether;
    uint256 public constant override GUARDIAN_COMMITTEE_SIZE = 5;
    uint256 public constant override SLASH_PERCENTAGE = 5_000; // 50% in bps

    IAgentRegistry    public immutable agentRegistry;
    ITaskManager      public immutable taskManager;
    ISettlementEngine public immutable settlementEngine;
    INiveBridge      public immutable bridge;

    mapping(address => GuardianInfo) public guardians;
    address[] public guardianList;

    uint256 public override protocolVersion;
    bool    public override paused;

    /// @dev Governance authority (multisig/DAO). Can pause the protocol and
    ///      slash guardians; rotatable via {setGovernor}.
    address public governor;


    // ────────────────────────────────
    //  Constructor
    // ────────────────────────────────

    constructor(
        address _agentRegistry,
        address _taskManager,
        address _settlementEngine,
        address _bridge
    ) {
        agentRegistry    = IAgentRegistry(_agentRegistry);
        taskManager      = ITaskManager(_taskManager);
        settlementEngine = ISettlementEngine(_settlementEngine);
        bridge           = INiveBridge(_bridge);
        protocolVersion  = 1;
        governor         = msg.sender;
    }

    // ────────────────────────────────
    //  Modifiers
    // ────────────────────────────────

    modifier onlyGovernor() {
        require(msg.sender == governor, "NiveCore: not governor");
        _;
    }

    // ────────────────────────────────
    //  Guardian Management
    // ────────────────────────────────

    /// @inheritdoc INiveCore
    function registerGuardian(uint256 stakeAmount) external override {
        require(!paused, "NiveCore: paused");
        require(stakeAmount >= MIN_GUARDIAN_STAKE, "NiveCore: insufficient stake");
        require(guardians[msg.sender].stake == 0, "NiveCore: already guardian");

        guardians[msg.sender] = GuardianInfo({
            staker: msg.sender,
            stake: stakeAmount,
            active: true,
            tasksVerified: 0,
            tasksSlashed: 0
        });
        guardianList.push(msg.sender);
        emit GuardianRegistered(msg.sender, stakeAmount);
    }

    /// @inheritdoc INiveCore
    function slashGuardian(address guardian, uint256 amount) external override onlyGovernor {
        require(guardians[guardian].stake >= amount, "NiveCore: insufficient stake");
        guardians[guardian].stake -= amount;
        guardians[guardian].tasksSlashed++;
        emit GuardianSlashed(guardian, amount);
    }

    // ────────────────────────────────
    //  Protocol Management
    // ────────────────────────────────

    /// @inheritdoc INiveCore
    function pause() external override onlyGovernor {
        require(!paused, "NiveCore: already paused");
        paused = true;
        emit ProtocolPaused(msg.sender);
    }

    /// @inheritdoc INiveCore
    function unpause() external override onlyGovernor {
        require(paused, "NiveCore: not paused");
        paused = false;
        emit ProtocolUnpaused(msg.sender);
    }

    /// @notice Transfer governor authority (multisig/DAO rotation).
    function setGovernor(address newGovernor) external onlyGovernor {
        require(newGovernor != address(0), "NiveCore: zero governor");
        address old = governor;
        governor = newGovernor;
        emit GovernorUpdated(old, newGovernor);
    }

    /// @inheritdoc INiveCore
    function getGuardianCount() external view override returns (uint256) {
        return guardianList.length;
    }
}
