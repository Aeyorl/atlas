// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {AtlasCore} from "../core/AtlasCore.sol";
import {IAtlasCore} from "../interfaces/IAtlasCore.sol";

contract AtlasCoreTest is Test {
    AtlasCore internal core;

    address internal governor = makeAddr("governor");
    address internal guardian = makeAddr("guardian");
    address internal alice    = makeAddr("alice");

    function setUp() public {
        vm.prank(governor);
        // Dependencies are interface-only upstream; not called in these paths.
        core = new AtlasCore(address(0), address(0), address(0), address(0));
    }

    // ────────────────────────────────
    //  Construction
    // ────────────────────────────────

    function test_ConstructorSetsDeployerAsGovernor() public view {
        assertEq(core.governor(), governor);
        assertEq(core.protocolVersion(), 1);
        assertFalse(core.paused());
        assertEq(core.getGuardianCount(), 0);
    }

    // ────────────────────────────────
    //  Guardian registration
    // ────────────────────────────────

    function test_RegisterGuardian() public {
        uint256 stake = core.MIN_GUARDIAN_STAKE();

        vm.prank(guardian);
        vm.expectEmit(true, false, false, true);
        emit IAtlasCore.GuardianRegistered(guardian, stake);
        core.registerGuardian(stake);

        assertEq(core.getGuardianCount(), 1);
        (address staker, uint256 stakeAmt, bool active,,) = core.guardians(guardian);
        assertEq(staker, guardian);
        assertEq(stakeAmt, stake);
        assertTrue(active);
    }

    function test_RegisterGuardian_RevertInsufficientStake() public {
        uint256 stake = core.MIN_GUARDIAN_STAKE(); // read before expectRevert — inline getter would consume it
        vm.prank(guardian);
        vm.expectRevert("AtlasCore: insufficient stake");
        core.registerGuardian(stake - 1);
    }

    function test_RegisterGuardian_RevertAlreadyGuardian() public {
        uint256 stake = core.MIN_GUARDIAN_STAKE();
        vm.startPrank(guardian);
        core.registerGuardian(stake);
        vm.expectRevert("AtlasCore: already guardian");
        core.registerGuardian(stake);
        vm.stopPrank();
    }

    function test_RegisterGuardian_RevertWhenPaused() public {
        vm.prank(governor);
        core.pause();

        uint256 stake = core.MIN_GUARDIAN_STAKE();
        vm.prank(guardian);
        vm.expectRevert("AtlasCore: paused");
        core.registerGuardian(stake);
    }

    // ────────────────────────────────
    //  Pause / unpause (governor only)
    // ────────────────────────────────

    function test_PauseUnpause_ByGovernor() public {
        vm.startPrank(governor);
        vm.expectEmit(true, false, false, false);
        emit IAtlasCore.ProtocolPaused(governor);
        core.pause();
        assertTrue(core.paused());

        vm.expectEmit(true, false, false, false);
        emit IAtlasCore.ProtocolUnpaused(governor);
        core.unpause();
        assertFalse(core.paused());
        vm.stopPrank();
    }

    function test_Pause_RevertNotGovernor() public {
        vm.prank(alice);
        vm.expectRevert("AtlasCore: not governor");
        core.pause();
    }

    function test_Unpause_RevertNotGovernor() public {
        vm.prank(governor);
        core.pause();

        vm.prank(alice);
        vm.expectRevert("AtlasCore: not governor");
        core.unpause();
    }

    function test_Pause_RevertAlreadyPaused() public {
        vm.startPrank(governor);
        core.pause();
        vm.expectRevert("AtlasCore: already paused");
        core.pause();
        vm.stopPrank();
    }

    function test_Unpause_RevertNotPaused() public {
        vm.prank(governor);
        vm.expectRevert("AtlasCore: not paused");
        core.unpause();
    }

    // ────────────────────────────────
    //  Slashing (governor only)
    // ────────────────────────────────

    function test_SlashGuardian() public {
        uint256 stake = core.MIN_GUARDIAN_STAKE();
        uint256 slash = core.SLASH_PERCENTAGE(); // 50% in bps semantics; used here as raw amount

        vm.prank(guardian);
        core.registerGuardian(stake);

        vm.prank(governor);
        vm.expectEmit(true, false, false, true);
        emit IAtlasCore.GuardianSlashed(guardian, slash);
        core.slashGuardian(guardian, slash);

        (, uint256 stakeAfter,,, uint256 slashedCount) = core.guardians(guardian);
        assertEq(stakeAfter, stake - slash);
        assertEq(slashedCount, 1);
    }

    function test_SlashGuardian_RevertNotGovernor() public {
        vm.prank(guardian);
        core.registerGuardian(core.MIN_GUARDIAN_STAKE());

        vm.prank(alice);
        vm.expectRevert("AtlasCore: not governor");
        core.slashGuardian(guardian, 1 ether);
    }

    function test_SlashGuardian_RevertInsufficientStake() public {
        vm.prank(guardian);
        core.registerGuardian(core.MIN_GUARDIAN_STAKE());

        uint256 stake = core.MIN_GUARDIAN_STAKE();
        vm.prank(governor);
        vm.expectRevert("AtlasCore: insufficient stake");
        core.slashGuardian(guardian, stake + 1);
    }

    // ────────────────────────────────
    //  Governor rotation
    // ────────────────────────────────

    function test_SetGovernor_RotatesAuthority() public {
        vm.prank(governor);
        vm.expectEmit(true, true, false, false);
        emit IAtlasCore.GovernorUpdated(governor, alice);
        core.setGovernor(alice);
        assertEq(core.governor(), alice);

        // Old governor loses authority...
        vm.prank(governor);
        vm.expectRevert("AtlasCore: not governor");
        core.pause();

        // ...new governor gains it.
        vm.prank(alice);
        core.pause();
        assertTrue(core.paused());
    }

    function test_SetGovernor_RevertNotGovernor() public {
        vm.prank(alice);
        vm.expectRevert("AtlasCore: not governor");
        core.setGovernor(alice);
    }

    function test_SetGovernor_RevertZeroAddress() public {
        vm.prank(governor);
        vm.expectRevert("AtlasCore: zero governor");
        core.setGovernor(address(0));
    }
}
