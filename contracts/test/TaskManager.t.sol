// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {AgentRegistry} from "../../contracts/core/AgentRegistry.sol";
import {TaskManager} from "../../contracts/core/TaskManager.sol";
import {SettlementEngine} from "../../contracts/core/SettlementEngine.sol";
import {ITaskManager} from "../../contracts/interfaces/ITaskManager.sol";
import {IAgentRegistry} from "../../contracts/interfaces/IAgentRegistry.sol";

contract TaskManagerTest is Test {
    AgentRegistry internal registry;
    SettlementEngine internal settlement;
    TaskManager internal taskManager;

    address internal creator;
    address internal agentOwner;
    address internal governor;

    bytes32 internal constant TASK1 = keccak256("task-1");
    bytes32 internal constant TASK2 = keccak256("task-2");
    bytes32 internal constant AGENT1 = keccak256("agent-1");
    bytes32 internal constant AGENT2 = keccak256("agent-2");

    bytes32 internal constant CAP_TRADE = bytes32("TRADE");
    bytes32 internal constant CAP_ANALYZE = bytes32("ANALYZE");

    string internal constant URI = "https://agent.example/meta.json";

    uint256 internal constant BUDGET = 10 ether;
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

        bytes32[] memory caps = new bytes32[](2);
        caps[0] = CAP_TRADE;
        caps[1] = CAP_ANALYZE;
        vm.prank(agentOwner);
        registry.register(AGENT1, URI, caps, agentOwner, 0);
    }

    // ────────────────────────────────
    //  Helpers
    // ────────────────────────────────

    function _defaultCaps() internal pure returns (bytes32[] memory caps) {
        caps = new bytes32[](1);
        caps[0] = CAP_TRADE;
    }

    function _createTask(bytes32 taskId) internal returns (ITaskManager.Task memory) {
        vm.deal(creator, BUDGET);
        vm.prank(creator);
        return taskManager.createTask{value: BUDGET}(
            taskId, _defaultCaps(), BUDGET, bytes("params"), block.timestamp + DEADLINE
        );
    }

    function _bid(bytes32 taskId, uint256 fee) internal {
        vm.prank(agentOwner);
        taskManager.submitBid(taskId, fee);
    }

    function _accept(bytes32 taskId, address agent) internal {
        vm.prank(creator);
        taskManager.acceptBid(taskId, agent);
    }

    // ────────────────────────────────
    //  Task creation
    // ────────────────────────────────

    function test_CreateTask_StoresTaskAndEscrow() public {
        _createTask(TASK1);

        ITaskManager.Task memory t = taskManager.getTask(TASK1);
        assertEq(t.taskId, TASK1);
        assertEq(t.creator, creator);
        assertEq(t.budget, BUDGET);
        assertEq(t.requiredCapabilities.length, 1);
        assertEq(uint256(t.status), uint256(ITaskManager.TaskStatus.Bidding));
        assertEq(taskManager.getEscrow(TASK1), BUDGET);
        assertEq(address(settlement).balance, BUDGET); // custodied by the engine
        assertEq(address(taskManager).balance, 0);
        assertEq(taskManager.getTaskCount(), 1);
    }

    function test_CreateTask_ZeroTaskIdReverts() public {
        vm.deal(creator, BUDGET);
        vm.prank(creator);
        vm.expectRevert(TaskManager.TaskManager__ZeroTaskId.selector);
        taskManager.createTask{value: BUDGET}(bytes32(0), _defaultCaps(), BUDGET, "", block.timestamp + 1);
    }

    function test_CreateTask_DuplicateIdReverts() public {
        _createTask(TASK1);
        vm.deal(creator, BUDGET);
        vm.prank(creator);
        vm.expectRevert(TaskManager.TaskManager__TaskExists.selector);
        taskManager.createTask{value: BUDGET}(TASK1, _defaultCaps(), BUDGET, "", block.timestamp + 1);
    }

    function test_CreateTask_ZeroEscrowReverts() public {
        vm.deal(creator, BUDGET);
        vm.prank(creator);
        vm.expectRevert(TaskManager.TaskManager__ZeroEscrow.selector);
        taskManager.createTask{value: 0}(TASK1, _defaultCaps(), BUDGET, "", block.timestamp + 1);
    }

    function test_CreateTask_BudgetMismatchReverts() public {
        vm.deal(creator, BUDGET);
        vm.prank(creator);
        vm.expectRevert(TaskManager.TaskManager__BudgetMismatch.selector);
        taskManager.createTask{value: BUDGET - 1}(TASK1, _defaultCaps(), BUDGET, "", block.timestamp + 1);
    }

    function test_CreateTask_NoCapabilitiesReverts() public {
        vm.deal(creator, BUDGET);
        vm.prank(creator);
        vm.expectRevert(TaskManager.TaskManager__NoRequiredCapabilities.selector);
        taskManager.createTask{value: BUDGET}(TASK1, new bytes32[](0), BUDGET, "", block.timestamp + 1);
    }

    function test_CreateTask_DeadlineInPastReverts() public {
        vm.deal(creator, BUDGET);
        vm.prank(creator);
        vm.expectRevert(TaskManager.TaskManager__DeadlineInPast.selector);
        taskManager.createTask{value: BUDGET}(TASK1, _defaultCaps(), BUDGET, "", block.timestamp - 1);
    }

    // ────────────────────────────────
    //  Bidding
    // ────────────────────────────────

    function test_SubmitBid_CapableAgent() public {
        _createTask(TASK1);
        _bid(TASK1, 6 ether);

        ITaskManager.Bid[] memory bids = taskManager.getBids(TASK1);
        assertEq(bids.length, 1);
        assertEq(bids[0].bidder, agentOwner);
        assertEq(bids[0].fee, 6 ether);
        assertEq(uint256(bids[0].status), uint256(ITaskManager.BidStatus.Pending));
        assertEq(taskManager.getBidAgentId(TASK1, agentOwner), AGENT1);
    }

    function test_SubmitBid_UnknownTaskReverts() public {
        vm.prank(agentOwner);
        vm.expectRevert(TaskManager.TaskManager__UnknownTask.selector);
        taskManager.submitBid(TASK1, 1 ether);
    }

    function test_SubmitBid_FeeExceedsBudgetReverts() public {
        _createTask(TASK1);
        vm.prank(agentOwner);
        vm.expectRevert(TaskManager.TaskManager__FeeExceedsBudget.selector);
        taskManager.submitBid(TASK1, BUDGET + 1);
    }

    function test_SubmitBid_DuplicateBidReverts() public {
        _createTask(TASK1);
        _bid(TASK1, 6 ether);
        vm.prank(agentOwner);
        vm.expectRevert(TaskManager.TaskManager__DuplicateBid.selector);
        taskManager.submitBid(TASK1, 5 ether);
    }

    function test_SubmitBid_NotCapableAgentReverts() public {
        _createTask(TASK1);

        // agent without the TRADE capability
        bytes32[] memory caps = new bytes32[](1);
        caps[0] = CAP_ANALYZE;
        vm.prank(creator);
        registry.register(AGENT2, URI, caps, creator, 0);

        vm.prank(creator);
        vm.expectRevert(TaskManager.TaskManager__NoCapableAgent.selector);
        taskManager.submitBid(TASK1, 1 ether);
    }

    function test_SubmitBid_AmbiguousAgentReverts() public {
        _createTask(TASK1);

        // second active agent owned by the same address with the same capability
        vm.prank(agentOwner);
        registry.register(AGENT2, URI, _defaultCaps(), agentOwner, 0);

        vm.prank(agentOwner);
        vm.expectRevert(TaskManager.TaskManager__AmbiguousAgent.selector);
        taskManager.submitBid(TASK1, 1 ether);
    }

    function test_SubmitBid_DeadlinePassedReverts() public {
        _createTask(TASK1);
        vm.warp(block.timestamp + DEADLINE + 1);
        vm.prank(agentOwner);
        vm.expectRevert(TaskManager.TaskManager__DeadlinePassed.selector);
        taskManager.submitBid(TASK1, 1 ether);
    }

    // ────────────────────────────────
    //  Bid acceptance
    // ────────────────────────────────

    function test_AcceptBid_SetsExecutingAndRejectsOthers() public {
        _createTask(TASK1);

        // second bidder
        address otherOwner = makeAddr("otherOwner");
        bytes32 agent3 = keccak256("agent-3");
        vm.prank(otherOwner);
        registry.register(agent3, URI, _defaultCaps(), otherOwner, 0);

        _bid(TASK1, 6 ether);
        vm.prank(otherOwner);
        taskManager.submitBid(TASK1, 7 ether);

        _accept(TASK1, agentOwner);

        ITaskManager.Task memory t = taskManager.getTask(TASK1);
        assertEq(t.assignedAgent, agentOwner);
        assertEq(uint256(t.status), uint256(ITaskManager.TaskStatus.Executing));

        ITaskManager.Bid[] memory bids = taskManager.getBids(TASK1);
        assertEq(uint256(bids[0].status), uint256(ITaskManager.BidStatus.Accepted));
        assertEq(uint256(bids[1].status), uint256(ITaskManager.BidStatus.Rejected));
    }

    function test_AcceptBid_OnlyCreatorOrGovernor() public {
        _createTask(TASK1);
        _bid(TASK1, 6 ether);

        vm.prank(agentOwner);
        vm.expectRevert(TaskManager.TaskManager__NotCreator.selector);
        taskManager.acceptBid(TASK1, agentOwner);
    }

    function test_AcceptBid_GovernorCanAccept() public {
        _createTask(TASK1);
        _bid(TASK1, 6 ether);

        vm.prank(governor);
        taskManager.acceptBid(TASK1, agentOwner);
        assertEq(taskManager.getTask(TASK1).assignedAgent, agentOwner);
    }

    function test_AcceptBid_UnknownBidReverts() public {
        _createTask(TASK1);
        vm.prank(creator);
        vm.expectRevert(TaskManager.TaskManager__BidNotFound.selector);
        taskManager.acceptBid(TASK1, agentOwner);
    }

    // ────────────────────────────────
    //  Execution & verification
    // ────────────────────────────────

    function test_CompleteTask_OnlyAssignedAgent() public {
        _createTask(TASK1);
        _bid(TASK1, 6 ether);
        _accept(TASK1, agentOwner);

        vm.prank(creator);
        vm.expectRevert(TaskManager.TaskManager__NotAssignedAgent.selector);
        taskManager.completeTask(TASK1, "result", "proof");
    }

    function test_CompleteTask_MovesToVerifying() public {
        _createTask(TASK1);
        _bid(TASK1, 6 ether);
        _accept(TASK1, agentOwner);

        vm.prank(agentOwner);
        taskManager.completeTask(TASK1, "result", "proof");

        assertEq(
            uint256(taskManager.getTask(TASK1).status),
            uint256(ITaskManager.TaskStatus.Verifying)
        );
    }

    function test_CompleteTask_DeadlinePassedReverts() public {
        _createTask(TASK1);
        _bid(TASK1, 6 ether);
        _accept(TASK1, agentOwner);
        vm.warp(block.timestamp + DEADLINE + 1);

        vm.prank(agentOwner);
        vm.expectRevert(TaskManager.TaskManager__DeadlinePassed.selector);
        taskManager.completeTask(TASK1, "result", "proof");
    }

    function test_VerifyTask_OnlyGovernor() public {
        _createTask(TASK1);
        _bid(TASK1, 6 ether);
        _accept(TASK1, agentOwner);
        vm.prank(agentOwner);
        taskManager.completeTask(TASK1, "result", "proof");

        vm.prank(creator);
        vm.expectRevert(TaskManager.TaskManager__NotGovernor.selector);
        taskManager.verifyTask(TASK1, true);
    }

    function test_VerifyTask_Rejected_FailsTaskAndRecordsReputation() public {
        _createTask(TASK1);
        _bid(TASK1, 6 ether);
        _accept(TASK1, agentOwner);
        vm.prank(agentOwner);
        taskManager.completeTask(TASK1, "result", "proof");

        vm.prank(governor);
        taskManager.verifyTask(TASK1, false);

        assertEq(
            uint256(taskManager.getTask(TASK1).status),
            uint256(ITaskManager.TaskStatus.Failed)
        );

        IAgentRegistry.AgentRecord memory r = registry.getAgent(AGENT1);
        assertEq(r.totalTasks, 1);
        assertEq(r.successfulTasks, 0);
    }

    // ────────────────────────────────
    //  Settlement
    // ────────────────────────────────

    function test_SettleTask_PaysAgentProtocolAndRefundsCreator() public {
        _createTask(TASK1);
        _bid(TASK1, 6 ether);
        _accept(TASK1, agentOwner);
        vm.prank(agentOwner);
        taskManager.completeTask(TASK1, "result", "proof");
        vm.prank(governor);
        taskManager.verifyTask(TASK1, true);

        // dispute window still open
        vm.prank(governor);
        vm.expectRevert(TaskManager.TaskManager__DisputeWindowOpen.selector);
        taskManager.settleTask(TASK1);

        vm.warp(block.timestamp + taskManager.DISPUTE_WINDOW() + 1);

        uint256 agentBefore = agentOwner.balance;
        uint256 governorBefore = governor.balance;
        uint256 creatorBefore = creator.balance;

        taskManager.settleTask(TASK1);

        // fee 6 ether, protocol cut 2.5% = 0.15 ether
        assertEq(agentOwner.balance - agentBefore, 5.85 ether);
        assertEq(governor.balance - governorBefore, 0.15 ether);
        assertEq(creator.balance - creatorBefore, 4 ether);

        ITaskManager.Task memory t = taskManager.getTask(TASK1);
        assertEq(uint256(t.status), uint256(ITaskManager.TaskStatus.Completed));
        assertEq(taskManager.getEscrow(TASK1), 0);
        assertEq(address(settlement).balance, 0);

        IAgentRegistry.AgentRecord memory r = registry.getAgent(AGENT1);
        assertEq(r.totalTasks, 1);
        assertEq(r.successfulTasks, 1);
    }

    function test_SettleTask_DoubleSettleReverts() public {
        _createTask(TASK1);
        _bid(TASK1, 6 ether);
        _accept(TASK1, agentOwner);
        vm.prank(agentOwner);
        taskManager.completeTask(TASK1, "result", "proof");
        vm.prank(governor);
        taskManager.verifyTask(TASK1, true);
        vm.warp(block.timestamp + taskManager.DISPUTE_WINDOW() + 1);

        taskManager.settleTask(TASK1);
        vm.expectRevert(TaskManager.TaskManager__NotVerifying.selector);
        taskManager.settleTask(TASK1);
    }

    function test_WithdrawEscrow_AfterFailure() public {
        _createTask(TASK1);
        _bid(TASK1, 6 ether);
        _accept(TASK1, agentOwner);
        vm.prank(agentOwner);
        taskManager.completeTask(TASK1, "result", "proof");
        vm.prank(governor);
        taskManager.verifyTask(TASK1, false);

        uint256 before = creator.balance;
        vm.prank(creator);
        taskManager.withdrawEscrow(TASK1);
        assertEq(creator.balance - before, BUDGET);
        assertEq(taskManager.getEscrow(TASK1), 0);
        assertEq(address(settlement).balance, 0);
    }

    function test_WithdrawEscrow_OnlyCreator() public {
        _createTask(TASK1);
        _bid(TASK1, 6 ether);
        _accept(TASK1, agentOwner);
        vm.prank(agentOwner);
        taskManager.completeTask(TASK1, "result", "proof");
        vm.prank(governor);
        taskManager.verifyTask(TASK1, false);

        vm.prank(agentOwner);
        vm.expectRevert(TaskManager.TaskManager__NotCreator.selector);
        taskManager.withdrawEscrow(TASK1);
    }

    // ────────────────────────────────
    //  Disputes
    // ────────────────────────────────

    function test_DisputeTask_WithinWindow() public {
        _createTask(TASK1);
        _bid(TASK1, 6 ether);
        _accept(TASK1, agentOwner);
        vm.prank(agentOwner);
        taskManager.completeTask(TASK1, "result", "proof");
        vm.prank(governor);
        taskManager.verifyTask(TASK1, true);

        vm.prank(creator);
        taskManager.disputeTask(TASK1, "evidence");

        assertEq(
            uint256(taskManager.getTask(TASK1).status),
            uint256(ITaskManager.TaskStatus.Disputed)
        );
    }

    function test_DisputeTask_AfterWindowReverts() public {
        _createTask(TASK1);
        _bid(TASK1, 6 ether);
        _accept(TASK1, agentOwner);
        vm.prank(agentOwner);
        taskManager.completeTask(TASK1, "result", "proof");
        vm.prank(governor);
        taskManager.verifyTask(TASK1, true);

        vm.warp(block.timestamp + taskManager.DISPUTE_WINDOW() + 1);
        vm.prank(creator);
        vm.expectRevert(TaskManager.TaskManager__DisputeWindowClosed.selector);
        taskManager.disputeTask(TASK1, "evidence");
    }

    function test_DisputeTask_OnlyCreator() public {
        _createTask(TASK1);
        _bid(TASK1, 6 ether);
        _accept(TASK1, agentOwner);
        vm.prank(agentOwner);
        taskManager.completeTask(TASK1, "result", "proof");
        vm.prank(governor);
        taskManager.verifyTask(TASK1, true);

        vm.prank(agentOwner);
        vm.expectRevert(TaskManager.TaskManager__NotCreator.selector);
        taskManager.disputeTask(TASK1, "evidence");
    }

    function test_ResolveDispute_AgentWins_Settles() public {
        _createTask(TASK1);
        _bid(TASK1, 6 ether);
        _accept(TASK1, agentOwner);
        vm.prank(agentOwner);
        taskManager.completeTask(TASK1, "result", "proof");
        vm.prank(governor);
        taskManager.verifyTask(TASK1, true);
        vm.prank(creator);
        taskManager.disputeTask(TASK1, "evidence");

        vm.prank(governor);
        taskManager.resolveDispute(TASK1, true);

        ITaskManager.Task memory t = taskManager.getTask(TASK1);
        assertEq(uint256(t.status), uint256(ITaskManager.TaskStatus.Completed));
        assertEq(taskManager.getEscrow(TASK1), 0);
    }

    function test_ResolveDispute_CreatorWins_RefundsAndFails() public {
        _createTask(TASK1);
        _bid(TASK1, 6 ether);
        _accept(TASK1, agentOwner);
        vm.prank(agentOwner);
        taskManager.completeTask(TASK1, "result", "proof");
        vm.prank(governor);
        taskManager.verifyTask(TASK1, true);
        vm.prank(creator);
        taskManager.disputeTask(TASK1, "evidence");

        uint256 creatorBefore = creator.balance;
        vm.prank(governor);
        taskManager.resolveDispute(TASK1, false);

        ITaskManager.Task memory t = taskManager.getTask(TASK1);
        assertEq(uint256(t.status), uint256(ITaskManager.TaskStatus.Failed));
        assertEq(creator.balance - creatorBefore, BUDGET);
        assertEq(taskManager.getEscrow(TASK1), 0);

        IAgentRegistry.AgentRecord memory r = registry.getAgent(AGENT1);
        assertEq(r.totalTasks, 1);
        assertEq(r.successfulTasks, 0);
    }

    // ────────────────────────────────
    //  Admin
    // ────────────────────────────────

    function test_SetProtocolFeeBps_OnlyGovernor() public {
        vm.prank(creator);
        vm.expectRevert(TaskManager.TaskManager__NotGovernor.selector);
        taskManager.setProtocolFeeBps(100);

        vm.prank(governor);
        taskManager.setProtocolFeeBps(100);
        assertEq(taskManager.protocolFeeBps(), 100);
    }

    function test_SetProtocolFeeBps_TooHighReverts() public {
        uint256 tooHigh = taskManager.MAX_PROTOCOL_FEE_BPS() + 1;
        vm.prank(governor);
        vm.expectRevert(TaskManager.TaskManager__FeeTooHigh.selector);
        taskManager.setProtocolFeeBps(tooHigh);
    }

    function test_SetGovernor_Rotates() public {
        address newGovernor = makeAddr("newGovernor");
        vm.prank(governor);
        taskManager.setGovernor(newGovernor);

        vm.prank(newGovernor);
        taskManager.setProtocolFeeBps(100);
        assertEq(taskManager.protocolFeeBps(), 100);
    }
}
