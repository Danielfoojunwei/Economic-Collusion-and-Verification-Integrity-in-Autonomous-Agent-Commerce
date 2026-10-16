// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Test} from "forge-std/Test.sol";
import {Vm} from "forge-std/Vm.sol";
import {ERC1967Proxy} from "@openzeppelin/contracts/proxy/ERC1967/ERC1967Proxy.sol";
import {ERC8183} from "erc8183/contracts/ERC8183.sol";
import {MockUSDC} from "erc8183/contracts/mocks/MockUSDC.sol";
import {IERC8183JobView, ProviderAuditorBonusEscrow} from "../src/ProviderAuditorBonusEscrow.sol";

contract MockJobCore is IERC8183JobView {
    mapping(uint256 => Job) private jobs;

    function setJob(uint256 id, address provider, address auditor, address token, JobStatus status) external {
        jobs[id] = Job({
            client: address(0x1111),
            status: status,
            provider: provider,
            expiredAt: uint48(block.timestamp + 3600),
            evaluator: auditor,
            submittedAt: 0,
            budget: 20_000_000,
            hook: address(0),
            paymentToken: token,
            providerAgentId: 0,
            description: "mock job",
            settledAmount: 0,
            payoutReceiver: address(0)
        });
    }

    function setStatus(uint256 id, JobStatus status) external {
        jobs[id].status = status;
    }

    function setEvaluator(uint256 id, address evaluator) external {
        jobs[id].evaluator = evaluator;
    }

    function getJob(uint256 id) external view returns (Job memory) {
        return jobs[id];
    }
}

contract CallbackUSDC is MockUSDC {
    address public escrow;
    bool public attempted;
    bool public blocked;

    function setEscrow(address escrow_) external {
        escrow = escrow_;
    }

    function transfer(address to, uint256 amount) public override returns (bool) {
        if (msg.sender == escrow && !attempted) {
            attempted = true;
            (bool success,) = escrow.call(abi.encodeWithSignature("settle()"));
            blocked = !success;
        }
        return super.transfer(to, amount);
    }
}

contract FeeToken is MockUSDC {
    function _update(address from, address to, uint256 amount) internal override {
        if (from != address(0) && to != address(0)) {
            uint256 fee = amount / 10;
            super._update(from, to, amount - fee);
            super._update(from, address(0), fee);
        } else {
            super._update(from, to, amount);
        }
    }
}

