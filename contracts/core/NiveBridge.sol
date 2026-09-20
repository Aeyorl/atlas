// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {INiveBridge} from "../interfaces/INiveBridge.sol";
import {INiveCore} from "../interfaces/INiveCore.sol";

/// @title NiveBridge
/// @notice Cross-ecosystem message bus between Robinhood Chain, EVM ecosystems,
///         and Virtuals Protocol.
/// @dev V1 is an attested message bus with one bridge instance per ecosystem:
///      1. {sendMessage} writes to a local outbox and derives a deterministic
///         `messageId` = keccak256(source, target, payload, sender, sourceBlock).
///      2. Off-chain relayers observe the MessageSent event and call
///         {deliverMessage} on the destination instance, supplying the payload
///         plus the provenance fields packed in `proof`.
///      3. Registered guardians attest each message via {verifyMessage}; a
///         delivery is accepted once `GUARDIAN_QUORUM` distinct guardians have
///         voted valid. Relayers are permissionless — attestation is the
///         security boundary.
///      `messageId` binds every provenance field, so a relayer cannot mix
///      payloads, senders, or source ecosystems; a mismatch reverts.
contract NiveBridge is INiveBridge {
    // ────────────────────────────────
    //  Errors
    // ────────────────────────────────

    error NiveBridge__ZeroGovernor();
    error NiveBridge__InvalidEcosystem();
    error NiveBridge__SameEcosystem();
    error NiveBridge__ZeroMessageId();
    error NiveBridge__WrongTargetEcosystem();
    error NiveBridge__PayloadMismatch();
    error NiveBridge__AlreadyDelivered();
    error NiveBridge__NotGuardian();
    error NiveBridge__AttestationClosed();
    error NiveBridge__ZeroCore();
    error NiveBridge__NotGovernor();

    // ────────────────────────────────
    //  Modifiers
    // ────────────────────────────────

    modifier onlyGovernor() {
        if (msg.sender != governor) revert NiveBridge__NotGovernor();
        _;
    }

    // ────────────────────────────────
    //  Constants
    // ────────────────────────────────

    /// @dev Mirrors the ecosystem constants on NiveCore.
    bytes32 public constant ECOSYSTEM_ROBINHOOD = keccak256("robinhood-chain");
    bytes32 public constant ECOSYSTEM_EVM       = keccak256("evm");
    bytes32 public constant ECOSYSTEM_VIRTUALS  = keccak256("virtuals");

    /// @dev Distinct guardian attestations required to deliver a message.
    ///      Matches the default NiveCore.GUARDIAN_COMMITTEE_SIZE (5) — 2-of-5.
    uint256 public constant GUARDIAN_QUORUM = 2;

    /// @dev Committee size this bridge's quorum is calibrated against.
    uint256 public constant GUARDIAN_COMMITTEE_SIZE = 5;

    // ────────────────────────────────
    //  Types
    // ────────────────────────────────

    struct OutboxMessage {
        bytes32  targetEcosystem;
        address  sender;
        bytes    payload;
        uint256  sentAt;
    }

    // ────────────────────────────────
    //  State
    // ────────────────────────────────

    /// @notice The ecosystem this instance runs on.
    bytes32 public immutable localEcosystem;

    /// @notice Governance: admin params and rotation. In production a
    ///         multisig/DAO or the Guardian committee.
    address public governor;

    /// @notice NiveCore deployment on this chain — source of the registered
    ///         guardian set. Set post-deploy (deployment is circular).
    INiveCore public core;

    /// @dev messageId => outgoing message (this instance is the source)
    mapping(bytes32 => OutboxMessage) private _outbox;

    /// @dev messageId => incoming message (this instance is the target)
    mapping(bytes32 => CrossChainMessage) private _inbox;

    /// @dev messageId => guardian => voted (true = attested valid)
    mapping(bytes32 => mapping(address => bool)) private _attestedValid;

    /// @dev messageId => guardian => has voted at all (dedup, incl. rejections)
    mapping(bytes32 => mapping(address => bool)) private _hasVoted;

    /// @dev messageId => count of valid attestations
    mapping(bytes32 => uint256) public validAttestations;

    /// @dev messageId => count of explicit rejections (audit trail; a
    ///      rejection does not block delivery — quorum of valid votes governs)
    mapping(bytes32 => uint256) public rejectedAttestations;

    uint256 public outboxCount;
    uint256 public deliveredCount;

    // ────────────────────────────────
    //  Constructor
    // ────────────────────────────────

    constructor(bytes32 _localEcosystem, address _governor) {
        if (_governor == address(0)) revert NiveBridge__ZeroGovernor();
        if (!_isValidEcosystem(_localEcosystem)) revert NiveBridge__InvalidEcosystem();
        localEcosystem = _localEcosystem;
        governor = _governor;
    }

    // ────────────────────────────────
    //  Admin
    // ────────────────────────────────

    /// @notice Link this bridge to the chain's NiveCore for guardian checks.
    /// @dev Post-deploy call. Until set, only the governor may attest.
    function setCore(address newCore) external onlyGovernor {
        if (newCore == address(0)) revert NiveBridge__ZeroCore();
        core = INiveCore(newCore);
    }

    /// @notice Transfer governor authority (multisig/DAO rotation).
    function setGovernor(address newGovernor) external onlyGovernor {
        if (newGovernor == address(0)) revert NiveBridge__ZeroGovernor();
        governor = newGovernor;
    }

    // ────────────────────────────────
    //  Outbound
    // ────────────────────────────────

    /// @inheritdoc INiveBridge
    function sendMessage(
        bytes32 targetEcosystem,
        bytes calldata payload
    ) external override returns (bytes32 messageId) {
        if (!_isValidEcosystem(targetEcosystem)) revert NiveBridge__InvalidEcosystem();
        if (targetEcosystem == localEcosystem) revert NiveBridge__SameEcosystem();

        messageId = keccak256(
            abi.encode(localEcosystem, targetEcosystem, payload, msg.sender, block.chainid, outboxCount)
        );

        _outbox[messageId] = OutboxMessage({
            targetEcosystem: targetEcosystem,
            sender: msg.sender,
            payload: payload,
            sentAt: block.timestamp
        });
        outboxCount++;

        emit MessageSent(messageId, targetEcosystem, msg.sender);
    }

    // ────────────────────────────────
    //  Inbound
    // ────────────────────────────────

    /// @inheritdoc INiveBridge
    /// @dev `proof` packs the source provenance, exactly as observed on the
    ///      source chain:
    ///      abi.encode(sourceEcosystem, sourceSender, sourceChainId, sourceNonce).
    ///      Every field is bound into `messageId`, so a relayer cannot mix
    ///      payloads, senders, chains, or nonces — any tampering changes the
    ///      recomputed hash and reverts. Guardians only attest ids they
    ///      observed on the real source chain, so a forged id also needs a
    ///      guardian quorum to become deliverable.
    ///      Reverts on caller bugs (replay, wrong instance, payload mismatch);
    ///      returns false + MessageFailed when the transport is not ready yet
    ///      (quorum unmet) so relayers can retry.
    function deliverMessage(
        bytes32 messageId,
        bytes calldata payload,
        bytes calldata proof
    ) external override returns (bool) {
        if (messageId == bytes32(0)) revert NiveBridge__ZeroMessageId();
        if (_inbox[messageId].delivered) revert NiveBridge__AlreadyDelivered();

        (bytes32 sourceEcosystem, address sourceSender, uint256 sourceChainId, uint256 sourceNonce) =
            abi.decode(proof, (bytes32, address, uint256, uint256));

        if (!_isValidEcosystem(sourceEcosystem)) revert NiveBridge__InvalidEcosystem();

        // This instance only accepts messages addressed to its ecosystem.
        // The target is bound into the messageId, so this check is implied by
        // the hash — spelled out for a precise revert reason.
        bytes32 expected = keccak256(
            abi.encode(sourceEcosystem, localEcosystem, payload, sourceSender, sourceChainId, sourceNonce)
        );
        if (expected != messageId) revert NiveBridge__PayloadMismatch();

        if (validAttestations[messageId] < GUARDIAN_QUORUM) {
            emit MessageFailed(messageId, bytes("nive-bridge: quorum not met"));
            return false;
        }

        _inbox[messageId] = CrossChainMessage({
            messageId: messageId,
            sourceEcosystem: sourceEcosystem,
            targetEcosystem: localEcosystem,
            payload: payload,
            sender: sourceSender,
            delivered: true
        });
        deliveredCount++;

        emit MessageDelivered(messageId, sourceEcosystem);
        return true;
    }

    // ────────────────────────────────
    //  Guardian attestation
    // ────────────────────────────────

    /// @inheritdoc INiveBridge
    /// @dev Guardians attest after observing the source-chain MessageSent
    ///      event; delivery is possible once quorum is reached. Repeat votes
    ///      are ignored (idempotent). Explicit rejections are recorded but do
    ///      not block delivery — a quorum of valid votes governs in V1.
    function verifyMessage(bytes32 messageId, bool valid) external override {
        if (messageId == bytes32(0)) revert NiveBridge__ZeroMessageId();
        if (_inbox[messageId].delivered) revert NiveBridge__AttestationClosed();
        if (!_isGuardian(msg.sender)) revert NiveBridge__NotGuardian();

        if (_hasVoted[messageId][msg.sender]) return; // idempotent dedup
        _hasVoted[messageId][msg.sender] = true;

        if (valid) {
            _attestedValid[messageId][msg.sender] = true;
            validAttestations[messageId]++;
        } else {
            rejectedAttestations[messageId]++;
        }

        emit GuardianVerification(messageId, msg.sender, valid);
    }

    // ────────────────────────────────
    //  Queries
    // ────────────────────────────────

    /// @inheritdoc INiveBridge
    /// @dev Returns the delivered inbox record for incoming messages; a stub
    ///      with `delivered = false` for anything not (yet) delivered. Outbox
    ///      state is exposed via {getOutboxMessage}.
    function getMessage(bytes32 messageId) external view override returns (CrossChainMessage memory) {
        return _inbox[messageId];
    }

    /// @notice Outgoing message record (this instance as source).
    function getOutboxMessage(bytes32 messageId)
        external
        view
        returns (OutboxMessage memory)
    {
        return _outbox[messageId];
    }

    /// @notice Whether `guardian` has attested `messageId` as valid.
    function hasAttested(bytes32 messageId, address guardian) external view returns (bool) {
        return _attestedValid[messageId][guardian];
    }

    /// @notice Whether `guardian` has voted on `messageId` at all.
    function hasVoted(bytes32 messageId, address guardian) external view returns (bool) {
        return _hasVoted[messageId][guardian];
    }

    /// @notice Whether this bridge instance will accept delivery for
    ///         `targetEcosystem` (always false — check the target instance).
    function acceptsEcosystem(bytes32 targetEcosystem) external view returns (bool) {
        return targetEcosystem == localEcosystem;
    }

    // ────────────────────────────────
    //  Internal
    // ────────────────────────────────

    function _isValidEcosystem(bytes32 ecosystem) internal pure returns (bool) {
        return ecosystem == ECOSYSTEM_ROBINHOOD || ecosystem == ECOSYSTEM_EVM
            || ecosystem == ECOSYSTEM_VIRTUALS;
    }

    function _isGuardian(address account) internal view returns (bool) {
        if (account == governor) return true; // governor counts as one attester
        if (address(core) == address(0)) return false;
        (, , bool active, , ) = core.guardians(account);
        return active;
    }
}
