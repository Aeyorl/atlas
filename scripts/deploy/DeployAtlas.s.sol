// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import {AgentRegistry} from "../../contracts/core/AgentRegistry.sol";
import {TaskManager} from "../../contracts/core/TaskManager.sol";
import {SettlementEngine} from "../../contracts/core/SettlementEngine.sol";
import {AtlasCore} from "../../contracts/core/AtlasCore.sol";
import {AtlasBridge} from "../../contracts/core/AtlasBridge.sol";

/// @title DeployAtlas — Deploy the Atlas Protocol coordination stack
/// @notice Deploys AgentRegistry, SettlementEngine, TaskManager, AtlasCore,
///         and AtlasBridge, wiring them together.
/// @dev Deployment is circular between TaskManager and SettlementEngine (each
///      wants the other's address), so both are constructed with the deployer
///      as provisional authority and wired via `setTaskManager` afterwards.
///      AtlasBridge needs AtlasCore for guardian checks, but AtlasCore wants
///      the bridge address — same circularity, resolved the same way via
///      `setCore`. One bridge instance per ecosystem: pass this chain's
///      ecosystem via the ATLAS_ECOSYSTEM (robinhood-chain | evm | virtuals)
///      env var; it defaults to EVM.
contract DeployAtlas is Script {
    function run() external {
        uint256 key = vm.envUint("DEPLOYER_KEY");
        bytes32 ecosystem = _ecosystemFromEnv();

        vm.startBroadcast(key);

        AgentRegistry registry = new AgentRegistry();
        SettlementEngine settlement = new SettlementEngine(msg.sender);
        TaskManager taskManager = new TaskManager(address(registry), address(settlement), msg.sender);
        AtlasBridge bridge = new AtlasBridge(ecosystem, msg.sender);
        AtlasCore core = new AtlasCore(address(registry), address(taskManager), address(settlement), address(bridge));

        registry.setTaskManager(address(taskManager));
        settlement.setTaskManager(address(taskManager));
        bridge.setCore(address(core));

        vm.stopBroadcast();

        console.log("AgentRegistry:    ", address(registry));
        console.log("SettlementEngine: ", address(settlement));
        console.log("TaskManager:      ", address(taskManager));
        console.log("AtlasBridge:      ", address(bridge));
        console.log("AtlasCore:        ", address(core));
        console.log("Atlas Protocol deployment complete");
    }

    function _ecosystemFromEnv() internal view returns (bytes32) {
        string memory name = vm.envOr("ATLAS_ECOSYSTEM", string("evm"));
        bytes32 encoded = keccak256(abi.encodePacked(name));
        if (encoded == AtlasBridge.ECOSYSTEM_ROBINHOOD) return AtlasBridge.ECOSYSTEM_ROBINHOOD;
        if (encoded == AtlasBridge.ECOSYSTEM_EVM) return AtlasBridge.ECOSYSTEM_EVM;
        if (encoded == AtlasBridge.ECOSYSTEM_VIRTUALS) return AtlasBridge.ECOSYSTEM_VIRTUALS;
        revert("DeployAtlas: unknown ATLAS_ECOSYSTEM");
    }
}
