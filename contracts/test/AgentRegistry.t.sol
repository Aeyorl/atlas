// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {AgentRegistry} from "../../contracts/core/AgentRegistry.sol";
import {IAgentRegistry} from "../../contracts/interfaces/IAgentRegistry.sol";

contract AgentRegistryTest is Test {
    AgentRegistry internal registry;

    address internal alice;
    address internal bob;

    bytes32 internal constant AGENT1_ID = keccak256("agent-1");
    bytes32 internal constant AGENT2_ID = keccak256("agent-2");
    string internal constant URI = "https://agent.example/meta.json";

    bytes32 internal constant CAP_TRADE = bytes32("TRADE");
    bytes32 internal constant CAP_ANALYZE = bytes32("ANALYZE");
    bytes32 internal constant CAP_VERIFY = bytes32("VERIFY");

    function setUp() public {
        registry = new AgentRegistry();
        alice = makeAddr("alice");
        bob = makeAddr("bob");
    }

    // ────────────────────────────────
    //  Helpers
    // ────────────────────────────────

    function _caps(bytes32 c1, bytes32 c2) internal pure returns (bytes32[] memory caps) {
        caps = new bytes32[](c2 == bytes32(0) ? 1 : 2);
        caps[0] = c1;
        if (c2 != bytes32(0)) caps[1] = c2;
    }

    function _register(address caller, bytes32 agentId, bytes32[] memory caps) internal {
        vm.prank(caller);
        registry.register(agentId, URI, caps, caller, 1 ether);
    }

    // ────────────────────────────────
    //  Registration
    // ────────────────────────────────

    function test_Register_CreatesRecord() public {
        _register(alice, AGENT1_ID, _caps(CAP_TRADE, CAP_ANALYZE));

        IAgentRegistry.AgentRecord memory r = registry.getAgent(AGENT1_ID);
        assertEq(r.agentId, AGENT1_ID);
        assertEq(r.owner, alice);
        assertEq(r.uri, URI);
        assertEq(r.capabilities.length, 2);
        assertEq(r.capabilities[0], CAP_TRADE);
        assertEq(r.executionWallet, alice);
        assertEq(r.minFee, 1 ether);
        assertTrue(r.active);
        assertEq(r.totalTasks, 0);
        assertEq(r.successfulTasks, 0);
        assertTrue(registry.isActive(AGENT1_ID));
        assertEq(registry.getAgentCount(), 1);
    }

    function test_Register_ZeroAgentIdReverts() public {
        vm.prank(alice);
        vm.expectRevert(AgentRegistry.AgentRegistry__ZeroAgentId.selector);
        registry.register(bytes32(0), URI, _caps(CAP_TRADE, bytes32(0)), alice, 0);
    }

    function test_Register_DuplicateIdReverts() public {
        _register(alice, AGENT1_ID, _caps(CAP_TRADE, bytes32(0)));
        vm.prank(bob);
        vm.expectRevert(AgentRegistry.AgentRegistry__AlreadyRegistered.selector);
        registry.register(AGENT1_ID, URI, _caps(CAP_TRADE, bytes32(0)), bob, 0);
    }

    function test_Register_ZeroExecutionWalletReverts() public {
        vm.prank(alice);
        vm.expectRevert(AgentRegistry.AgentRegistry__ZeroExecutionWallet.selector);
        registry.register(AGENT1_ID, URI, _caps(CAP_TRADE, bytes32(0)), address(0), 0);
    }

    function test_Register_EmptyUriReverts() public {
        vm.prank(alice);
        vm.expectRevert(AgentRegistry.AgentRegistry__EmptyUri.selector);
        registry.register(AGENT1_ID, "", _caps(CAP_TRADE, bytes32(0)), alice, 0);
    }

    function test_Register_NoCapabilitiesReverts() public {
        vm.prank(alice);
        vm.expectRevert(AgentRegistry.AgentRegistry__NoCapabilities.selector);
        registry.register(AGENT1_ID, URI, new bytes32[](0), alice, 0);
    }

    // ────────────────────────────────
    //  Updates & ownership
    // ────────────────────────────────

    function test_UpdateAgent_OnlyOwner() public {
        _register(alice, AGENT1_ID, _caps(CAP_TRADE, bytes32(0)));

        vm.prank(bob);
        vm.expectRevert(AgentRegistry.AgentRegistry__NotOwner.selector);
        registry.updateAgent(AGENT1_ID, URI, _caps(CAP_VERIFY, bytes32(0)), 2 ether);
    }

    function test_UpdateAgent_UpdatesFields() public {
        _register(alice, AGENT1_ID, _caps(CAP_TRADE, bytes32(0)));

        vm.prank(alice);
        registry.updateAgent(AGENT1_ID, "https://agent.example/v2.json", _caps(CAP_VERIFY, bytes32(0)), 2 ether);

        IAgentRegistry.AgentRecord memory r = registry.getAgent(AGENT1_ID);
        assertEq(r.uri, "https://agent.example/v2.json");
        assertEq(r.capabilities.length, 1);
        assertEq(r.capabilities[0], CAP_VERIFY);
        assertEq(r.minFee, 2 ether);
    }

    function test_DeactivateAgent_OnlyOwner() public {
        _register(alice, AGENT1_ID, _caps(CAP_TRADE, bytes32(0)));

        vm.prank(bob);
        vm.expectRevert(AgentRegistry.AgentRegistry__NotOwner.selector);
        registry.deactivateAgent(AGENT1_ID);
    }

    function test_DeactivatedAgent_IsInactiveAndExcludedFromSearch() public {
        _register(alice, AGENT1_ID, _caps(CAP_TRADE, bytes32(0)));
        vm.prank(alice);
        registry.deactivateAgent(AGENT1_ID);

        assertFalse(registry.isActive(AGENT1_ID));
        assertEq(registry.searchByCapability(CAP_TRADE).length, 0);
    }

    function test_UnknownAgent_RevertsOnUpdate() public {
        vm.expectRevert(AgentRegistry.AgentRegistry__NotRegistered.selector);
        registry.updateAgent(AGENT1_ID, URI, _caps(CAP_TRADE, bytes32(0)), 0);
    }

    // ────────────────────────────────
    //  Discovery
    // ────────────────────────────────

    function test_SearchByCapability_FindsActiveAgentsOnly() public {
        _register(alice, AGENT1_ID, _caps(CAP_TRADE, CAP_ANALYZE));
        _register(bob, AGENT2_ID, _caps(CAP_TRADE, bytes32(0)));

        bytes32[] memory byTrade = registry.searchByCapability(CAP_TRADE);
        assertEq(byTrade.length, 2);

        bytes32[] memory byAnalyze = registry.searchByCapability(CAP_ANALYZE);
        assertEq(byAnalyze.length, 1);
        assertEq(byAnalyze[0], AGENT1_ID);

        assertEq(registry.searchByCapability(bytes32("NONEXISTENT")).length, 0);
    }

    function test_GetAgentByOwner() public {
        _register(alice, AGENT1_ID, _caps(CAP_TRADE, bytes32(0)));
        _register(alice, AGENT2_ID, _caps(CAP_ANALYZE, bytes32(0)));
        _register(bob, keccak256("agent-3"), _caps(CAP_VERIFY, bytes32(0)));

        bytes32[] memory alices = registry.getAgentByOwner(alice);
        assertEq(alices.length, 2);

        bytes32[] memory bobs = registry.getAgentByOwner(bob);
        assertEq(bobs.length, 1);
    }

    // ────────────────────────────────
    //  Reputation
    // ────────────────────────────────

    function test_UpdateReputation_RevertsWhenTaskManagerNotSet() public {
        _register(alice, AGENT1_ID, _caps(CAP_TRADE, bytes32(0)));

        vm.expectRevert(AgentRegistry.AgentRegistry__TaskManagerNotSet.selector);
        registry.updateReputation(AGENT1_ID, true);
    }

    function test_UpdateReputation_OnlyTaskManager() public {
        _register(alice, AGENT1_ID, _caps(CAP_TRADE, bytes32(0)));
        registry.setTaskManager(address(this));

        vm.prank(alice);
        vm.expectRevert(AgentRegistry.AgentRegistry__NotTaskManager.selector);
        registry.updateReputation(AGENT1_ID, true);
    }

    function test_UpdateReputation_TracksSuccessRate() public {
        _register(alice, AGENT1_ID, _caps(CAP_TRADE, bytes32(0)));
        registry.setTaskManager(address(this));

        registry.updateReputation(AGENT1_ID, true);
        registry.updateReputation(AGENT1_ID, true);
        registry.updateReputation(AGENT1_ID, false);

        IAgentRegistry.AgentRecord memory r = registry.getAgent(AGENT1_ID);
        assertEq(r.totalTasks, 3);
        assertEq(r.successfulTasks, 2);
    }

    function test_SetTaskManager_ZeroReverts() public {
        vm.expectRevert(AgentRegistry.AgentRegistry__ZeroTaskManager.selector);
        registry.setTaskManager(address(0));
    }

    function test_SetTaskManager_OnlyAdmin() public {
        vm.prank(alice);
        vm.expectRevert();
        registry.setTaskManager(address(this));
    }
}
