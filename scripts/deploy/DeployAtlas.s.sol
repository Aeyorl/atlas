// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import {AgentRegistry} from "../../contracts/core/AgentRegistry.sol";
import {TaskManager} from "../../contracts/core/TaskManager.sol";
import {AtlasCore} from "../../contracts/core/AtlasCore.sol";

/// @title DeployAtlas — Deploy the Atlas Protocol coordination stack
/// @notice Deploys AgentRegistry + TaskManager and wires them into AtlasCore.
/// @dev SettlementEngine and Bridge are not implemented yet (interface-only
///      upstream); they are deployed in later phases and passed here as zero
///      addresses until then. After deployment, grant the TaskManager
///      reputation rights on the registry via `setTaskManager`.
contract DeployAtlas is Script {
    function run() external {
        uint256 key = vm.envUint("DEPLOYER_KEY");
        vm.startBroadcast(key);

        AgentRegistry registry = new AgentRegistry();
        TaskManager taskManager = new TaskManager(address(registry), msg.sender);
        // settlementEngine and bridge arrive in later phases
        AtlasCore core = new AtlasCore(address(registry), address(taskManager), address(0), address(0));

        registry.setTaskManager(address(taskManager));

        vm.stopBroadcast();

        console.log("AgentRegistry:", address(registry));
        console.log("TaskManager:  ", address(taskManager));
        console.log("AtlasCore:    ", address(core));
        console.log("Atlas Protocol deployment complete");
    }
}
