// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title ISettlementEngine
/// @notice Handles payment settlement, fee distribution, and slashing
interface ISettlementEngine {
    struct Settlement {
        bytes32 taskId;
        address agent;
        address creator;
        uint256 agentFee;
        uint256 guardianFee;
        uint256 protocolFee;
        bool    settled;
    }

    event PaymentSettled(bytes32 indexed taskId, address indexed agent, uint256 amount);
    event FeeDistributed(bytes32 indexed taskId, uint256 guardianShare, uint256 protocolShare);
    event BondSlash(bytes32 indexed taskId, address indexed agent, uint256 amount);
    event BondPosted(bytes32 indexed taskId, address indexed agent, uint256 amount);

    function postBond(bytes32 taskId) external payable;
    function settle(bytes32 taskId, bytes calldata verification) external;
    function slash(bytes32 taskId, address agent, uint256 amount) external;
    function getSettlement(bytes32 taskId) external view returns (Settlement memory);

    // ────────────────────────────────
    //  Escrow plumbing (TaskManager-controlled)
    // ────────────────────────────────

    /// @notice Receive a task budget forwarded by TaskManager.createTask.
    function depositEscrow(bytes32 taskId) external payable;

    /// @notice Return the full remaining escrow to the task creator on a
    ///         failure path (failed task, lost dispute, escrow withdrawal).
    function refundCreator(bytes32 taskId) external;

    /// @notice Escrow still held for a task.
    function getEscrow(bytes32 taskId) external view returns (uint256);
}
