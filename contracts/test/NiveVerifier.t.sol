// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {NiveVerifier} from "../core/NiveVerifier.sol";
import {AgentRegistry} from "../core/AgentRegistry.sol";
import {SettlementEngine} from "../core/SettlementEngine.sol";
import {TaskManager} from "../core/TaskManager.sol";

/// @dev NiveVerifier tests over REAL BN254 precompile math.
///
///      Unlike the MockGroth16Verifier in ZkVerification.t.sol, these tests
///      run the actual pairing check (EIP-197 precompiles on Cancun/Foundry).
///      The verification key is synthetic but structurally valid:
///
///        alpha1 = G1 * 1,  beta2 = gamma2 = delta2 = G2 * 1
///        IC[0] = G1 * 1,   IC[1] = G1 * 2,   IC[2] = G1 * 3
///
///      so e(alpha, beta) = e(C, delta) = e(IC[0], gamma) = e(G1, G2) and
///      e(IC[i+1] * x_i, gamma) = e(G1, G2)^(s_i * x_i) with s_1 = 2, s_2 = 3.
///      The toy circuit proves a LINEAR statement over the two public inputs
///      (x0, x1) — the canonical task-id limbs per SettlementEngine:
///
///        k == 3 + 2*x0 + 3*x1   (mod r)
///
///      for a proof (A = G1*k, B = G2*1, C = G1*1). The linear form lets the
///      prover satisfy ANY statement (k is derived from the inputs), which is
///      exactly what the settlement integration needs: task ids are fixed by
///      setUp, so a quadratic constraint would be unsatisfiable for most ids.
///
///      There is no G2-arithmetic precompile (EIP-196's 0x06/0x07 are G1
///      only), so B = G2*1 is computed here with plain Solidity Fp2
///      arithmetic on the twist curve y^2 = x^3 + 3/(9+i).
///
///      This keeps every constant independently derivable (no copied magic
///      numbers except the EIP-197 curve parameters) while still proving the
///      verifier accepts exactly the statements it should and rejects
///      everything else.
contract NiveVerifierTest is Test {
    // ────────────────────────────────
    //  BN254 parameters (EIP-197)
    // ────────────────────────────────

    uint256 internal constant P =
        21888242871839275222246405745257275088696311157297823662689037894645226208583;
    uint256 internal constant R =
        21888242871839275222246405745257275088548364400416034343698204186575808495617;

    /// @dev G1 generator (1, 2) on y^2 = x^3 + 3.
    uint256 internal constant G1X = 1;
    uint256 internal constant G1Y = 2;

    // G2 generator, real/imaginary components of x and y.
    uint256 internal constant G2X_RE = 10857046999023057135944570762232829481370756359578518086990519993285655852781;
    uint256 internal constant G2X_IM = 11559732032986387107991004021392285783925812861821192530917403151452391805634;
    uint256 internal constant G2Y_RE = 8495653923123431417604973247489272438418190587263600148770280649306958101930;
    uint256 internal constant G2Y_IM = 4082367875863433681332203403145435568316851327593401208105741076214120093531;

    // Synthetic-circuit scalars: IC = [G1*1, G1*2, G1*3]
    uint256 internal constant S0 = 1;
    uint256 internal constant S1 = 2;
    uint256 internal constant S2 = 3;

    /// @dev Prover's witness scalar for the primary test vector.
    uint256 internal constant K = 12345;
    NiveVerifier internal verifier;

    // Settlement wiring (integration section)
    AgentRegistry internal registry;
    SettlementEngine internal settlement;
    TaskManager internal taskManager;

    address internal governor;
    address internal creator;
    address internal agentOwner;

    bytes32 internal constant TASK1 = keccak256("task-1");
    uint256 internal constant BUDGET = 10 ether;
    uint256 internal constant FEE = 6 ether;
    uint256 internal constant DEADLINE = 7 days;

    /// @dev Twist curve constant b' = 3/(9+i), as (re, im).
    uint256[2] internal twistB;

    function setUp() public {
        twistB = _fp2Mul([uint256(3), uint256(0)], _fp2Inv([uint256(9), uint256(1)]));

        // Sanity: the G2 generator sits on the twist curve.
        (uint256[2] memory gx, uint256[2] memory gy) = _g2Raw();
        assertTrue(_onTwist(gx, gy), "G2 generator not on twist curve");

        uint256[2] memory alpha = _g1Mul(1);
        uint256[4] memory beta = _g2Wire(1);
        uint256[4] memory gamma = _g2Wire(1);
        uint256[4] memory delta = _g2Wire(1);

        uint256[2][] memory ic = new uint256[2][](3);
        ic[0] = _g1Mul(S0);
        ic[1] = _g1Mul(S1);
        ic[2] = _g1Mul(S2);

        verifier = new NiveVerifier(alpha, beta, gamma, delta, ic);

        // Settlement wiring — mirrors ZkVerification.t.sol
        registry = new AgentRegistry();
        governor = makeAddr("governor");
        settlement = new SettlementEngine(governor);
        taskManager = new TaskManager(address(registry), address(settlement), governor);
        registry.setTaskManager(address(taskManager));
        vm.prank(governor);
        settlement.setTaskManager(address(taskManager));

        creator = makeAddr("creator");
        agentOwner = makeAddr("agentOwner");

        bytes32[] memory caps = new bytes32[](1);
        caps[0] = bytes32("TRADE");
        vm.prank(agentOwner);
        registry.register(keccak256("agent-1"), "https://a.example/x.json", caps, agentOwner, 0);

        vm.prank(governor);
        settlement.setVerifier(address(verifier));
    }

    // ────────────────────────────────
    //  Unit: verifyProof on real pairings
    // ────────────────────────────────

    function test_ValidProofVerifies() public view {
        (bytes memory proof, uint256[] memory inputs) = _validProof(TASK1);
        assertTrue(verifier.verifyProof(proof, inputs));
    }

    function test_DifferentTasksProduceDistinctValidProofs() public view {
        // The witness k is derived from the statement: two different task ids
        // yield different k (and hence different A), and both verify.
        (bytes memory proof1, uint256[] memory inputs1) = _validProof(keccak256("task-A"));
        (bytes memory proof2, uint256[] memory inputs2) = _validProof(keccak256("task-B"));
        assertTrue(verifier.verifyProof(proof1, inputs1));
        assertTrue(verifier.verifyProof(proof2, inputs2));
        assertTrue(keccak256(proof1) != keccak256(proof2));
    }

    function test_WrongPublicInputFails() public view {
        (bytes memory proof, uint256[] memory inputs) = _validProof(TASK1);
        // Perturb the free input: the constraint k == 3 + 2*x0 + 3*x1
        // no longer holds, so the pairing check must fail.
        inputs[1] = addmod(inputs[1], 1, R);
        assertFalse(verifier.verifyProof(proof, inputs));
    }

    function test_TamperedProofComponentFails() public view {
        (bytes memory proof, uint256[] memory inputs) = _validProof(TASK1);
        // Overwrite pi_c.x (word 6) — the commitment no longer matches.
        _writeWord(proof, 6, uint256(keccak256("tampered-c")));
        assertFalse(verifier.verifyProof(proof, inputs));
    }

    function test_TamperedG2ComponentFails() public view {
        (bytes memory proof, uint256[] memory inputs) = _validProof(TASK1);
        // Overwrite pi_b.y real part (word 5) — either an off-curve G2 point
        // (precompile rejects) or a wrong pairing (result != 1).
        _writeWord(proof, 5, addmod(_readWord(proof, 5), 1, P));
        assertFalse(verifier.verifyProof(proof, inputs));
    }

    function test_WrongLengthProofFails() public view {
        (bytes memory proof, uint256[] memory inputs) = _validProof(TASK1);

        bytes memory short = new bytes(255);
        for (uint256 i = 0; i < 255; i++) short[i] = proof[i];
        assertFalse(verifier.verifyProof(short, inputs));

        bytes memory long = new bytes(257);
        for (uint256 i = 0; i < 256; i++) long[i] = proof[i];
        assertFalse(verifier.verifyProof(long, inputs));
    }

    function test_OffCurveG1ProofFails() public view {
        (bytes memory proof, uint256[] memory inputs) = _validProof(TASK1);
        // (1, 3) is not on y^2 = x^3 + 3 (9 != 4): the pairing precompile
        // must reject the input, and verifyProof must return false.
        _writeWord(proof, 0, G1X);
        _writeWord(proof, 1, 3);
        assertFalse(verifier.verifyProof(proof, inputs));
    }

    function test_InputCountMismatchFails() public view {
        (bytes memory proof, uint256[] memory inputs) = _validProof(TASK1);
        uint256[] memory wrong = new uint256[](3);
        wrong[0] = inputs[0];
        wrong[1] = inputs[1];
        wrong[2] = 0;
        assertFalse(verifier.verifyProof(proof, wrong));
    }

    function test_SnarkjsComponentOrderFails() public view {
        // snarkjs serializes G2 as (real, imaginary); EIP-197 wants
        // (imaginary, real). Feeding snarkjs order must NOT verify — this is
        // the wire-format trap the contract docs warn about.
        (bytes memory proof, uint256[] memory inputs) = _validProof(TASK1);
        _swapWords(proof, 2, 3); // pi_b.x (im, re) -> (re, im)
        _swapWords(proof, 4, 5); // pi_b.y
        assertFalse(verifier.verifyProof(proof, inputs));
    }

    function test_ProofForDifferentStatementFails() public view {
        // A proof of statement (task-X, witness kX) must not verify against
        // statement (task-Y, witness kY != kX): the input commitment vk_x is
        // part of the pairing equation, and the two statements imply
        // different witness scalars.
        (bytes memory proofX,) = _validProof(keccak256("task-X"));
        (, uint256[] memory inputsY) = _validProof(keccak256("task-Y"));
        assertFalse(verifier.verifyProof(proofX, inputsY));
    }

    // ────────────────────────────────
    //  Unit: constructor guards
    // ────────────────────────────────

    function test_Constructor_NoVerificationKeyReverts() public {
        uint256[2] memory alpha = _g1Mul(1);
        uint256[4] memory beta = _g2Wire(1);
        uint256[4] memory gamma = _g2Wire(1);
        uint256[4] memory delta = _g2Wire(1);
        uint256[2][] memory ic = new uint256[2][](0);

        vm.expectRevert(NiveVerifier.NiveVerifier__NoVerificationKey.selector);
        new NiveVerifier(alpha, beta, gamma, delta, ic);
    }

    function test_Constructor_ZeroAlphaReverts() public {
        uint256[2] memory alpha;
        uint256[4] memory beta = _g2Wire(1);
        uint256[4] memory gamma = _g2Wire(1);
        uint256[4] memory delta = _g2Wire(1);
        uint256[2][] memory ic = new uint256[2][](1);
        ic[0] = _g1Mul(1);

        vm.expectRevert(NiveVerifier.NiveVerifier__ZeroAlpha.selector);
        new NiveVerifier(alpha, beta, gamma, delta, ic);
    }

    function test_KeyShapeIsExposed() public view {
        assertEq(verifier.publicInputCount(), 2);
        (uint256 ic0x, uint256 ic0y) = verifier.icPoint(0);
        assertEq(ic0x, _g1Mul(S0)[0]);
        assertEq(ic0y, _g1Mul(S0)[1]);
        assertEq(verifier.alpha1()[0], G1X);
        assertEq(verifier.alpha1()[1], G1Y);
    }

    // ────────────────────────────────
    //  Integration: ZK-gated settlement with the real verifier
    // ────────────────────────────────

    function test_Settlement_ValidSyntheticProofSettles() public {
        (bytes memory proof, uint256[] memory inputs) = _validProof(TASK1);
        _runToVerifying(TASK1, abi.encode(proof, inputs));
        _settle(TASK1);

        assertTrue(settlement.getSettlement(TASK1).settled);
        assertTrue(settlement.hasProofVerified(TASK1));
        assertEq(address(settlement.verifier()), address(verifier));
    }

    function test_Settlement_TamperedProofRevertsAndKeepsEscrow() public {
        (bytes memory proof, uint256[] memory inputs) = _validProof(TASK1);
        // Tamper pi_c — settlement must revert and preserve the escrow.
        _writeWord(proof, 6, uint256(keccak256("tampered")));

        _runToVerifying(TASK1, abi.encode(proof, inputs));

        vm.prank(governor);
        taskManager.verifyTask(TASK1, true);
        vm.warp(block.timestamp + 3 days + 1);

        vm.expectRevert(SettlementEngine.SettlementEngine__InvalidProof.selector);
        taskManager.settleTask(TASK1);

        assertEq(settlement.getEscrow(TASK1), BUDGET);
        assertFalse(settlement.getSettlement(TASK1).settled);
        assertEq(agentOwner.balance, 0);
        assertFalse(settlement.hasProofVerified(TASK1));
    }

    // ────────────────────────────────
    //  Helpers: proof construction
    // ────────────────────────────────

    /// @dev Valid proof for the canonical statement over `taskId`:
    ///      inputs = (lo, hi) 128-bit limbs, k = 3 + 2*lo + 3*hi (mod r).
    function _validProof(bytes32 taskId)
        internal
        view
        returns (bytes memory proof, uint256[] memory inputs)
    {
        uint256 x0 = uint256(taskId) & type(uint128).max;
        uint256 x1 = uint256(taskId) >> 128;
        uint256 k = addmod(3, addmod(mulmod(S1, x0, R), mulmod(S2, x1, R), R), R);

        // Circuit sanity: k == 3 + 2*x0 + 3*x1 (mod r).
        assertEq(
            k,
            addmod(3, addmod(mulmod(S1, x0, R), mulmod(S2, x1, R), R), R),
            "synthetic constraint violated"
        );

        inputs = new uint256[](2);
        inputs[0] = x0;
        inputs[1] = x1;

        proof = new bytes(256);
        uint256[2] memory a = _g1Mul(k);
        uint256[4] memory b = _g2Wire(1); // B = G2 * 1 (constant for this circuit)
        uint256[2] memory c = _g1Mul(1);  // C = G1 * 1 per the circuit setup
        _writeWord(proof, 0, a[0]);
        _writeWord(proof, 1, a[1]);
        _writeWord(proof, 2, b[0]);
        _writeWord(proof, 3, b[1]);
        _writeWord(proof, 4, b[2]);
        _writeWord(proof, 5, b[3]);
        _writeWord(proof, 6, c[0]);
        _writeWord(proof, 7, c[1]);
    }

    function _runToVerifying(bytes32 taskId, bytes memory verificationPayload) internal {
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
        taskManager.completeTask(taskId, "0xresult", verificationPayload);
    }

    function _settle(bytes32 taskId) internal {
        vm.prank(governor);
        taskManager.verifyTask(taskId, true);
        vm.warp(block.timestamp + 3 days + 1);
        taskManager.settleTask(taskId);
    }

    function _caps() internal pure returns (bytes32[] memory caps) {
        caps = new bytes32[](1);
        caps[0] = bytes32("TRADE");
    }

    // ────────────────────────────────
    //  Helpers: G1 (via EIP-196 precompiles)
    // ────────────────────────────────

    function _g1Mul(uint256 scalar) internal view returns (uint256[2] memory point) {
        (bool ok, bytes memory out) = address(0x07).staticcall(
            abi.encodePacked(G1X, G1Y, scalar)
        );
        require(ok && out.length == 64, "g1Mul failed");
        // `out` is a bytes memory: word 0 is the LENGTH, data starts at 32.
        assembly {
            mstore(point, mload(add(out, 32)))
            mstore(add(point, 32), mload(add(out, 64)))
        }
    }

    // ────────────────────────────────
    //  Helpers: G2 (plain Solidity Fp2 arithmetic)
    // ────────────────────────────────

    /// @dev Fp2 elements as (real, imaginary): a + b*i = [a, b].
    ///      Twist curve: y^2 = x^3 + b', b' = 3/(9+i).

    function _g2Raw() internal pure returns (uint256[2] memory x, uint256[2] memory y) {
        x = [G2X_RE, G2X_IM];
        y = [G2Y_RE, G2Y_IM];
    }

    function _fp2Mul(uint256[2] memory u, uint256[2] memory v)
        internal
        pure
        returns (uint256[2] memory w)
    {
        // (a + bi)(c + di) = (ac - bd) + (ad + bc)i
        uint256 ac = mulmod(u[0], v[0], P);
        uint256 bd = mulmod(u[1], v[1], P);
        w[0] = addmod(ac, P - bd, P);
        w[1] = addmod(mulmod(u[0], v[1], P), mulmod(u[1], v[0], P), P);
    }

    function _fp2Add(uint256[2] memory u, uint256[2] memory v)
        internal
        pure
        returns (uint256[2] memory w)
    {
        w[0] = addmod(u[0], v[0], P);
        w[1] = addmod(u[1], v[1], P);
    }

    function _fp2Sub(uint256[2] memory u, uint256[2] memory v)
        internal
        pure
        returns (uint256[2] memory w)
    {
        w[0] = addmod(u[0], P - v[0], P);
        w[1] = addmod(u[1], P - v[1], P);
    }

    function _fp2Inv(uint256[2] memory u)
        internal
        pure
        returns (uint256[2] memory w)
    {
        // 1/(a + bi) = (a - bi) / (a^2 + b^2)
        uint256 norm = addmod(mulmod(u[0], u[0], P), mulmod(u[1], u[1], P), P);
        uint256 normInv = _modPow(norm, P - 2, P);
        w[0] = mulmod(u[0], normInv, P);
        // P - u[1]: correct negation for u[1] in (0, P); u[1] = 0 gives P,
        // which mulmod reduces to 0 — also correct.
        w[1] = mulmod(P - u[1], normInv, P);
    }

    function _onTwist(uint256[2] memory x, uint256[2] memory y)
        internal
        view
        returns (bool)
    {
        uint256[2] memory lhs = _fp2Mul(y, y);
        uint256[2] memory rhs = _fp2Add(
            _fp2Mul(_fp2Mul(x, x), x),
            twistB
        );
        return lhs[0] == rhs[0] && lhs[1] == rhs[1];
    }

    /// @dev Affine point addition on the twist curve. Callers guarantee
    ///      x1 != x2 (see the double-and-add analysis below).
    function _g2Add(
        uint256[2] memory x1, uint256[2] memory y1,
        uint256[2] memory x2, uint256[2] memory y2
    ) internal pure returns (uint256[2] memory x3, uint256[2] memory y3) {
        uint256[2] memory lam = _fp2Mul(_fp2Sub(y2, y1), _fp2Inv(_fp2Sub(x2, x1)));
        x3 = _fp2Sub(_fp2Mul(lam, lam), _fp2Add(x1, x2));
        y3 = _fp2Sub(_fp2Mul(lam, _fp2Sub(x1, x3)), y1);
    }

    function _g2Double(uint256[2] memory x, uint256[2] memory y)
        internal
        pure
        returns (uint256[2] memory x3, uint256[2] memory y3)
    {
        // lambda = 3x^2 / 2y
        uint256[2] memory x2 = _fp2Mul(x, x);
        uint256[2] memory lam = _fp2Mul(
            _fp2Add(_fp2Add(x2, x2), x2),
            _fp2Inv(_fp2Add(y, y))
        );
        x3 = _fp2Sub(_fp2Mul(lam, lam), _fp2Add(x, x));
        y3 = _fp2Sub(_fp2Mul(lam, _fp2Sub(x, x3)), y);
    }

    /// @dev G2 generator * k via double-and-add. For k < r the accumulator
    ///      never equals the doubling point (accumulator = G*m with
    ///      m < 2^j, doubling point = G*2^j), so the affine add is safe.
    function _g2Mul(uint256 k) internal view returns (uint256[2] memory rx, uint256[2] memory ry) {
        (uint256[2] memory x, uint256[2] memory y) = _g2Raw();
        bool hasResult = false;
        while (k > 0) {
            if (k & 1 == 1) {
                if (!hasResult) {
                    rx = x;
                    ry = y;
                    hasResult = true;
                } else {
                    (rx, ry) = _g2Add(rx, ry, x, y);
                }
            }
            (x, y) = _g2Double(x, y);
            k >>= 1;
        }
        assertTrue(_onTwist(rx, ry), "G2 scalar mul left the curve");
    }

    /// @dev G2 point for scalar k, in EIP-197 wire order (im, re).
    function _g2Wire(uint256 k) internal view returns (uint256[4] memory wire) {
        (uint256[2] memory x, uint256[2] memory y) = _g2Mul(k);
        wire = [x[1], x[0], y[1], y[0]];
    }

    // ────────────────────────────────
    //  Helpers: bytes + scalar math
    // ────────────────────────────────

    function _modInvR(uint256 a) internal pure returns (uint256) {
        return _modPow(a, R - 2, R); // Fermat: a^(r-2) mod r
    }

    function _modPow(uint256 base, uint256 exp, uint256 modulus)
        internal
        pure
        returns (uint256 result)
    {
        result = 1;
        base %= modulus;
        while (exp > 0) {
            if (exp & 1 == 1) result = mulmod(result, base, modulus);
            base = mulmod(base, base, modulus);
            exp >>= 1;
        }
    }

    function _writeWord(bytes memory buf, uint256 wordIndex, uint256 value) internal pure {
        assembly {
            mstore(add(buf, add(32, mul(wordIndex, 32))), value)
        }
    }

    function _readWord(bytes memory buf, uint256 wordIndex)
        internal
        pure
        returns (uint256 value)
    {
        assembly {
            value := mload(add(buf, add(32, mul(wordIndex, 32))))
        }
    }

    function _swapWords(bytes memory buf, uint256 i, uint256 j) internal pure {
        assembly {
            let a := mload(add(buf, add(32, mul(i, 32))))
            let b := mload(add(buf, add(32, mul(j, 32))))
            mstore(add(buf, add(32, mul(i, 32))), b)
            mstore(add(buf, add(32, mul(j, 32))), a)
        }
    }
}
