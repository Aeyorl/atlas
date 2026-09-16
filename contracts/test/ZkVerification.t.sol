// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {AgentRegistry} from "../core/AgentRegistry.sol";
import {SettlementEngine} from "../core/SettlementEngine.sol";
import {TaskManager} from "../core/TaskManager.sol";
import {IVerifier} from "../interfaces/IVerifier.sol";
import {ISettlementEngine} from "../interfaces/ISettlementEngine.sol";

/// @dev Mock Groth16-style verifier. Accepts a proof iff it is well-formed
///      for the simulated proof system (size + tag byte) and carries the
///      expected public-input shape — mirroring how a real Groth16 verifier
///      hard-codes its circuit's input layout. Statement-level task binding
///      is enforced by the engine (publicInputs[0] == taskId).
contract MockGroth16Verifier is IVerifier {
    function verifyProof(bytes calldata proof, uint256[] calldata publicInputs)
        external
        pure
        returns (bool valid)
    {
        if (proof.length < 96) return false;
        if (proof[0] != 0x07) return false; // Groth16 proof tag
        if (publicInputs.length != 2) return false; // [taskId, resultHash]
        if (publicInputs[0] == 0) return false;
        return true;
    }
}

/// @dev Staticcall-shape guard: a state-mutating verifier that deliberately
///      does NOT inherit IVerifier (so it compiles as nonpayable). Staticness
///      comes from the callsite, not the target: the engine invokes it via a
///      view-typed interface (STATICCALL), so its SSTORE must revert there.
contract StateChangingVerifier {
    uint256 public counter;

    function verifyProof(bytes calldata, uint256[] calldata) external returns (bool) {
        counter++; // mutates state — impossible from settle()'s STATICCALL
        return true;
    }
}