contract ProviderAuditorBonusEscrowMockTest is Test {
    uint256 constant JOB_ID = 17;
    uint256 constant BONUS = 5_000_000;

    address provider = makeAddr("provider");
    address auditor = makeAddr("auditor");
    address stranger = makeAddr("stranger");

    MockJobCore core;
    MockUSDC token;
    ProviderAuditorBonusEscrow escrow;

    function setUp() public {
        core = new MockJobCore();
        token = new MockUSDC();
        core.setJob(JOB_ID, provider, auditor, address(token), IERC8183JobView.JobStatus.Funded);
        escrow = _deploy(address(token), JOB_ID, provider, auditor, BONUS, uint48(block.timestamp + 1800));
        token.mint(provider, BONUS);
        vm.prank(provider);
        token.approve(address(escrow), BONUS);
    }

    function _deploy(
        address token_,
        uint256 jobId_,
        address provider_,
        address auditor_,
        uint256 amount_,
        uint48 deadline_
    ) internal returns (ProviderAuditorBonusEscrow) {
        return new ProviderAuditorBonusEscrow(address(core), jobId_, provider_, auditor_, token_, amount_, deadline_);
    }

    function _fund() internal {
        vm.prank(provider);
        escrow.fund();
    }

    function testCompletedPaysBoundAuditorOnceWithNativeEvent() public {
        vm.recordLogs();
        _fund();
        Vm.Log[] memory fundingLogs = vm.getRecordedLogs();
        bytes32 fundingSig = keccak256("BonusFunded(uint256,address,address,address,uint256)");
        bool fundingSeen;
        for (uint256 i; i < fundingLogs.length; ++i) {
            if (fundingLogs[i].emitter == address(escrow) && fundingLogs[i].topics[0] == fundingSig) {
                assertEq(uint256(fundingLogs[i].topics[1]), JOB_ID);
                assertEq(address(uint160(uint256(fundingLogs[i].topics[2]))), provider);
                assertEq(address(uint160(uint256(fundingLogs[i].topics[3]))), auditor);
                (address receiptToken, uint256 amount) = abi.decode(fundingLogs[i].data, (address, uint256));
                assertEq(receiptToken, address(token));
                assertEq(amount, BONUS);
                fundingSeen = true;
            }
        }
        assertTrue(fundingSeen);
        assertEq(token.balanceOf(address(escrow)), BONUS);
        assertEq(token.balanceOf(provider), 0);

        core.setStatus(JOB_ID, IERC8183JobView.JobStatus.Completed);
        vm.recordLogs();
        vm.prank(stranger);
        escrow.settle();
        Vm.Log[] memory settlementLogs = vm.getRecordedLogs();
        bytes32 settlementSig = keccak256("BonusSettled(uint256,address,uint256,uint8)");
        bool settlementSeen;
        for (uint256 i; i < settlementLogs.length; ++i) {
            if (settlementLogs[i].emitter == address(escrow) && settlementLogs[i].topics[0] == settlementSig) {
                assertEq(uint256(settlementLogs[i].topics[1]), JOB_ID);
                assertEq(address(uint160(uint256(settlementLogs[i].topics[2]))), auditor);
                (uint256 amount, uint8 status) = abi.decode(settlementLogs[i].data, (uint256, uint8));
                assertEq(amount, BONUS);
                assertEq(status, uint8(IERC8183JobView.JobStatus.Completed));
                settlementSeen = true;
            }
        }
        assertTrue(settlementSeen);
        assertEq(token.balanceOf(auditor), BONUS);
        assertEq(token.balanceOf(address(escrow)), 0);
        assertEq(uint8(escrow.state()), uint8(ProviderAuditorBonusEscrow.EscrowState.Settled));
        vm.expectRevert(ProviderAuditorBonusEscrow.WrongState.selector);
        escrow.settle();
    }

    function testRejectedAndExpiredRefundProvider() public {
        _fund();
        core.setStatus(JOB_ID, IERC8183JobView.JobStatus.Rejected);
        escrow.settle();
        assertEq(token.balanceOf(provider), BONUS);
        assertEq(token.balanceOf(auditor), 0);

        MockJobCore otherCore = new MockJobCore();
        otherCore.setJob(JOB_ID, provider, auditor, address(token), IERC8183JobView.JobStatus.Funded);
        ProviderAuditorBonusEscrow otherEscrow = new ProviderAuditorBonusEscrow(
            address(otherCore), JOB_ID, provider, auditor, address(token), BONUS, uint48(block.timestamp + 1800)
        );
        vm.prank(provider);
        token.approve(address(otherEscrow), BONUS);
        vm.prank(provider);
        otherEscrow.fund();
        otherCore.setStatus(JOB_ID, IERC8183JobView.JobStatus.Expired);
        otherEscrow.settle();
        assertEq(token.balanceOf(provider), BONUS);
        assertEq(token.balanceOf(auditor), 0);
    }

    function testWrongJobCannotSelectStatus() public {
        _fund();
        core.setJob(JOB_ID + 1, provider, auditor, address(token), IERC8183JobView.JobStatus.Completed);
        vm.expectRevert(ProviderAuditorBonusEscrow.WrongJobStatus.selector);
        escrow.settle();
        assertEq(token.balanceOf(address(escrow)), BONUS);
    }

    function testOnlyProviderMayFundAndOnlyOnce() public {
        vm.prank(stranger);
        vm.expectRevert(ProviderAuditorBonusEscrow.Unauthorized.selector);
        escrow.fund();
        _fund();
        vm.prank(provider);
        vm.expectRevert(ProviderAuditorBonusEscrow.WrongState.selector);
        escrow.fund();
    }

    function testCannotSettleBeforeFundingOrTerminalStatus() public {
        vm.expectRevert(ProviderAuditorBonusEscrow.WrongState.selector);
        escrow.settle();
        _fund();
        vm.expectRevert(ProviderAuditorBonusEscrow.WrongJobStatus.selector);
        escrow.settle();
        core.setStatus(JOB_ID, IERC8183JobView.JobStatus.Submitted);
        vm.expectRevert(ProviderAuditorBonusEscrow.WrongJobStatus.selector);
        escrow.settle();
    }

    function testCannotFundAfterAuditorHasCompletedJob() public {
        core.setStatus(JOB_ID, IERC8183JobView.JobStatus.Completed);
        vm.prank(provider);
        vm.expectRevert(ProviderAuditorBonusEscrow.WrongJobStatus.selector);
        escrow.fund();
        assertEq(token.balanceOf(address(escrow)), 0);
        assertEq(uint8(escrow.state()), uint8(ProviderAuditorBonusEscrow.EscrowState.Unfunded));
    }

    function testBadBindingAndAmountRejected() public {
        vm.expectRevert(ProviderAuditorBonusEscrow.InvalidBinding.selector);
        _deploy(address(token), JOB_ID + 1, provider, auditor, BONUS, uint48(block.timestamp + 1800));
        vm.expectRevert(ProviderAuditorBonusEscrow.InvalidBinding.selector);
        _deploy(address(token), JOB_ID, stranger, auditor, BONUS, uint48(block.timestamp + 1800));
        vm.expectRevert(ProviderAuditorBonusEscrow.InvalidBinding.selector);
        _deploy(address(token), JOB_ID, provider, stranger, BONUS, uint48(block.timestamp + 1800));
        vm.expectRevert(ProviderAuditorBonusEscrow.InvalidBinding.selector);
        _deploy(address(core), JOB_ID, provider, auditor, BONUS, uint48(block.timestamp + 1800));
        vm.expectRevert(ProviderAuditorBonusEscrow.InvalidAmount.selector);
        _deploy(address(token), JOB_ID, provider, auditor, 0, uint48(block.timestamp + 1800));
        vm.expectRevert(ProviderAuditorBonusEscrow.InvalidAmount.selector);
        _deploy(address(token), JOB_ID, provider, auditor, 20_000_001, uint48(block.timestamp + 1800));
    }

    function testFundingDeadlineAndJobExpiry() public {
        vm.expectRevert(ProviderAuditorBonusEscrow.InvalidDeadline.selector);
        _deploy(address(token), JOB_ID, provider, auditor, BONUS, uint48(block.timestamp + 3601));
        vm.warp(block.timestamp + 1800);
        vm.prank(provider);
        vm.expectRevert(ProviderAuditorBonusEscrow.InvalidDeadline.selector);
        escrow.fund();
    }

    function testChangedJobRecipientCannotStealBonus() public {
        _fund();
        core.setEvaluator(JOB_ID, stranger);
        core.setStatus(JOB_ID, IERC8183JobView.JobStatus.Completed);
        vm.expectRevert(ProviderAuditorBonusEscrow.InvalidBinding.selector);
        escrow.settle();
        assertEq(token.balanceOf(stranger), 0);
        assertEq(token.balanceOf(address(escrow)), BONUS);
    }

    function testUnderapprovalAndFeeOnTransferCannotCreateFalseFundingReceipt() public {
        vm.prank(provider);
        token.approve(address(escrow), 0);
        vm.prank(provider);
        vm.expectRevert();
        escrow.fund();
        assertEq(uint8(escrow.state()), uint8(ProviderAuditorBonusEscrow.EscrowState.Unfunded));

        FeeToken feeToken = new FeeToken();
        core.setJob(JOB_ID + 1, provider, auditor, address(feeToken), IERC8183JobView.JobStatus.Funded);
        ProviderAuditorBonusEscrow feeEscrow =
            _deploy(address(feeToken), JOB_ID + 1, provider, auditor, BONUS, uint48(block.timestamp + 1800));
        feeToken.mint(provider, BONUS);
        vm.prank(provider);
        feeToken.approve(address(feeEscrow), BONUS);
        vm.prank(provider);
        vm.expectRevert(ProviderAuditorBonusEscrow.UnexpectedFundedAmount.selector);
        feeEscrow.fund();
        assertEq(feeToken.balanceOf(address(feeEscrow)), 0);
        assertEq(uint8(feeEscrow.state()), uint8(ProviderAuditorBonusEscrow.EscrowState.Unfunded));
    }

    function testTokenCallbackCannotReenterSettlement() public {
        CallbackUSDC callbackToken = new CallbackUSDC();
        core.setJob(JOB_ID + 1, provider, auditor, address(callbackToken), IERC8183JobView.JobStatus.Funded);
        ProviderAuditorBonusEscrow callbackEscrow =
            _deploy(address(callbackToken), JOB_ID + 1, provider, auditor, BONUS, uint48(block.timestamp + 1800));
        callbackToken.setEscrow(address(callbackEscrow));
        callbackToken.mint(provider, BONUS);
        vm.prank(provider);
        callbackToken.approve(address(callbackEscrow), BONUS);
        vm.prank(provider);
        callbackEscrow.fund();
        core.setStatus(JOB_ID + 1, IERC8183JobView.JobStatus.Completed);
        callbackEscrow.settle();
        assertTrue(callbackToken.attempted());
        assertTrue(callbackToken.blocked());
        assertEq(callbackToken.balanceOf(auditor), BONUS);
        assertEq(callbackToken.balanceOf(address(callbackEscrow)), 0);
    }
}

