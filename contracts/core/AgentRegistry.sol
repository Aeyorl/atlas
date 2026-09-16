// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IAgentRegistry} from "../interfaces/IAgentRegistry.sol";
import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";

/// @title AgentRegistry
/// @notice On-chain registry for AI agent identity and capability declarations.
/// @dev Implements {IAgentRegistry}. Every agent must register here before
///      participating in the Atlas protocol. Reputation updates are restricted
///      to the protocol's TaskManager so that only executed task outcomes can
///      mutate `totalTasks` / `successfulTasks`.
contract AgentRegistry is IAgentRegistry, AccessControl {
    // ────────────────────────────────
    //  Errors
    // ────────────────────────────────

    error AgentRegistry__ZeroAgentId();
    error AgentRegistry__AlreadyRegistered();
    error AgentRegistry__NotRegistered();
    error AgentRegistry__ZeroOwner();
    error AgentRegistry__ZeroExecutionWallet();
    error AgentRegistry__EmptyUri();
    error AgentRegistry__NoCapabilities();
    error AgentRegistry__NotOwner();
    error AgentRegistry__AgentInactive();
    error AgentRegistry__TaskManagerNotSet();
    error AgentRegistry__NotTaskManager();
    error AgentRegistry__ZeroTaskManager();

    // ────────────────────────────────
    //  State
    // ────────────────────────────────

    /// @notice Role required to wire the TaskManager address post-deploy.
    /// @dev Admin (DEFAULT_ADMIN_ROLE) grants this; kept separate so a
    ///      governance flow can delegate it without handing over admin.
    bytes32 public constant REGISTRY_ADMIN_ROLE = keccak256("REGISTRY_ADMIN_ROLE");

    /// @dev agentId => record
    mapping(bytes32 => AgentRecord) private _agents;

    /// @dev All registered agent ids (active or not) — enables linear discovery scans.
    bytes32[] private _agentList;

    /// @dev owner => agent ids owned by that address
    mapping(address => bytes32[]) private _agentsByOwner;

    /// @dev The only address allowed to call updateReputation.
    address public taskManager;

    // ────────────────────────────────
    //  Constructor
    // ────────────────────────────────

    constructor() {
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        _grantRole(REGISTRY_ADMIN_ROLE, msg.sender);
    }

    // ────────────────────────────────
    //  Agent Lifecycle
    // ────────────────────────────────

    /// @inheritdoc IAgentRegistry
    function register(
        bytes32 agentId,
        string memory uri,
        bytes32[] memory capabilities,
        address executionWallet,
        uint256 minFee
    ) external override returns (AgentRecord memory record) {
        if (agentId == bytes32(0)) revert AgentRegistry__ZeroAgentId();
        if (_agents[agentId].owner != address(0)) revert AgentRegistry__AlreadyRegistered();
        if (msg.sender == address(0)) revert AgentRegistry__ZeroOwner();
        if (executionWallet == address(0)) revert AgentRegistry__ZeroExecutionWallet();
        if (bytes(uri).length == 0) revert AgentRegistry__EmptyUri();
        if (capabilities.length == 0) revert AgentRegistry__NoCapabilities();

        record = AgentRecord({
            agentId: agentId,
            owner: msg.sender,
            uri: uri,
            capabilities: capabilities,
            executionWallet: executionWallet,
            minFee: minFee,
            active: true,
            totalTasks: 0,
            successfulTasks: 0
        });

        _agents[agentId] = record;
        _agentList.push(agentId);
        _agentsByOwner[msg.sender].push(agentId);

        emit AgentRegistered(agentId, msg.sender, uri);
    }

    /// @inheritdoc IAgentRegistry
    function updateAgent(
        bytes32 agentId,
        string memory uri,
        bytes32[] memory newCapabilities,
        uint256 newMinFee
    ) external override {
        AgentRecord storage agent = _requireAgent(agentId);
        if (agent.owner != msg.sender) revert AgentRegistry__NotOwner();
        if (!agent.active) revert AgentRegistry__AgentInactive();
        if (bytes(uri).length == 0) revert AgentRegistry__EmptyUri();
        if (newCapabilities.length == 0) revert AgentRegistry__NoCapabilities();

        agent.uri = uri;
        agent.capabilities = newCapabilities;
        agent.minFee = newMinFee;

        emit AgentUpdated(agentId, uri, newCapabilities);
    }

    /// @inheritdoc IAgentRegistry
    function deactivateAgent(bytes32 agentId) external override {
        AgentRecord storage agent = _requireAgent(agentId);
        if (agent.owner != msg.sender) revert AgentRegistry__NotOwner();
        if (!agent.active) revert AgentRegistry__AgentInactive();

        agent.active = false;

        emit AgentDeactivated(agentId);
    }

    /// @inheritdoc IAgentRegistry
    function updateReputation(bytes32 agentId, bool taskSuccess) external override {
        if (taskManager == address(0)) revert AgentRegistry__TaskManagerNotSet();
        if (msg.sender != taskManager) revert AgentRegistry__NotTaskManager();

        AgentRecord storage agent = _requireAgent(agentId);

        agent.totalTasks += 1;
        if (taskSuccess) {
            agent.successfulTasks += 1;
        }

        uint256 successRate = agent.totalTasks == 0
            ? 0
            : (agent.successfulTasks * 10_000) / agent.totalTasks;

        emit AgentReputationUpdated(agentId, successRate);
    }

    // ────────────────────────────────
    //  Admin
    // ────────────────────────────────

    /// @notice Wire the TaskManager allowed to push reputation updates.
    /// @dev Post-deploy call because TaskManager's constructor needs the
    ///      registry address first (deployment is circular otherwise).
    function setTaskManager(address newTaskManager) external onlyRole(REGISTRY_ADMIN_ROLE) {
        if (newTaskManager == address(0)) revert AgentRegistry__ZeroTaskManager();
        taskManager = newTaskManager;
    }

    // ────────────────────────────────
    //  Queries
    // ────────────────────────────────

    /// @inheritdoc IAgentRegistry
    function getAgent(bytes32 agentId) external view override returns (AgentRecord memory) {
        return _agents[agentId];
    }

    /// @inheritdoc IAgentRegistry
    function getAgentByOwner(address owner) external view override returns (bytes32[] memory) {
        return _agentsByOwner[owner];
    }

    /// @inheritdoc IAgentRegistry
    function getAgentCount() external view override returns (uint256) {
        return _agentList.length;
    }

    /// @inheritdoc IAgentRegistry
    function searchByCapability(bytes32 capability) external view override returns (bytes32[] memory) {
        // Linear scan keeps the index always-correct even after capability
        // updates/deactivations; agent counts are small at this stage.
        bytes32[] memory tmp = new bytes32[](_agentList.length);
        uint256 count = 0;
        for (uint256 i = 0; i < _agentList.length; i++) {
            bytes32 agentId = _agentList[i];
            AgentRecord storage agent = _agents[agentId];
            if (!agent.active) continue;
            for (uint256 j = 0; j < agent.capabilities.length; j++) {
                if (agent.capabilities[j] == capability) {
                    tmp[count] = agentId;
                    count++;
                    break;
                }
            }
        }

        bytes32[] memory result = new bytes32[](count);
        for (uint256 i = 0; i < count; i++) {
            result[i] = tmp[i];
        }
        return result;
    }

    /// @inheritdoc IAgentRegistry
    function isActive(bytes32 agentId) external view override returns (bool) {
        return _agents[agentId].owner != address(0) && _agents[agentId].active;
    }

    // ────────────────────────────────
    //  Internal
    // ────────────────────────────────

    function _requireAgent(bytes32 agentId) internal view returns (AgentRecord storage agent) {
        agent = _agents[agentId];
        if (agent.owner == address(0)) revert AgentRegistry__NotRegistered();
    }
}
