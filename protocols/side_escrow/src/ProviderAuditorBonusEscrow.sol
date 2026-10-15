// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/// @notice The ABI layout of the pinned ERC-8183 reference contract's getJob(uint256).
/// @dev Keep the full struct and its field order: ABI decoding a partial tuple is unsafe.
interface IERC8183JobView {
    enum JobStatus {
        Open,
        Funded,
        Submitted,
        Completed,
        Rejected,
        Expired
    }

    struct Job {
        address client;
        JobStatus status;
        address provider;
        uint48 expiredAt;
        address evaluator;
        uint48 submittedAt;
        uint256 budget;
        address hook;
        address paymentToken;
        uint256 providerAgentId;
        string description;
        uint256 settledAmount;
        address payoutReceiver;
    }

    function getJob(uint256 jobId) external view returns (Job memory);
}

/// @notice Local research side payment: the provider funds a fixed evaluator bonus,
///         contingent only on the *official* ERC-8183 job's terminal status.
/// @dev This is an application contract, not part of the ERC-8183 standard. A
///      Completed status says nothing about independent task correctness. Use
///      valueless 6-decimal MockUSDC on a local chain only.
contract ProviderAuditorBonusEscrow is ReentrancyGuard {
    using SafeERC20 for IERC20;

    // Local experiment cap, in 6-decimal MockUSDC minor units (20 test USDC).
    uint256 public constant MAX_BONUS_MINOR_UNITS = 20_000_000;

    enum EscrowState {
        Unfunded,
        Funded,
        Settled
    }

    IERC8183JobView public immutable core;
    IERC20 public immutable token;
    uint256 public immutable jobId;
    address public immutable provider;
    address public immutable auditor;
    uint256 public immutable bonusAmount;
    uint48 public immutable fundingDeadline;
    EscrowState public state;

    error InvalidBinding();
    error InvalidAmount();
    error InvalidDeadline();
    error Unauthorized();
    error WrongState();
    error WrongJobStatus();
    error UnexpectedFundedAmount();

    event BonusFunded(
        uint256 indexed jobId, address indexed provider, address indexed auditor, address token, uint256 amount
    );
    event BonusSettled(uint256 indexed jobId, address indexed recipient, uint256 amount, uint8 jobStatus);

    constructor(
        address core_,
        uint256 jobId_,
        address provider_,
        address auditor_,
        address token_,
        uint256 bonusAmount_,
        uint48 fundingDeadline_
    ) {
        if (
            core_.code.length == 0 || token_.code.length == 0 || jobId_ == 0 || provider_ == address(0)
                || auditor_ == address(0) || provider_ == auditor_
        ) revert InvalidBinding();
        if (bonusAmount_ == 0 || bonusAmount_ > MAX_BONUS_MINOR_UNITS) revert InvalidAmount();
        if (fundingDeadline_ <= block.timestamp) revert InvalidDeadline();

        IERC8183JobView coreView = IERC8183JobView(core_);
        IERC8183JobView.Job memory job = coreView.getJob(jobId_);
        if (
            job.provider != provider_ || job.evaluator != auditor_ || job.paymentToken != token_
                || job.expiredAt <= block.timestamp
        ) revert InvalidBinding();
        if (fundingDeadline_ > job.expiredAt) revert InvalidDeadline();
        if (job.status != IERC8183JobView.JobStatus.Funded && job.status != IERC8183JobView.JobStatus.Submitted) {
            revert WrongJobStatus();
        }

        core = coreView;
        token = IERC20(token_);
        jobId = jobId_;
        provider = provider_;
        auditor = auditor_;
        bonusAmount = bonusAmount_;
        fundingDeadline = fundingDeadline_;
    }

    /// @notice Only the bound provider may lock the exact bonus before the deadline.
    function fund() external nonReentrant {
        if (msg.sender != provider) revert Unauthorized();
        if (state != EscrowState.Unfunded) revert WrongState();
        if (block.timestamp >= fundingDeadline) revert InvalidDeadline();

        IERC8183JobView.Job memory job = core.getJob(jobId);
        _checkBinding(job);
        if (job.status != IERC8183JobView.JobStatus.Funded && job.status != IERC8183JobView.JobStatus.Submitted) {
            revert WrongJobStatus();
        }

        state = EscrowState.Funded;
        uint256 balanceBefore = token.balanceOf(address(this));
        token.safeTransferFrom(provider, address(this), bonusAmount);
        if (token.balanceOf(address(this)) - balanceBefore != bonusAmount) revert UnexpectedFundedAmount();
        emit BonusFunded(jobId, provider, auditor, address(token), bonusAmount);
    }

    /// @notice Anyone may settle once after the official job reaches a terminal state.
    ///         A caller cannot select a recipient, amount, or job status.
    function settle() external nonReentrant {
        if (state != EscrowState.Funded) revert WrongState();
        IERC8183JobView.Job memory job = core.getJob(jobId);
        _checkBinding(job);

        address recipient;
        if (job.status == IERC8183JobView.JobStatus.Completed) {
            recipient = auditor;
        } else if (job.status == IERC8183JobView.JobStatus.Rejected || job.status == IERC8183JobView.JobStatus.Expired)
        {
            recipient = provider;
        } else {
            revert WrongJobStatus();
        }

        state = EscrowState.Settled;
        token.safeTransfer(recipient, bonusAmount);
        emit BonusSettled(jobId, recipient, bonusAmount, uint8(job.status));
    }

    function _checkBinding(IERC8183JobView.Job memory job) private view {
        if (job.provider != provider || job.evaluator != auditor || job.paymentToken != address(token)) {
            revert InvalidBinding();
        }
    }
}