contract ProviderAuditorBonusEscrowOfficialTest is Test {
    uint256 constant BONUS = 5_000_000;
    uint256 constant CORE_BUDGET = 20_000_000;

    address admin = makeAddr("admin");
    address client = makeAddr("client");
    address provider = makeAddr("provider");
    address auditor = makeAddr("auditor");

    ERC8183 core;
    MockUSDC token;
    uint256 jobId;
    ProviderAuditorBonusEscrow escrow;

    function setUp() public {
        token = new MockUSDC();
        ERC8183 implementation = new ERC8183();
        ERC1967Proxy proxy =
            new ERC1967Proxy(address(implementation), abi.encodeCall(ERC8183.initialize, (admin, admin)));
        core = ERC8183(address(proxy));
        vm.prank(admin);
        core.setPaymentTokenAllowed(address(token), true);

        token.mint(client, CORE_BUDGET);
        token.mint(provider, BONUS);
        vm.prank(client);
        jobId = core.createJob(provider, auditor, uint48(block.timestamp + 3600), "bonus test", address(0), 0);
        vm.prank(provider);
        core.setBudget(jobId, address(token), CORE_BUDGET, "");
        vm.prank(client);
        token.approve(address(core), CORE_BUDGET);
        vm.prank(client);
        core.fund(jobId, address(token), CORE_BUDGET, "");

        escrow = new ProviderAuditorBonusEscrow(
            address(core), jobId, provider, auditor, address(token), BONUS, uint48(block.timestamp + 1800)
        );
        vm.prank(provider);
        token.approve(address(escrow), BONUS);
        vm.prank(provider);
        escrow.fund();
    }

    function testOfficialCompletedStatusReleasesBonusWithCorePayment() public {
        vm.prank(provider);
        core.submit(jobId, keccak256("work"), "");
        vm.prank(auditor);
        core.complete(jobId, keccak256("approve"), "");
        assertEq(uint8(core.getJob(jobId).status), uint8(ERC8183.JobStatus.Completed));
        assertEq(token.balanceOf(provider), CORE_BUDGET);
        assertEq(token.balanceOf(auditor), 0);

        escrow.settle();
        assertEq(token.balanceOf(provider), CORE_BUDGET);
        assertEq(token.balanceOf(auditor), BONUS);
        assertEq(token.balanceOf(address(core)), 0);
        assertEq(token.balanceOf(address(escrow)), 0);
    }

    function testOfficialRejectedStatusRefundsBonusAndCoreBudgetSeparately() public {
        vm.prank(provider);
        core.submit(jobId, keccak256("bad work"), "");
        vm.prank(auditor);
        core.reject(jobId, keccak256("reject"), "");
        assertEq(uint8(core.getJob(jobId).status), uint8(ERC8183.JobStatus.Rejected));
        assertEq(token.balanceOf(client), CORE_BUDGET);

        escrow.settle();
        assertEq(token.balanceOf(provider), BONUS);
        assertEq(token.balanceOf(auditor), 0);
        assertEq(token.balanceOf(address(escrow)), 0);
    }

    function testOfficialExpiryRefundsBonusAfterGracePeriod() public {
        vm.prank(provider);
        core.submit(jobId, keccak256("work"), "");
        vm.warp(block.timestamp + 7200);
        core.claimRefund(jobId);
        assertEq(uint8(core.getJob(jobId).status), uint8(ERC8183.JobStatus.Expired));
        escrow.settle();
        assertEq(token.balanceOf(provider), BONUS);
        assertEq(token.balanceOf(client), CORE_BUDGET);
        assertEq(token.balanceOf(auditor), 0);
    }
}
