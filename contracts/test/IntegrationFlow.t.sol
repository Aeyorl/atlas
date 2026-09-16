// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {AgentRegistry} from "../core/AgentRegistry.sol";
import {TaskManager} from "../core/TaskManager.sol";
import {IAgentRegistry} from "../interfaces/IAgentRegistry.sol";

/// @title IntegrationFlowTest
/// @notice End-to-end Atlas coordination flow: register → discover → create
///         task → bid → accept → execute → verify → dispute window → settle,
///         with reputation outcomes asserted along the way.
contract IntegrationFlowTest is Test {
    AgentRegistry internal registry;
    TaskManager internal taskManager;

    address internal creator;
    address internal analystOwner;
    address internal executorOwner;
    address internal governor;

    bytes32 internal constant ANALYST = keccak256("agent-analyst");
    bytes32 internal constant EXECUTOR = keccak256("agent-executor");
    bytes32 internal constant TASK = keccak256("task-pipeline");

    bytes32 internal constant CAP_ANALYZE = bytes32("ANALYZE");
    bytes32 internal constant CAP_TRADE = bytes32("TRADE");

    string internal constant URI = "https://agent.example/meta.json";

    uint256 internal constant BUDGET = 50 ether;

    function setUp() public {
        registry = new AgentRegistry();
        governor = makeAddr("governor");
        taskManager = new TaskManager(address(registry), governor);
        registry.setTaskManager(address(taskManager));

        creator = makeAddr("creator");
        analystOwner = makeAddr("analystOwner");
        executorOwner = makeAddr("executorOwner");

        bytes32[] memory analystCaps = new bytes32[](1);
        analystCaps[0] = CAP_ANALYZE;
        vm.prank(analystOwner);
        registry.register(ANALYST, URI, analystCaps, analystOwner, 0);

        bytes32[] memory executorCaps = new bytes32[](2);
        executorCaps[0] = CAP_TRADE;
        executorCaps[1] = CAP_ANALYZE;
        vm.prank(executorOwner);
        registry.register(EXECUTOR, URI, executorCaps, executorOwner, 0);
    }

    function test_FullHappyPath_DiscoveryToSettlement() public {
        // 1. Discovery: creator finds agents with the TRADE capability
        bytes32[] memory traders = registry.searchByCapability(CAP_TRADE);
        assertEq(traders.length, 1);
        assertEq(traders[0], EXECUTOR);

        // 2. Task creation with escrow
        vm.deal(creator, BUDGET);
        vm.prank(creator);
        taskManager.createTask{value: BUDGET}(
            TASK,
            _caps(CAP_TRADE, CAP_ANALYZE),
            BUDGET,
            bytes("analyze market & execute trade"),
            block.timestamp + 7 days
        );

        // 3. Only agents covering all required capabilities can bid
        vm.prank(analystOwner);
        vm.expectRevert(TaskManager.TaskManager__NoCapableAgent.selector);
        taskManager.submitBid(TASK, 10 ether);

        // Executor (registered for both capabilities) bids and wins
        vm.prank(executorOwner);
        taskManager.submitBid(TASK, 40 ether);
        vm.prank(creator);
        taskManager.acceptBid(TASK, executorOwner);

        // 4. Execution
        vm.prank(executorOwner);
        taskManager.completeTask(TASK, "0xresult", "0xproof");

        // 5. Verification by governor
        vm.prank(governor);
        taskManager.verifyTask(TASK, true);

        // 6. Dispute window elapses, then settlement pays out
        vm.warp(block.timestamp + taskManager.DISPUTE_WINDOW() + 1);

        uint256 executorBefore = executorOwner.balance;
        uint256 governorBefore = governor.balance;
        uint256 creatorBefore = creator.balance;

        taskManager.settleTask(TASK);

        assertEq(executorOwner.balance - executorBefore, 39 ether); // 40 - 2.5%
        assertEq(governor.balance - governorBefore, 1 ether); // 2.5% of 40
        assertEq(creator.balance - creatorBefore, 10 ether); // unspent budget

        // 7. Reputation recorded for the winning agent
        IAgentRegistry.AgentRecord memory r = registry.getAgent(EXECUTOR);
        assertEq(r.totalTasks, 1);
        assertEq(r.successfulTasks, 1);
        assertEq(registry.getAgent(ANALYST).totalTasks, 0);
    }

    function test_MultiTaskReputation_AccumulatesAcrossOutcomes() public {
        // Agent wins two tasks, fails one
        _runTask(keccak256("task-1"), true); // success
        _runTask(keccak256("task-2"), true); // success
        _runTask(keccak256("task-3"), false); // rejected at verification

        IAgentRegistry.AgentRecord memory r = registry.getAgent(EXECUTOR);
        assertEq(r.totalTasks, 3);
        assertEq(r.successfulTasks, 2);
        // success rate = 2/3 = 6666 bps (rounded down)
        assertEq(r.successfulTasks * 10_000 / r.totalTasks, 6666);
    }

    // ────────────────────────────────
    //  Helpers
    // ────────────────────────────────

    function _caps(bytes32 c1, bytes32 c2) internal pure returns (bytes32[] memory caps) {
        caps = new bytes32[](2);
        caps[0] = c1;
        caps[1] = c2;
    }

    function _runTask(bytes32 taskId, bool verified) internal {
        vm.deal(creator, BUDGET);
        vm.prank(creator);
        taskManager.createTask{value: BUDGET}(
            taskId,
            _caps(CAP_TRADE, CAP_ANALYZE),
            BUDGET,
            bytes("work"),
            block.timestamp + 7 days
        );

        vm.prank(executorOwner);
        taskManager.submitBid(taskId, 40 ether);
        vm.prank(creator);
        taskManager.acceptBid(taskId, executorOwner);

        vm.prank(executorOwner);
        taskManager.completeTask(taskId, "0xresult", "0xproof");

        vm.prank(governor);
        taskManager.verifyTask(taskId, verified);

        if (verified) {
            vm.warp(block.timestamp + taskManager.DISPUTE_WINDOW() + 1);
            taskManager.settleTask(taskId);
        } else {
            vm.prank(creator);
            taskManager.withdrawEscrow(taskId);
        }
    }
}
