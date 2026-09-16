// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {AgentRegistry} from "../core/AgentRegistry.sol";
import {SettlementEngine} from "../core/SettlementEngine.sol";
import {TaskManager} from "../core/TaskManager.sol";
import {ITaskManager} from "../interfaces/ITaskManager.sol";
import {ISettlementEngine} from "../interfaces/ISettlementEngine.sol";

contract SettlementEngineTest is Test {
    AgentRegistry internal registry;
    SettlementEngine internal settlement;
    TaskManager internal taskManager;

    address internal creator;
    address internal agentOwner;
    address internal governor;
    address internal guardianVault;
    address internal stranger;

    bytes32 internal constant TASK1 = keccak256("task-1");
    bytes32 internal constant AGENT1 = keccak256("agent-1");

    bytes32 internal constant CAP_TRADE = bytes32("TRADE");

    string internal constant URI = "https://agent.example/meta.json";

    uint256 internal constant BUDGET = 10 ether;
    uint256 internal constant FEE = 6 ether;
    uint256 internal constant DEADLINE = 7 days;

    function setUp() public {
        registry = new AgentRegistry();
        governor = makeAddr("governor");
        settlement = new SettlementEngine(governor);
        taskManager = new TaskManager(address(registry), address(settlement), governor);
        registry.setTaskManager(address(taskManager));
        vm.prank(governor);
        settlement.setTaskManager(address(taskManager));

        creator = makeAddr("creator");
        agentOwner = makeAddr("agentOwner");
        guardianVault = makeAddr("guardianVault");
        stranger = makeAddr("stranger");

        bytes32[] memory caps = new bytes32[](1);
        caps[0] = CAP_TRADE;
        vm.prank(agentOwner);
        registry.register(AGENT1, URI, caps, agentOwner, 0);
    }

    // ────────────────────────────────
    //  Helpers
    // ────────────────────────────────

    function _caps() internal pure returns (bytes32[] memory caps) {
        caps = new bytes32[](1);
        caps[0] = CAP_TRADE;
    }

    /// @dev Runs a task through to the Verified state (dispute window running).
    function _runToVerified(bytes32 taskId) internal {
        vm.deal(creator, BUDGET);
        vm.prank(creator);
        taskManager.createTask{value: BUDGET}(
            taskId, _caps(), BUDGET, bytes("params"), block.timestamp + DEADLINE
        );
        vm.prank(agentOwner);
        taskManager.submitBid(taskId, FEE);
        vm.prank(creator);
        taskManager.acceptBid(taskId, agentOwner);
        vm.prank(agentOwner);
        taskManager.completeTask(taskId, "0xresult", "0xproof");
        vm.prank(governor);
        taskManager.verifyTask(taskId, true);
    }

    /// @dev Runs a task through to the Failed state (verification rejected).
    function _runToFailed(bytes32 taskId) internal {
        _runToVerified(taskId);
        vm.prank(governor);
        taskManager.verifyTask(taskId, false);
    }

    // ────────────────────────────────
    //  Escrow custody
    // ────────────────────────────────

    function test_DepositEscrow_ForwardedFromTaskCreation() public {
        _runToVerified(TASK1);

        assertEq(settlement.getEscrow(TASK1), BUDGET);
        assertEq(address(settlement).balance, BUDGET);
        assertEq(address(taskManager).balance, 0);
        assertEq(creator.balance, 0);
    }

    function test_DepositEscrow_RevertNotTaskManager() public {
        vm.expectRevert(SettlementEngine.SettlementEngine__NotTaskManager.selector);
        settlement.depositEscrow{value: 1 ether}(TASK1);
    }

    function test_DepositEscrow_RevertZeroAmount() public {
        vm.prank(address(taskManager));
        vm.expectRevert(SettlementEngine.SettlementEngine__ZeroAmount.selector);
        settlement.depositEscrow(TASK1);
    }

    function test_DepositEscrow_RevertAlreadyFunded() public {
        vm.deal(creator, BUDGET);
        vm.prank(creator);
        taskManager.createTask{value: BUDGET}(TASK1, _caps(), BUDGET, "", block.timestamp + DEADLINE);

        // A second createTask with the same id reverts at the TaskManager, so
        // simulate the raw re-deposit from the (trusted) TaskManager directly.
        vm.deal(address(taskManager), 1 ether);
        vm.prank(address(taskManager));
        vm.expectRevert(SettlementEngine.SettlementEngine__AlreadyFunded.selector);
        settlement.depositEscrow{value: 1 ether}(TASK1);
    }

    // ────────────────────────────────
    //  Settlement & fee split
    // ────────────────────────────────

    function test_Settle_PaysAgentProtocolAndRefundsCreator() public {
        _runToVerified(TASK1);
        vm.warp(block.timestamp + taskManager.DISPUTE_WINDOW() + 1);

        uint256 agentBefore = agentOwner.balance;
        uint256 governorBefore = governor.balance;
        uint256 creatorBefore = creator.balance;

        taskManager.settleTask(TASK1);

        // 6 ether fee, 2.5% protocol fee
        assertEq(agentOwner.balance - agentBefore, 5.85 ether);
        assertEq(governor.balance - governorBefore, 0.15 ether);
        assertEq(creator.balance - creatorBefore, 4 ether); // unspent budget
        assertEq(address(settlement).balance, 0);
        assertEq(settlement.getEscrow(TASK1), 0);

        ISettlementEngine.Settlement memory s = settlement.getSettlement(TASK1);
        assertTrue(s.settled);
        assertEq(s.taskId, TASK1);
        assertEq(s.agent, agentOwner);
        assertEq(s.creator, creator);
        assertEq(s.agentFee, 5.85 ether);
        assertEq(s.protocolFee, 0.15 ether);
        assertEq(s.guardianFee, 0);
    }

    function test_Settle_SplitsFeeWithGuardianTreasury() public {
        vm.prank(governor);
        settlement.setGuardianTreasury(guardianVault);
        vm.prank(governor);
        settlement.setGuardianShareBps(4_000); // 40% of protocol cut to guardians

        _runToVerified(TASK1);
        vm.warp(block.timestamp + taskManager.DISPUTE_WINDOW() + 1);
        taskManager.settleTask(TASK1);

        uint256 protocolCut = 0.15 ether; // 2.5% of 6
        uint256 guardianCut = 0.06 ether; // 40% of protocol cut
        uint256 protocolNet = 0.09 ether;

        assertEq(agentOwner.balance, 5.85 ether);
        assertEq(guardianVault.balance, guardianCut);
        assertEq(governor.balance, protocolNet);

        ISettlementEngine.Settlement memory s = settlement.getSettlement(TASK1);
        assertEq(s.guardianFee, guardianCut);
        assertEq(s.protocolFee, protocolNet);
    }

    function test_Settle_RevertNotTaskManager() public {
        vm.expectRevert(SettlementEngine.SettlementEngine__NotTaskManager.selector);
        settlement.settle(TASK1, "");
    }

    function test_Settle_RevertUnknownOrEmptyEscrow() public {
        // Known task, no escrow: run a task to failure so it exists on both
        // contracts, then the creator withdraws the refund.
        _runToFailed(TASK1);
        vm.prank(creator);
        taskManager.withdrawEscrow(TASK1);

        vm.prank(address(taskManager));
        vm.expectRevert(SettlementEngine.SettlementEngine__UnknownOrEmptyEscrow.selector);
        settlement.settle(TASK1, "");
    }

    function test_Settle_RevertAlreadySettled() public {
        _runToVerified(TASK1);
        vm.warp(block.timestamp + taskManager.DISPUTE_WINDOW() + 1);
        taskManager.settleTask(TASK1);

        // Second settleTask reverts at the TaskManager (not Verifying), so
        // exercise the engine guard directly from the (trusted) TaskManager.
        vm.prank(address(taskManager));
        vm.expectRevert(SettlementEngine.SettlementEngine__AlreadySettled.selector);
        settlement.settle(TASK1, "");
    }

    // ────────────────────────────────
    //  Creator refunds
    // ────────────────────────────────

    function test_RefundCreator_AfterFailedTask() public {
        _runToFailed(TASK1);

        uint256 before = creator.balance;
        assertEq(settlement.getEscrow(TASK1), BUDGET);

        vm.prank(creator);
        taskManager.withdrawEscrow(TASK1);

        assertEq(creator.balance - before, BUDGET);
        assertEq(settlement.getEscrow(TASK1), 0);
        assertEq(address(settlement).balance, 0);
    }

    function test_RefundCreator_RevertNotTaskManager() public {
        vm.expectRevert(SettlementEngine.SettlementEngine__NotTaskManager.selector);
        settlement.refundCreator(TASK1);
    }

    function test_RefundCreator_RevertEmptyEscrow() public {
        _runToFailed(TASK1);
        vm.prank(creator);
        taskManager.withdrawEscrow(TASK1);

        vm.prank(address(taskManager));
        vm.expectRevert(SettlementEngine.SettlementEngine__UnknownOrEmptyEscrow.selector);
        settlement.refundCreator(TASK1);
    }

    function test_RefundCreator_RevertEmptyEscrow_UnknownTask() public {
        vm.prank(address(taskManager));
        vm.expectRevert(SettlementEngine.SettlementEngine__UnknownOrEmptyEscrow.selector);
        settlement.refundCreator(keccak256("never-created"));
    }

    // ────────────────────────────────
    //  Bonds
    // ────────────────────────────────

    function test_PostBond_Accumulates() public {
        vm.deal(agentOwner, 2 ether);
        vm.startPrank(agentOwner);
        settlement.postBond{value: 1 ether}(TASK1);
        settlement.postBond{value: 0.5 ether}(TASK1);
        vm.stopPrank();

        assertEq(settlement.getBond(TASK1, agentOwner), 1.5 ether);
        assertEq(address(settlement).balance, 1.5 ether);
    }

    function test_PostBond_RevertZeroAmount() public {
        vm.expectRevert(SettlementEngine.SettlementEngine__ZeroAmount.selector);
        settlement.postBond(TASK1);
    }

    function test_Settle_AutoReleasesBondToAssignedAgent() public {
        vm.deal(agentOwner, 1 ether);
        vm.prank(agentOwner);
        settlement.postBond{value: 1 ether}(TASK1);

        _runToVerified(TASK1);
        vm.warp(block.timestamp + taskManager.DISPUTE_WINDOW() + 1);

        uint256 agentBefore = agentOwner.balance;
        taskManager.settleTask(TASK1);

        // 5.85 agent fee + 1 bond release
        assertEq(agentOwner.balance - agentBefore, 6.85 ether);
        assertEq(settlement.getBond(TASK1, agentOwner), 0);
        assertEq(address(settlement).balance, 0);
    }

    function test_WithdrawBond_AfterFailedTask() public {
        vm.deal(agentOwner, 1 ether);
        vm.prank(agentOwner);
        settlement.postBond{value: 1 ether}(TASK1);

        _runToFailed(TASK1);
        vm.prank(creator);
        taskManager.withdrawEscrow(TASK1);

        uint256 before = agentOwner.balance;
        vm.prank(agentOwner);
        settlement.withdrawBond(TASK1);

        assertEq(agentOwner.balance - before, 1 ether);
        assertEq(settlement.getBond(TASK1, agentOwner), 0);
    }

    function test_WithdrawBond_RevertTaskNotTerminal() public {
        vm.deal(agentOwner, 1 ether);
        vm.prank(agentOwner);
        settlement.postBond{value: 1 ether}(TASK1);

        _runToVerified(TASK1); // Verifying — not settled, not refunded

        vm.prank(agentOwner);
        vm.expectRevert(SettlementEngine.SettlementEngine__TaskNotTerminal.selector);
        settlement.withdrawBond(TASK1);
    }

    function test_WithdrawBond_RevertNoBond() public {
        vm.expectRevert(SettlementEngine.SettlementEngine__NoBond.selector);
        settlement.withdrawBond(TASK1);
    }

    function test_WithdrawBond_RevertNotBonder() public {
        vm.deal(agentOwner, 1 ether);
        vm.prank(agentOwner);
        settlement.postBond{value: 1 ether}(TASK1);

        _runToFailed(TASK1);
        vm.prank(creator);
        taskManager.withdrawEscrow(TASK1);

        vm.prank(stranger);
        vm.expectRevert(SettlementEngine.SettlementEngine__NoBond.selector);
        settlement.withdrawBond(TASK1);
    }

    function test_WithdrawBond_ClaimableForNeverCreatedTask() public {
        bytes32 ghost = keccak256("ghost-task");
        vm.deal(stranger, 1 ether);
        vm.prank(stranger);
        settlement.postBond{value: 1 ether}(ghost);

        // Task was never created — no terminal state will ever arrive.
        uint256 before = stranger.balance;
        vm.prank(stranger);
        settlement.withdrawBond(ghost);

        assertEq(stranger.balance - before, 1 ether);
    }

    // ────────────────────────────────
    //  Slashing
    // ────────────────────────────────

    function test_Slash_PaysBondToTaskCreator() public {
        vm.deal(agentOwner, 2 ether);
        vm.prank(agentOwner);
        settlement.postBond{value: 2 ether}(TASK1);

        _runToFailed(TASK1);

        uint256 creatorBefore = creator.balance;
        vm.prank(governor);
        vm.expectEmit(true, false, false, true, address(settlement));
        emit ISettlementEngine.BondSlash(TASK1, agentOwner, 1 ether);
        settlement.slash(TASK1, agentOwner, 1 ether);

        assertEq(creator.balance - creatorBefore, 1 ether);
        assertEq(settlement.getBond(TASK1, agentOwner), 1 ether);
    }

    function test_Slash_ClampsToBondedAmount() public {
        vm.deal(agentOwner, 0.5 ether);
        vm.prank(agentOwner);
        settlement.postBond{value: 0.5 ether}(TASK1);

        _runToFailed(TASK1);

        uint256 creatorBefore = creator.balance;
        vm.prank(governor);
        settlement.slash(TASK1, agentOwner, 5 ether);

        assertEq(creator.balance - creatorBefore, 0.5 ether);
        assertEq(settlement.getBond(TASK1, agentOwner), 0);
    }

    function test_Slash_RevertNotGovernor() public {
        vm.expectRevert(SettlementEngine.SettlementEngine__NotGovernor.selector);
        settlement.slash(TASK1, agentOwner, 1 ether);
    }

    function test_Slash_RevertNoBond() public {
        _runToFailed(TASK1);

        vm.prank(governor);
        vm.expectRevert(SettlementEngine.SettlementEngine__NoBond.selector);
        settlement.slash(TASK1, agentOwner, 1 ether);
    }

    // ────────────────────────────────
    //  Admin
    // ────────────────────────────────

    function test_SetGuardianTreasury_Updates() public {
        vm.prank(governor);
        vm.expectEmit(true, true, false, false, address(settlement));
        emit SettlementEngine.GuardianTreasuryUpdated(address(0), guardianVault);
        settlement.setGuardianTreasury(guardianVault);

        assertEq(settlement.guardianTreasury(), guardianVault);
    }

    function test_SetGuardianShareBps_Bounded() public {
        vm.startPrank(governor);
        settlement.setGuardianShareBps(10_000); // max: whole protocol cut
        assertEq(settlement.guardianShareBps(), 10_000);

        vm.expectRevert(SettlementEngine.SettlementEngine__GuardianShareTooHigh.selector);
        settlement.setGuardianShareBps(10_001);
        vm.stopPrank();
    }

    function test_SetGuardianShareBps_RevertNotGovernor() public {
        vm.prank(stranger);
        vm.expectRevert(SettlementEngine.SettlementEngine__NotGovernor.selector);
        settlement.setGuardianShareBps(1_000);
    }

    function test_SetTaskManager_RevertNotGovernor() public {
        vm.prank(stranger);
        vm.expectRevert(SettlementEngine.SettlementEngine__NotGovernor.selector);
        settlement.setTaskManager(stranger);
    }

    function test_SetTaskManager_RevertZeroAddress() public {
        vm.prank(governor);
        vm.expectRevert(SettlementEngine.SettlementEngine__ZeroTaskManager.selector);
        settlement.setTaskManager(address(0));
    }

    function test_SetGovernor_RotatesAuthority() public {
        vm.prank(governor);
        settlement.setGovernor(stranger);
        assertEq(settlement.governor(), stranger);

        // Old governor loses authority...
        vm.prank(governor);
        vm.expectRevert(SettlementEngine.SettlementEngine__NotGovernor.selector);
        settlement.setGovernor(governor);

        // ...new governor gains it.
        vm.prank(stranger);
        settlement.setGovernor(governor);
    }

    function test_SetGovernor_RevertZeroAddress() public {
        vm.prank(governor);
        vm.expectRevert(SettlementEngine.SettlementEngine__ZeroGovernor.selector);
        settlement.setGovernor(address(0));
    }

    // ────────────────────────────────
    //  Dispute-path payouts via engine
    // ────────────────────────────────

    function test_ResolveDispute_AgentWins_SettlesViaEngine() public {
        _runToVerified(TASK1);
        vm.prank(creator);
        taskManager.disputeTask(TASK1, "evidence");

        uint256 agentBefore = agentOwner.balance;
        uint256 creatorBefore = creator.balance;

        vm.prank(governor);
        taskManager.resolveDispute(TASK1, true);

        assertEq(agentOwner.balance - agentBefore, 5.85 ether);
        assertEq(creator.balance - creatorBefore, 4 ether);
        assertTrue(settlement.getSettlement(TASK1).settled);
    }

    function test_ResolveDispute_CreatorWins_RefundsViaEngine() public {
        _runToVerified(TASK1);
        vm.prank(creator);
        taskManager.disputeTask(TASK1, "evidence");

        uint256 creatorBefore = creator.balance;

        vm.prank(governor);
        taskManager.resolveDispute(TASK1, false);

        assertEq(creator.balance - creatorBefore, BUDGET);
        assertEq(address(settlement).balance, 0);
        assertEq(settlement.getEscrow(TASK1), 0);
    }
}