contract ZkVerificationTest is Test {
    AgentRegistry internal registry;
    SettlementEngine internal settlement;
    TaskManager internal taskManager;
    MockGroth16Verifier internal mockVerifier;

    address internal creator;
    address internal agentOwner;
    address internal governor;

    bytes32 internal constant TASK1 = keccak256("task-1");

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
        mockVerifier = new MockGroth16Verifier();

        bytes32[] memory caps = new bytes32[](1);
        caps[0] = bytes32("TRADE");
        vm.prank(agentOwner);
        registry.register(keccak256("agent-1"), "https://a.example/x.json", caps, agentOwner, 0);
    }

    // ────────────────────────────────
    //  Helpers
    // ────────────────────────────────

    function _caps() internal pure returns (bytes32[] memory caps) {
        caps = new bytes32[](1);
        caps[0] = bytes32("TRADE");
    }

    /// @dev Well-formed 96-byte "Groth16" proof with the tag byte.
    function _groth16Proof() internal pure returns (bytes memory p) {
        p = new bytes(96);
        p[0] = 0x07;
    }

    /// @dev The settlement payload for a proof over `taskId`:
    ///      abi.encode(proof, publicInputs) with publicInputs[0] = taskId.
    function _proofBlob(bytes32 taskId) internal pure returns (bytes memory) {
        uint256[] memory inputs = new uint256[](2);
        inputs[0] = uint256(taskId);
        inputs[1] = uint256(keccak256("result"));
        return abi.encode(_groth16Proof(), inputs);
    }

    /// @dev Runs a task through to Verifying (proof submitted at completion).
    function _runToVerifying(bytes32 taskId) internal {
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
        taskManager.completeTask(taskId, "0xresult", _proofBlob(taskId));
    }

    /// @dev Verify + advance past the dispute window + settle.
    function _settle(bytes32 taskId) internal {
        vm.prank(governor);
        taskManager.verifyTask(taskId, true);
        vm.warp(block.timestamp + 3 days + 1);
        taskManager.settleTask(taskId);
    }

    // ────────────────────────────────
    //  V1 mode: no verifier configured
    // ────────────────────────────────

    function test_V1Mode_SettleWithoutVerifierSucceeds() public {
        // setUp does not set a verifier — governor trust mode
        _runToVerifying(TASK1);
        _settle(TASK1);

        assertTrue(settlement.getSettlement(TASK1).settled);
        assertFalse(settlement.hasProofVerified(TASK1));
        assertEq(address(settlement.verifier()), address(0));
    }

    // ────────────────────────────────
    //  ZK-gated settlement
    // ────────────────────────────────

    function test_ZkGated_ValidProofSettles() public {
        vm.prank(governor);
        settlement.setVerifier(address(mockVerifier));

        _runToVerifying(TASK1);
        _settle(TASK1);

        assertTrue(settlement.getSettlement(TASK1).settled);
        assertTrue(settlement.hasProofVerified(TASK1));
        assertEq(address(settlement.verifier()), address(mockVerifier));
    }

    function test_ZkGated_AgentGetsPaidNetOfFee() public {
        vm.prank(governor);
        settlement.setVerifier(address(mockVerifier));

        _runToVerifying(TASK1);
        _settle(TASK1);

        // 6 ether fee, 2.5% protocol cut → agent nets 5.85 ether
        assertEq(agentOwner.balance, 5.85 ether);
        // settlement record reflects the same
        ISettlementEngine.Settlement memory s = settlement.getSettlement(TASK1);
        assertEq(s.agentFee, 5.85 ether);
        assertTrue(s.settled);
    }

    function test_ZkGated_InvalidProofRevertsAndPreservesEscrow() public {
        vm.prank(governor);
        settlement.setVerifier(address(mockVerifier));

        // Complete with a bad-tag proof (fails the mock's check)
        uint256[] memory inputs = new uint256[](2);
        inputs[0] = uint256(TASK1);
        inputs[1] = 1;
        bytes memory badProof = new bytes(96);
        badProof[0] = 0x08; // wrong tag

        vm.deal(creator, BUDGET);
        vm.prank(creator);
        taskManager.createTask{value: BUDGET}(TASK1, _caps(), BUDGET, "", block.timestamp + DEADLINE);
        vm.prank(agentOwner);
        taskManager.submitBid(TASK1, FEE);
        vm.prank(creator);
        taskManager.acceptBid(TASK1, agentOwner);
        vm.prank(agentOwner);
        taskManager.completeTask(TASK1, "0xresult", abi.encode(badProof, inputs));

        vm.prank(governor);
        taskManager.verifyTask(TASK1, true);
        vm.warp(block.timestamp + 3 days + 1);

        vm.expectRevert(SettlementEngine.SettlementEngine__InvalidProof.selector);
        taskManager.settleTask(TASK1);

        // Nothing moved: escrow intact, nothing settled, agent unpaid
        assertEq(settlement.getEscrow(TASK1), BUDGET);
        assertFalse(settlement.getSettlement(TASK1).settled);
        assertEq(agentOwner.balance, 0);
        assertFalse(settlement.hasProofVerified(TASK1));
    }

    function test_ZkGated_ProofForDifferentTaskReverts() public {
        vm.prank(governor);
        settlement.setVerifier(address(mockVerifier));

        // Agent submits a well-formed proof bound to a DIFFERENT task id —
        // the engine's publicInputs[0] check must reject it even though the
        // verifier itself would accept the shape.
        bytes32 otherTask = keccak256("some-other-task");
        vm.deal(creator, BUDGET);
        vm.prank(creator);
        taskManager.createTask{value: BUDGET}(TASK1, _caps(), BUDGET, "", block.timestamp + DEADLINE);
        vm.prank(agentOwner);
        taskManager.submitBid(TASK1, FEE);
        vm.prank(creator);
        taskManager.acceptBid(TASK1, agentOwner);
        vm.prank(agentOwner);
        taskManager.completeTask(TASK1, "0xresult", _proofBlob(otherTask));

        vm.prank(governor);
        taskManager.verifyTask(TASK1, true);
        vm.warp(block.timestamp + 3 days + 1);

        vm.expectRevert(SettlementEngine.SettlementEngine__ProofTaskMismatch.selector);
        taskManager.settleTask(TASK1);

        assertEq(settlement.getEscrow(TASK1), BUDGET);
    }

    function test_ZkGated_EmptyVerificationReverts() public {
        vm.prank(governor);
        settlement.setVerifier(address(mockVerifier));

        // Agent completes without a proof payload
        vm.deal(creator, BUDGET);
        vm.prank(creator);
        taskManager.createTask{value: BUDGET}(TASK1, _caps(), BUDGET, "", block.timestamp + DEADLINE);
        vm.prank(agentOwner);
        taskManager.submitBid(TASK1, FEE);
        vm.prank(creator);
        taskManager.acceptBid(TASK1, agentOwner);
        vm.prank(agentOwner);
        taskManager.completeTask(TASK1, "0xresult", "");

        vm.prank(governor);
        taskManager.verifyTask(TASK1, true);
        vm.warp(block.timestamp + 3 days + 1);

        vm.expectRevert(SettlementEngine.SettlementEngine__VerificationPayloadMalformed.selector);
        taskManager.settleTask(TASK1);
    }

    function test_ZkGated_DisputeResolutionAlsoGated() public {
        vm.prank(governor);
        settlement.setVerifier(address(mockVerifier));

        _runToVerifying(TASK1);

        // Creator challenges the verified result, governor resolves in the
        // agent's favor — the settle path is the same, so the proof gate
        // applies here too.
        vm.prank(governor);
        taskManager.verifyTask(TASK1, true);
        vm.prank(creator);
        taskManager.disputeTask(TASK1, "evidence");

        vm.prank(governor);
        taskManager.resolveDispute(TASK1, true);

        assertTrue(settlement.getSettlement(TASK1).settled);
        assertTrue(settlement.hasProofVerified(TASK1));
    }

    // ────────────────────────────────
    //  Admin
    // ────────────────────────────────

    function test_Admin_SetVerifierOnlyGovernor() public {
        vm.prank(creator);
        vm.expectRevert(SettlementEngine.SettlementEngine__NotGovernor.selector);
        settlement.setVerifier(address(mockVerifier));
    }

    function test_Admin_ZeroAddressDisablesEnforcement() public {
        vm.startPrank(governor);
        settlement.setVerifier(address(mockVerifier));
        settlement.setVerifier(address(0));
        vm.stopPrank();

        _runToVerifying(TASK1);
        _settle(TASK1);

        assertTrue(settlement.getSettlement(TASK1).settled);
        assertFalse(settlement.hasProofVerified(TASK1));
    }

    // ────────────────────────────────
    //  Verifier call safety
    // ────────────────────────────────

    function test_Verifier_CalledViaStaticcallCannotMutateState() public {
        StateChangingVerifier stateful = new StateChangingVerifier();
        vm.prank(governor);
        settlement.setVerifier(address(stateful));

        _runToVerifying(TASK1);

        // Sanity: outside a static frame the verifier works fine (counter → 1)
        assertTrue(stateful.verifyProof(hex"", new uint256[](0)));

        // settle() invokes the verifier through a view-typed interface
        // (STATICCALL); the state-mutating SSTORE must revert the whole settle.
        vm.prank(governor);
        taskManager.verifyTask(TASK1, true);
        vm.warp(block.timestamp + 3 days + 1);

        vm.expectRevert();
        taskManager.settleTask(TASK1);

        // Counter unchanged by the failed settle — still 1 from the sanity call
        assertEq(stateful.counter(), 1);
        assertEq(settlement.getEscrow(TASK1), BUDGET);
    }

    // ────────────────────────────────
    //  Queries
    // ────────────────────────────────

    function test_GetProof_ReturnsStoredBlob() public {
        bytes memory blob = _proofBlob(TASK1);
        _runToVerifying(TASK1);

        bytes memory stored = taskManager.getProof(TASK1);
        assertEq(stored.length, blob.length);
        assertEq(keccak256(stored), keccak256(blob));
    }
}
