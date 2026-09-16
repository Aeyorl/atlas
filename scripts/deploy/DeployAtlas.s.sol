// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import {AgentRegistry} from "../../contracts/core/AgentRegistry.sol";
import {TaskManager} from "../../contracts/core/TaskManager.sol";
import {SettlementEngine} from "../../contracts/core/SettlementEngine.sol";
import {AtlasCore} from "../../contracts/core/AtlasCore.sol";

/// @title DeployAtlas — Deploy the Atlas Protocol coordination stack
/// @notice Deploys AgentRegistry, SettlementEngine, TaskManager, and AtlasCore,
///         wiring them together.
/// @dev Bridge is not implemented yet (interface-only upstream); it is passed
///      as a zero address until then. Deployment is circular between
///      TaskManager and SettlementEngine (each wants the other's address), so
///      both are constructed with the deployer as provisional authority and
///      wired via `setTaskManager` afterwards.
contract DeployAtlas is Script {
    function run() external {
        uint256 key = vm.envUint("DEPLOYER_KEY");
        vm.startBroadcast(key);

        AgentRegistry registry = new AgentRegistry();
        SettlementEngine settlement = new SettlementEngine(msg.sender);
        TaskManager taskManager = new TaskManager(address(registry), address(settlement), msg.sender);
        // bridge arrives in a later phase
        AtlasCore core = new AtlasCore(address(registry), address(taskManager), address(settlement), address(0));

        registry.setTaskManager(address(taskManager));
        settlement.setTaskManager(address(taskManager));

        vm.stopBroadcast();

        console.log("AgentRegistry:    ", address(registry));
        console.log("SettlementEngine: ", address(settlement));
        console.log("TaskManager:      ", address(taskManager));
        console.log("AtlasCore:        ", address(core));
        console.log("Atlas Protocol deployment complete");
    }
}
