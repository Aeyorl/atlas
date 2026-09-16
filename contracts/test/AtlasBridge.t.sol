// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {AtlasBridge} from "../core/AtlasBridge.sol";
import {IAtlasBridge} from "../interfaces/IAtlasBridge.sol";

contract AtlasBridgeTest is Test {
    AtlasBridge internal bridge;
    address internal governor;
    address internal relayer;
    address internal app;
    address internal coreStub;

    // 5 guardians mirroring the AtlasCore committee default
    address[5] internal guardians;

    bytes32 constant ROBINHOOD = keccak256("robinhood-chain");
    bytes32 constant EVM = keccak256("evm");
    bytes32 constant VIRTUALS = keccak256("virtuals");
    bytes constant PAYLOAD = hex"deadbeef";

    function setUp() public {
        governor = makeAddr("governor");
        relayer = makeAddr("relayer");
        app = makeAddr("app");
        coreStub = address(new ActiveGuardianCoreStub());

        for (uint256 i = 0; i < 5; i++) {
            guardians[i] = makeAddr(string.concat("guardian", vm.toString(i)));
        }

        bridge = new AtlasBridge(EVM, governor);
        vm.prank(governor);
        bridge.setCore(coreStub);

        // Register the committee on the stub so exactly they attest
        for (uint256 i = 0; i < 5; i++) {
            ActiveGuardianCoreStub(coreStub).setMember(guardians[i]);
        }
    }

    // ────────────────────────────────
    //  Helpers
    // ────────────────────────────────

    /// @notice Send `PAYLOAD` from `source` (this caller's chain context) and
    ///         capture the provenance a relayer would observe.
    function _send(AtlasBridge source, bytes32 targetEcosystem, address sender)
        internal
        returns (bytes32 id, uint256 nonce, uint256 chainIdAtSend)
    {
        nonce = source.outboxCount();
        chainIdAtSend = block.chainid;
        vm.prank(sender);
        id = source.sendMessage(targetEcosystem, PAYLOAD);
    }

    function _deliver(
        AtlasBridge dest,
        bytes32 id,
        bytes32 sourceEcosystem,
        address sourceSender,
        uint256 sourceChainId,
        uint256 sourceNonce
    ) internal returns (bool ok) {
        bytes memory proof = abi.encode(sourceEcosystem, sourceSender, sourceChainId, sourceNonce);
        vm.prank(relayer);
        ok = dest.deliverMessage(id, PAYLOAD, proof);
    }

    /// @notice Governor + 2 committee guardians = quorum (2-of-5 + governor).
    function _reachQuorum(AtlasBridge b, bytes32 id) internal {
        vm.prank(governor);
        b.verifyMessage(id, true);
        vm.prank(guardians[0]);
        b.verifyMessage(id, true);
        vm.prank(guardians[1]);
        b.verifyMessage(id, true);
    }

    // ────────────────────────────────
    //  sendMessage / outbox
    // ────────────────────────────────

    function test_SendMessage_EmitsAndStoresOutboxRecord() public {
        vm.prank(app);
        bytes32 id = bridge.sendMessage(VIRTUALS, PAYLOAD);

        assertTrue(id != bytes32(0));
        assertEq(bridge.outboxCount(), 1);

        AtlasBridge.OutboxMessage memory m = bridge.getOutboxMessage(id);
        assertEq(m.targetEcosystem, VIRTUALS);
        assertEq(m.sender, app);
        assertEq(m.payload, PAYLOAD);
        assertEq(m.sentAt, block.timestamp);

        // Next message gets the next nonce → distinct id, correctly emitted
        bytes32 nextId =
            keccak256(abi.encode(EVM, VIRTUALS, PAYLOAD, app, block.chainid, uint256(1)));
        vm.expectEmit(true, false, false, true);
        emit IAtlasBridge.MessageSent(nextId, VIRTUALS, app);
        vm.prank(app);
        bytes32 actual = bridge.sendMessage(VIRTUALS, PAYLOAD);
        assertEq(actual, nextId);
        assertEq(bridge.outboxCount(), 2);
    }

    function test_SendMessage_SameEcosystemReverts() public {
        vm.prank(app);
        vm.expectRevert(AtlasBridge.AtlasBridge__SameEcosystem.selector);
        bridge.sendMessage(EVM, PAYLOAD);
    }

    function test_SendMessage_UnknownEcosystemReverts() public {
        vm.prank(app);
        vm.expectRevert(AtlasBridge.AtlasBridge__InvalidEcosystem.selector);
        bridge.sendMessage(keccak256("solana"), PAYLOAD);
    }

    function test_SendMessage_IdBindsAllProvenance() public {
        vm.prank(app);
        bytes32 id = bridge.sendMessage(VIRTUALS, PAYLOAD);

        // Same provenance → same id
        assertEq(
            keccak256(abi.encode(EVM, VIRTUALS, PAYLOAD, app, block.chainid, uint256(0))), id
        );

        // Any provenance field change → different id
        vm.prank(app);
        assertTrue(bridge.sendMessage(VIRTUALS, hex"ff") != id);
        vm.prank(makeAddr("other"));
        assertTrue(bridge.sendMessage(VIRTUALS, PAYLOAD) != id);

        // Different target ecosystem → different id (from a Robinhood source)
        AtlasBridge rh = new AtlasBridge(ROBINHOOD, governor);
        vm.prank(app);
        bytes32 toEvm = rh.sendMessage(EVM, PAYLOAD);
        vm.prank(app);
        bytes32 toVirtuals = rh.sendMessage(VIRTUALS, PAYLOAD);
        assertTrue(toEvm != toVirtuals);
    }

    // ────────────────────────────────
    //  Delivery
    // ────────────────────────────────

    function test_Deliver_FullPath_FromRealSourceInstance() public {
        // Source instance stands in for the Robinhood Chain deployment
        AtlasBridge source = new AtlasBridge(ROBINHOOD, governor);
        vm.chainId(42170);
        (bytes32 id, uint256 nonce, uint256 srcChain) = _send(source, EVM, app);
        vm.chainId(1);

        // Not deliverable before quorum
        assertFalse(_deliver(bridge, id, ROBINHOOD, app, srcChain, nonce));
        assertFalse(bridge.getMessage(id).delivered);

        _reachQuorum(bridge, id);
        assertEq(bridge.validAttestations(id), 3);

        assertTrue(_deliver(bridge, id, ROBINHOOD, app, srcChain, nonce));

        IAtlasBridge.CrossChainMessage memory m = bridge.getMessage(id);
        assertTrue(m.delivered);
        assertEq(m.messageId, id);
        assertEq(m.sourceEcosystem, ROBINHOOD);
        assertEq(m.targetEcosystem, EVM);
        assertEq(m.payload, PAYLOAD);
        assertEq(m.sender, app);
        assertEq(bridge.deliveredCount(), 1);
    }

    function test_Deliver_SecondDeliveryReverts() public {
        AtlasBridge source = new AtlasBridge(ROBINHOOD, governor);
        (bytes32 id, uint256 nonce, uint256 srcChain) = _send(source, EVM, app);
        _reachQuorum(bridge, id);
        assertTrue(_deliver(bridge, id, ROBINHOOD, app, srcChain, nonce));

        vm.prank(relayer);
        vm.expectRevert(AtlasBridge.AtlasBridge__AlreadyDelivered.selector);
        bridge.deliverMessage(id, PAYLOAD, abi.encode(ROBINHOOD, app, srcChain, nonce));
    }

    function test_Deliver_PayloadMismatchReverts() public {
        AtlasBridge source = new AtlasBridge(ROBINHOOD, governor);
        (bytes32 id,, ) = _send(source, EVM, app);
        _reachQuorum(bridge, id);

        vm.prank(relayer);
        vm.expectRevert(AtlasBridge.AtlasBridge__PayloadMismatch.selector);
        bridge.deliverMessage(id, hex"ffff", abi.encode(ROBINHOOD, app, uint256(1), uint256(0)));
    }

    function test_Deliver_WrongTargetInstanceReverts() public {
        (AtlasBridge source, bytes32 id, uint256 nonce, uint256 srcChain) = _sendFromRobinhood(app);
        _reachQuorum(bridge, id);

        // A destination on a *different* ecosystem must reject it — the id
        // binds the target ecosystem.
        AtlasBridge virtualsDest = new AtlasBridge(VIRTUALS, governor);
        vm.prank(relayer);
        vm.expectRevert(AtlasBridge.AtlasBridge__PayloadMismatch.selector);
        virtualsDest.deliverMessage(
            id, PAYLOAD, abi.encode(ROBINHOOD, app, uint256(1), uint256(0))
        );

        // Sanity: the correct destination still accepts it.
        assertTrue(_deliver(bridge, id, ROBINHOOD, app, srcChain, nonce));
        assertEq(source.outboxCount(), 1);
    }

    /// @dev Robinhood source on chain 42170, payload sent to EVM at nonce 0.
    function _sendFromRobinhood(address sender)
        internal
        returns (AtlasBridge source, bytes32 id, uint256 nonce, uint256 srcChain)
    {
        source = new AtlasBridge(ROBINHOOD, governor);
        vm.chainId(42170);
        (id, nonce, srcChain) = _send(source, EVM, sender);
        vm.chainId(1);
    }

    function test_Deliver_TamperedProvenanceReverts() public {
        (, bytes32 id, uint256 nonce, uint256 srcChain) = _sendFromRobinhood(app);
        _reachQuorum(bridge, id);

        // Different claimed sender → different recomputed id → mismatch
        vm.prank(relayer);
        vm.expectRevert(AtlasBridge.AtlasBridge__PayloadMismatch.selector);
        bridge.deliverMessage(
            id, PAYLOAD, abi.encode(ROBINHOOD, makeAddr("imposter"), srcChain, nonce)
        );

        // Tampered nonce → mismatch
        vm.prank(relayer);
        vm.expectRevert(AtlasBridge.AtlasBridge__PayloadMismatch.selector);
        bridge.deliverMessage(id, PAYLOAD, abi.encode(ROBINHOOD, app, srcChain, nonce + 1));
    }

    function test_Deliver_UnknownSourceEcosystemReverts() public {
        bytes32 unknown = keccak256("solana");
        bytes32 id = keccak256(abi.encode(unknown, EVM, PAYLOAD, app, uint256(1), uint256(0)));
        _reachQuorum(bridge, id);

        vm.prank(relayer);
        vm.expectRevert(AtlasBridge.AtlasBridge__InvalidEcosystem.selector);
        bridge.deliverMessage(id, PAYLOAD, abi.encode(unknown, app, uint256(1), uint256(0)));
    }

    function test_Deliver_ZeroMessageIdReverts() public {
        vm.prank(relayer);
        vm.expectRevert(AtlasBridge.AtlasBridge__ZeroMessageId.selector);
        bridge.deliverMessage(bytes32(0), PAYLOAD, abi.encode(ROBINHOOD, app, uint256(1), uint256(0)));
    }

    function test_Deliver_DoesNotConsumeAttestationsWhenQuorumUnmet() public {
        AtlasBridge source = new AtlasBridge(ROBINHOOD, governor);
        (bytes32 id, uint256 nonce, uint256 srcChain) = _send(source, EVM, app);

        assertFalse(_deliver(bridge, id, ROBINHOOD, app, srcChain, nonce));
        assertFalse(_deliver(bridge, id, ROBINHOOD, app, srcChain, nonce));

        // Delivery still works once quorum arrives later
        _reachQuorum(bridge, id);
        assertTrue(_deliver(bridge, id, ROBINHOOD, app, srcChain, nonce));
    }

    // ────────────────────────────────
    //  Guardian attestation
    // ────────────────────────────────

    function test_VerifyMessage_QuorumMet_ExactBoundary() public {
        AtlasBridge source = new AtlasBridge(ROBINHOOD, governor);
        (bytes32 id,, ) = _send(source, EVM, app);

        vm.prank(guardians[0]);
        bridge.verifyMessage(id, true);
        assertFalse(bridge.getMessage(id).delivered);
        assertLt(bridge.validAttestations(id), bridge.GUARDIAN_QUORUM());

        vm.prank(guardians[1]);
        bridge.verifyMessage(id, true);
        assertGe(bridge.validAttestations(id), bridge.GUARDIAN_QUORUM()); // exactly 2-of-5
    }

    function test_VerifyMessage_NonGuardianReverts() public {
        AtlasBridge source = new AtlasBridge(ROBINHOOD, governor);
        (bytes32 id,, ) = _send(source, EVM, app);

        vm.prank(app);
        vm.expectRevert(AtlasBridge.AtlasBridge__NotGuardian.selector);
        bridge.verifyMessage(id, true);
    }

    function test_VerifyMessage_DuplicateVoteIgnored() public {
        AtlasBridge source = new AtlasBridge(ROBINHOOD, governor);
        (bytes32 id,, ) = _send(source, EVM, app);

        vm.prank(guardians[0]);
        bridge.verifyMessage(id, true);
        vm.prank(guardians[0]);
        bridge.verifyMessage(id, true); // double vote
        vm.prank(governor);
        bridge.verifyMessage(id, true);

        assertEq(bridge.validAttestations(id), 2); // not 3
    }

    function test_VerifyMessage_FlipVoteIgnored() public {
        AtlasBridge source = new AtlasBridge(ROBINHOOD, governor);
        (bytes32 id,, ) = _send(source, EVM, app);

        vm.prank(guardians[0]);
        bridge.verifyMessage(id, true);
        vm.prank(guardians[0]);
        bridge.verifyMessage(id, false); // flip attempt — ignored

        assertEq(bridge.validAttestations(id), 1);
        assertEq(bridge.rejectedAttestations(id), 0);
    }

    function test_VerifyMessage_RejectionsDoNotBlockDelivery() public {
        AtlasBridge source = new AtlasBridge(ROBINHOOD, governor);
        (bytes32 id, uint256 nonce, uint256 srcChain) = _send(source, EVM, app);

        for (uint256 i = 1; i < 5; i++) {
            vm.prank(guardians[i]);
            bridge.verifyMessage(id, false); // four committee guardians reject
        }
        assertEq(bridge.rejectedAttestations(id), 4);

        // Governor counts as one attester; +1 guardian who hasn't voted → quorum
        vm.prank(governor);
        bridge.verifyMessage(id, true);
        vm.prank(guardians[0]);
        bridge.verifyMessage(id, true);

        assertTrue(_deliver(bridge, id, ROBINHOOD, app, srcChain, nonce));
        assertTrue(bridge.getMessage(id).delivered);
    }

    function test_VerifyMessage_NonExistentMessageIsAttestable() public {
        // Guardians attest ids they observed off-chain on the source chain;
        // V1 keeps no local outbox mirror, so any id is attestable pre-delivery.
        bytes32 id = keccak256("future message");
        vm.prank(guardians[0]);
        bridge.verifyMessage(id, true);
        assertEq(bridge.validAttestations(id), 1);
    }

    function test_VerifyMessage_AfterDeliveryClosesAttestation() public {
        AtlasBridge source = new AtlasBridge(ROBINHOOD, governor);
        (bytes32 id, uint256 nonce, uint256 srcChain) = _send(source, EVM, app);
        _reachQuorum(bridge, id);
        assertTrue(_deliver(bridge, id, ROBINHOOD, app, srcChain, nonce));

        vm.prank(guardians[2]);
        vm.expectRevert(AtlasBridge.AtlasBridge__AttestationClosed.selector);
        bridge.verifyMessage(id, true);
    }

    // ────────────────────────────────
    //  Admin
    // ────────────────────────────────

    function test_Admin_GovernorRotation() public {
        address newGov = makeAddr("newGovernor");
        vm.prank(governor);
        bridge.setGovernor(newGov);

        // Old governor loses authority
        vm.prank(governor);
        vm.expectRevert(AtlasBridge.AtlasBridge__NotGovernor.selector);
        bridge.setGovernor(governor);
    }

    function test_Admin_SetCoreAndGuardianGate() public {
        // Fresh bridge without core: only the governor may attest
        AtlasBridge bare = new AtlasBridge(EVM, governor);
        vm.prank(guardians[0]);
        vm.expectRevert(AtlasBridge.AtlasBridge__NotGuardian.selector);
        bare.verifyMessage(bytes32("x"), true);

        // After setCore, registered active guardians are recognized
        vm.prank(governor);
        bare.setCore(coreStub);
        vm.prank(guardians[0]);
        bare.verifyMessage(bytes32("x"), true);
        assertEq(bare.validAttestations(bytes32("x")), 1);
    }

    // ────────────────────────────────
    //  Multi-ecosystem deployment
    // ────────────────────────────────

    function test_MultiEcosystem_IndependentInstancesPerEcosystem() public {
        // One instance per ecosystem, same governor
        AtlasBridge rh = new AtlasBridge(ROBINHOOD, governor);
        AtlasBridge virt = new AtlasBridge(VIRTUALS, governor);

        assertEq(rh.localEcosystem(), ROBINHOOD);
        assertEq(bridge.localEcosystem(), EVM);
        assertEq(virt.localEcosystem(), VIRTUALS);

        // Ids from different source ecosystems differ — the source is bound
        vm.prank(app);
        bytes32 rhId = rh.sendMessage(EVM, PAYLOAD);
        vm.prank(app);
        bytes32 virtId = virt.sendMessage(EVM, PAYLOAD);
        assertTrue(rhId != virtId);

        // The EVM destination independently derives the matching inbound id
        assertEq(rhId, keccak256(abi.encode(ROBINHOOD, EVM, PAYLOAD, app, block.chainid, uint256(0))));

        // Quorum on the destination, then deliver
        vm.prank(governor);
        bridge.verifyMessage(rhId, true);
        vm.prank(guardians[0]);
        bridge.verifyMessage(rhId, true);
        assertTrue(_deliver(bridge, rhId, ROBINHOOD, app, block.chainid, 0));
        assertTrue(bridge.getMessage(rhId).delivered);
        assertFalse(virt.getMessage(virtId).delivered);
    }

    function test_MultiEcosystem_MessageFromEvmToVirtuals() public {
        vm.chainId(8453);
        AtlasBridge evmSource = new AtlasBridge(EVM, governor);
        (bytes32 id, uint256 nonce, uint256 srcChain) = _send(evmSource, VIRTUALS, app);
        vm.chainId(1);

        AtlasBridge virt = new AtlasBridge(VIRTUALS, governor);
        vm.prank(governor);
        virt.setCore(coreStub);

        assertFalse(_deliver(virt, id, EVM, app, srcChain, nonce)); // quorum unmet

        vm.prank(governor);
        virt.verifyMessage(id, true);
        vm.prank(guardians[0]);
        virt.verifyMessage(id, true);

        assertTrue(_deliver(virt, id, EVM, app, srcChain, nonce));

        IAtlasBridge.CrossChainMessage memory m = virt.getMessage(id);
        assertTrue(m.delivered);
        assertEq(m.sourceEcosystem, EVM);
        assertEq(m.targetEcosystem, VIRTUALS);
    }
}

/// @dev Minimal IAtlasCore stub matching the real `guardians` getter shape:
///      (address staker, uint256 stake, bool active, uint256 tasksVerified, uint256 tasksSlashed).
///      Guardians must be explicitly registered via {setMember}.
contract ActiveGuardianCoreStub {
    mapping(address => bool) public isMember;

    function setMember(address who) external {
        isMember[who] = true;
    }

    function guardians(address g)
        external
        view
        returns (address, uint256, bool, uint256, uint256)
    {
        return (g, 0, isMember[g], 0, 0);
    }
}
