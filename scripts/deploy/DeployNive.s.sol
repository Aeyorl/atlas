// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import {NiveBridge} from "../../contracts/core/NiveBridge.sol";
import {AgentRegistry} from "../../contracts/core/AgentRegistry.sol";
import {TaskManager} from "../../contracts/core/TaskManager.sol";
import {SettlementEngine} from "../../contracts/core/SettlementEngine.sol";
import {NiveCore} from "../../contracts/core/NiveCore.sol";
import {NiveBridge} from "../../contracts/core/NiveBridge.sol";
import {NiveVerifier} from "../../contracts/core/NiveVerifier.sol";

/// @title DeployNive — Deploy the Nive Protocol coordination stack
/// @notice Deploys AgentRegistry, SettlementEngine, TaskManager, NiveCore,
///         and NiveBridge, wiring them together.
/// @dev Deployment is circular between TaskManager and SettlementEngine (each
///      wants the other's address), so both are constructed with the deployer
///      as provisional authority and wired via `setTaskManager` afterwards.
///      NiveBridge needs NiveCore for guardian checks, but NiveCore wants
///      the bridge address — same circularity, resolved the same way via
///      `setCore`. One bridge instance per ecosystem: pass this chain's
///      ecosystem via the NIVE_ECOSYSTEM (robinhood-chain | evm | virtuals)
///      env var; it defaults to EVM.
///
///      ZK verification (optional): set NIVE_VK_JSON to the path of a JSON
///      file `{"vk": [alpha_x, alpha_y, beta_im_x, beta_re_x, beta_im_y,
///      beta_re_y, gamma..., delta..., ic0_x, ic0_y, ic1_x, ic1_y, ...]}`
///      (all decimal words, EIP-197 (imaginary, real) order for G2, IC flat).
///      When set, an {NiveVerifier} is deployed and enabled on the
///      SettlementEngine (ZK-gated settlement). When unset, settlement runs
///      in governor-trust mode and `setVerifier` can be called later.
contract DeployNive is Script {
    /// @dev Ecosystem ids must match NiveBridge's constants. Declared locally
    ///      because solc does not resolve `NiveBridge.ECOSYSTEM_*` member
    ///      access from outside the contract; any drift reverts loudly in the
    ///      bridge constructor's ecosystem validation anyway.
    bytes32 constant ECOSYSTEM_ROBINHOOD = keccak256("robinhood-chain");
    bytes32 constant ECOSYSTEM_EVM       = keccak256("evm");
    bytes32 constant ECOSYSTEM_VIRTUALS  = keccak256("virtuals");

    function run() external {
        uint256 key = vm.envUint("DEPLOYER_KEY");
        // Derive the broadcast sender explicitly. Inside a Script's run(),
        // top-level `msg.sender` is forge's DEFAULT script sender
        // (0x1804c8AB1F12E6bbf3894dDe8a6e5F0402f76dCd), NOT vm.addr(key) —
        // using it here would mint provisional-governor roles to an address
        // that can never sign the follow-up admin calls.
        address deployer = vm.addr(key);
        bytes32 ecosystem = _ecosystemFromEnv();

        vm.startBroadcast(key);

        AgentRegistry registry = new AgentRegistry();
        SettlementEngine settlement = new SettlementEngine(deployer);
        TaskManager taskManager = new TaskManager(address(registry), address(settlement), deployer);
        NiveBridge bridge = new NiveBridge(ecosystem, deployer);
        NiveCore core = new NiveCore(address(registry), address(taskManager), address(settlement), address(bridge));

        registry.setTaskManager(address(taskManager));
        settlement.setTaskManager(address(taskManager));
        bridge.setCore(address(core));

        // Optional: ZK-gated settlement when a verification key is provided.
        _deployVerifierIfConfigured(settlement);

        vm.stopBroadcast();

        console.log("AgentRegistry:    ", address(registry));
        console.log("SettlementEngine: ", address(settlement));
        console.log("TaskManager:      ", address(taskManager));
        console.log("NiveBridge:      ", address(bridge));
        console.log("NiveCore:        ", address(core));
        console.log("Nive Protocol deployment complete");
    }

    function _ecosystemFromEnv() internal view returns (bytes32) {
        string memory name = vm.envOr("NIVE_ECOSYSTEM", string("evm"));
        bytes32 encoded = keccak256(abi.encodePacked(name));
        if (encoded == ECOSYSTEM_ROBINHOOD) return ECOSYSTEM_ROBINHOOD;
        if (encoded == ECOSYSTEM_EVM) return ECOSYSTEM_EVM;
        if (encoded == ECOSYSTEM_VIRTUALS) return ECOSYSTEM_VIRTUALS;
        revert("DeployNive: unknown NIVE_ECOSYSTEM");
    }

    /// @dev Verifier deployment lives in a helper: the constructor takes 5
    ///      arrays, and a multi-value return cannot be spread into a `new`
    ///      expression — the tuple must be assigned to locals first.
    function _deployVerifierIfConfigured(SettlementEngine settlement) internal {
        string memory vkPath = vm.envOr("NIVE_VK_JSON", string(""));
        if (bytes(vkPath).length == 0) {
            console.log("NiveVerifier:    skipped (NIVE_VK_JSON not set)");
            return;
        }
        (
            uint256[2] memory alpha1,
            uint256[4] memory beta2,
            uint256[4] memory gamma2,
            uint256[4] memory delta2,
            uint256[2][] memory ic
        ) = _parseVk(vkPath);
        NiveVerifier verifier = new NiveVerifier(alpha1, beta2, gamma2, delta2, ic);
        settlement.setVerifier(address(verifier));
        console.log("NiveVerifier:    ", address(verifier));
    }

    /// @dev Parses the verification key from a JSON file into the constructor
    ///      tuple. Layout of the flat `vk` array (all decimal words):
    ///      [0..1] alpha1 (G1 x,y) · [2..5] beta2 (G2, EIP-197 im/re order)
    ///      [6..9] gamma2 · [10..13] delta2 · [14..] IC flat (x,y per input).
    function _parseVk(string memory path)
        internal
        view
        returns (
            uint256[2] memory alpha1,
            uint256[4] memory beta2,
            uint256[4] memory gamma2,
            uint256[4] memory delta2,
            uint256[2][] memory ic
        )
    {
        uint256[] memory vk = vm.parseJsonUintArray(vm.readFile(path), ".vk");
        if (vk.length < 16 || (vk.length - 14) % 2 != 0) {
            revert("DeployNive: malformed verification key array");
        }
        alpha1 = [vk[0], vk[1]];
        beta2 = [vk[2], vk[3], vk[4], vk[5]];
        gamma2 = [vk[6], vk[7], vk[8], vk[9]];
        delta2 = [vk[10], vk[11], vk[12], vk[13]];

        uint256 inputCount = (vk.length - 14) / 2;
        ic = new uint256[2][](inputCount);
        for (uint256 i = 0; i < inputCount; i++) {
            ic[i] = [vk[14 + 2 * i], vk[15 + 2 * i]];
        }
    }
}
