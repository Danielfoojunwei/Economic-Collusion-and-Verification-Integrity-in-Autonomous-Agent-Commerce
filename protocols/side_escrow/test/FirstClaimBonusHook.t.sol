// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Test} from "forge-std/Test.sol";
import {Vm} from "forge-std/Vm.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {ERC8183} from "erc8183/contracts/ERC8183.sol";
import {MockUSDC} from "erc8183/contracts/mocks/MockUSDC.sol";
import {FirstClaimBonusHook} from "../src/FirstClaimBonusHook.sol";

contract FirstClaimBonusHookOfficialTest is Test {
    uint256 constant BUDGET = 20_000_000;
    uint256 constant FIRST = 10_000_000;
    uint256 constant BONUS = 5_000_000;
    bytes32 constant DIGEST = keccak256("invoice-350-cents");

    address admin = makeAddr("admin");
    address client = makeAddr("client");
    address provider = makeAddr("provider");
    address evaluator = makeAddr("evaluator");
    address outsider = makeAddr("outsider");

    ERC8183 core;
    MockUSDC token;
    FirstClaimBonusHook hook;
    uint256 jobId;

    function setUp() public {
        token = new MockUSDC();
        ERC8183 implementation = new ERC8183();
        ERC1967Proxy proxy = new ERC1967Proxy(
            address(implementation), abi.encodeCall(ERC8183.initialize, (admin, admin))
        );
        core = ERC8183(address(proxy));
        vm.startPrank(admin);
        core.setPaymentTokenAllowed(address(token), true);
        core.setPlatformFee(0, admin);
        core.setEvaluatorFee(1000);
        vm.stopPrank();
        token.mint(client, 2 * BUDGET);
        token.mint(provider, BONUS);
        vm.prank(client);
        token.approve(address(core), 2 * BUDGET);
        hook = new FirstClaimBonusHook(
            address(core), client, provider, evaluator, address(token), DIGEST
        );
        vm.prank(admin);
        core.setHookWhitelist(address(hook), true);
        vm.prank(client);
        jobId = core.createJob(
            provider, evaluator, uint48(block.timestamp + 3600), "invoice first claim",
            address(hook), 0
        );
        vm.prank(provider);
        core.setBudget(jobId, address(token), BUDGET, "");
        vm.prank(client);
        core.fund(jobId, address(token), BUDGET, "");
        vm.prank(client);
        hook.bindJob(jobId);
        vm.prank(provider);
        token.approve(address(hook), BONUS);
        vm.prank(provider);
        hook.fund();
        assertEq(uint8(hook.state()), uint8(FirstClaimBonusHook.State.Funded));
        assertEq(token.balanceOf(address(hook)), BONUS);
    }

    function _claim(bytes32 digest) private {
        vm.prank(provider);
        core.submitClaim(jobId, FIRST, digest, "");
    }

    function _approve(address actor, bytes32 digest) private {
        vm.prank(actor);
        core.approveClaim(jobId, FIRST, digest, "");
    }

    function testEvaluatorFirstApprovalReleasesBonusInSameOfficialTransaction() public {
        _claim(DIGEST);
        vm.recordLogs();
        _approve(evaluator, DIGEST);
        Vm.Log[] memory logs = vm.getRecordedLogs();
        bool officialApproval;
        bool bonusRelease;
        for (uint256 i; i < logs.length; ++i) {
            if (logs[i].emitter == address(core)
                && logs[i].topics[0] == keccak256("ClaimApproved(uint256,address,uint256,uint256,bytes32)")) {
                assertEq(uint256(logs[i].topics[1]), jobId);
                assertEq(address(uint160(uint256(logs[i].topics[2]))), evaluator);
                (uint256 cumulative, uint256 delta, bytes32 digest) =
                    abi.decode(logs[i].data, (uint256, uint256, bytes32));
                assertEq(cumulative, FIRST);
                assertEq(delta, FIRST);
                assertEq(digest, DIGEST);
                officialApproval = true;
            }
            if (logs[i].emitter == address(hook)
                && logs[i].topics[0] == keccak256("FirstClaimBonusReleased(uint256,address,uint256)")) {
                assertEq(uint256(logs[i].topics[1]), jobId);
                assertEq(address(uint160(uint256(logs[i].topics[2]))), evaluator);
                assertEq(abi.decode(logs[i].data, (uint256)), BONUS);
                bonusRelease = true;
            }
        }
        assertTrue(officialApproval && bonusRelease);
        assertEq(token.balanceOf(provider), 9_000_000);
        assertEq(token.balanceOf(evaluator), 1_000_000 + BONUS);
        assertEq(token.balanceOf(address(core)), 10_000_000);
        assertEq(token.balanceOf(address(hook)), 0);
        assertEq(uint8(hook.state()), uint8(FirstClaimBonusHook.State.Released));

        vm.prank(provider);
        core.submit(jobId, DIGEST, "");
        vm.prank(evaluator);
        core.reject(jobId, keccak256("final fail"), "");
        assertEq(token.balanceOf(client), 30_000_000);
        assertEq(token.balanceOf(provider), 9_000_000);
        assertEq(token.balanceOf(evaluator), 6_000_000);
        assertEq(uint8(hook.state()), uint8(FirstClaimBonusHook.State.Released));
    }

    function testFirstClaimRejectionRefundsProviderBonus() public {
        _claim(DIGEST);
        vm.prank(evaluator);
        core.rejectClaim(jobId, FIRST, DIGEST, keccak256("bad interim"), "");
        assertEq(token.balanceOf(provider), BONUS);
        assertEq(token.balanceOf(evaluator), 0);
        assertEq(token.balanceOf(address(hook)), 0);
        assertEq(token.balanceOf(address(core)), BUDGET);
        assertEq(uint8(hook.state()), uint8(FirstClaimBonusHook.State.Refunded));
        vm.prank(provider);
        core.submit(jobId, DIGEST, "");
        vm.prank(evaluator);
        core.reject(jobId, keccak256("bad final"), "");
        assertEq(token.balanceOf(client), 2 * BUDGET);
    }

    function testClientDirectSettlementCannotSpoofEvaluatorApproval() public {
        vm.prank(client);
        core.settleClaim(jobId, FIRST, DIGEST, "");
        assertEq(core.getJob(jobId).settledAmount, FIRST);
        assertEq(token.balanceOf(provider), 9_000_000 + BONUS);
        assertEq(token.balanceOf(evaluator), 1_000_000);
        assertEq(token.balanceOf(address(hook)), 0);
        assertEq(uint8(hook.state()), uint8(FirstClaimBonusHook.State.Refunded));
    }

    function testClientApprovalOfProviderClaimCannotSpoofEvaluator() public {
        _claim(DIGEST);
        _approve(client, DIGEST);
        assertEq(core.getJob(jobId).settledAmount, FIRST);
        assertEq(token.balanceOf(provider), 9_000_000 + BONUS);
        assertEq(token.balanceOf(evaluator), 1_000_000);
        assertEq(uint8(hook.state()), uint8(FirstClaimBonusHook.State.Refunded));
    }

    function testWrongFirstClaimCannotEarnBonusLater() public {
        _claim(keccak256("different report"));
        assertEq(uint8(hook.state()), uint8(FirstClaimBonusHook.State.Refunded));
        assertEq(token.balanceOf(provider), BONUS);
        _approve(evaluator, keccak256("different report"));
        assertEq(token.balanceOf(evaluator), 1_000_000);
        assertEq(token.balanceOf(address(hook)), 0);
    }

    function testSecondPaymentCannotClaimFirstApprovalBonus() public {
        vm.prank(client);
        core.settleClaim(jobId, 5_000_000, DIGEST, "");
        assertEq(uint8(hook.state()), uint8(FirstClaimBonusHook.State.Refunded));
        _claim(DIGEST);
        _approve(evaluator, DIGEST);
        assertEq(token.balanceOf(evaluator), 1_000_000); // Two native 500k fees.
        assertEq(token.balanceOf(provider), BONUS + 9_000_000);
    }

    function testExternalCallbackAndPrematureRefundCannotSpoofCore() public {
        vm.prank(outsider);
        vm.expectRevert(FirstClaimBonusHook.Unauthorized.selector);
        hook.beforeAction(jobId, bytes4(keccak256("approveClaim(uint256,uint256,bytes32,bytes)")),
                          abi.encode(evaluator, FIRST, DIGEST, bytes("")));
        vm.prank(outsider);
        vm.expectRevert(FirstClaimBonusHook.Unauthorized.selector);
        hook.afterAction(jobId, bytes4(keccak256("approveClaim(uint256,uint256,bytes32,bytes)")),
                         abi.encode(evaluator, FIRST, DIGEST, bytes("")));
        vm.expectRevert(FirstClaimBonusHook.NotTerminal.selector);
        hook.refundAfterTerminal();
        assertEq(token.balanceOf(address(hook)), BONUS);
    }

    function testOnlyProviderFundsOnceAndCannotReplayPayout() public {
        vm.prank(provider);
        vm.expectRevert(FirstClaimBonusHook.WrongState.selector);
        hook.fund();
        _claim(DIGEST);
        _approve(evaluator, DIGEST);
        vm.expectRevert(FirstClaimBonusHook.WrongState.selector);
        hook.refundAfterTerminal();
        assertEq(token.balanceOf(evaluator), BONUS + 1_000_000);
    }

    function testNoClaimFinalSubmissionRefundsBonus() public {
        vm.prank(provider);
        core.submit(jobId, DIGEST, "");
        assertEq(uint8(hook.state()), uint8(FirstClaimBonusHook.State.Refunded));
        assertEq(token.balanceOf(provider), BONUS);
        assertEq(token.balanceOf(evaluator), 0);
        vm.prank(evaluator);
        core.complete(jobId, keccak256("final accepted"), "");
        assertEq(token.balanceOf(evaluator), 2_000_000); // Native fee, no side bonus.
    }

    function testExpiryRefundLivenessWhenCoreRefundIsNotHookable() public {
        vm.warp(block.timestamp + 3601);
        vm.prank(outsider);
        core.claimRefund(jobId);
        assertEq(uint8(hook.state()), uint8(FirstClaimBonusHook.State.Funded));
        hook.refundAfterTerminal();
        assertEq(uint8(hook.state()), uint8(FirstClaimBonusHook.State.Refunded));
        assertEq(token.balanceOf(provider), BONUS);
        assertEq(token.balanceOf(address(hook)), 0);
    }

    function testAdminDetachCanStillRefundAfterTerminal() public {
        uint256[] memory ids = new uint256[](1);
        ids[0] = jobId;
        vm.prank(admin);
        core.batchDetachHook(ids);
        assertEq(core.getJob(jobId).hook, address(0));
        vm.prank(provider);
        core.submit(jobId, DIGEST, "");
        vm.prank(evaluator);
        core.reject(jobId, keccak256("terminal rejection"), "");
        hook.refundAfterTerminal();
        assertEq(token.balanceOf(provider), BONUS);
        assertEq(token.balanceOf(address(hook)), 0);
        vm.expectRevert(FirstClaimBonusHook.WrongState.selector);
        hook.refundAfterTerminal();
    }
}
