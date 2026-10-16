// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {IERC165} from "@openzeppelin/contracts/utils/introspection/IERC165.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {IERC8183Hook} from "erc8183/contracts/IERC8183Hook.sol";
import {IERC8183JobView} from "./ProviderAuditorBonusEscrow.sol";

interface IFirstClaimCore is IERC8183JobView {
    function pendingClaimHash(uint256 jobId) external view returns (bytes32);
}

/// @notice Local-only, provider-funded bonus for one authentic evaluator approval.
/// @dev This is an ERC-8183 application hook, not a protocol feature or audited
/// production escrow. The job must name this hook at creation, then the client
/// binds the funded job and the provider funds the exact valueless MockUSDC bonus.
contract FirstClaimBonusHook is IERC8183Hook, ReentrancyGuard {
    using SafeERC20 for IERC20;

    uint256 public constant JOB_BUDGET = 20_000_000;
    uint256 public constant FIRST_CLAIM = 10_000_000;
    uint256 public constant BONUS = 5_000_000;

    enum State { Unbound, Bound, Funded, Released, Refunded }

    IFirstClaimCore public immutable core;
    IERC20 public immutable token;
    address public immutable client;
    address public immutable provider;
    address public immutable evaluator;
    bytes32 public immutable reportDigest;
    uint256 public jobId;
    State public state;
    bool public firstClaimSeen;
    bool private qualifyingApprovalInProgress;

    error InvalidBinding();
    error Unauthorized();
    error WrongState();
    error UnexpectedFundedAmount();
    error NotTerminal();

    event FirstClaimJobBound(uint256 indexed jobId, bytes32 indexed reportDigest);
    event FirstClaimBonusFunded(uint256 indexed jobId, address indexed provider, uint256 amount);
    event FirstClaimBonusReleased(uint256 indexed jobId, address indexed evaluator, uint256 amount);
    event FirstClaimBonusRefunded(uint256 indexed jobId, address indexed provider, uint256 amount);

    constructor(address core_, address client_, address provider_, address evaluator_,
                address token_, bytes32 reportDigest_) {
        if (core_.code.length == 0 || token_.code.length == 0 || reportDigest_ == bytes32(0)
            || client_ == address(0) || provider_ == address(0) || evaluator_ == address(0)
            || client_ == provider_ || provider_ == evaluator_ || client_ == evaluator_)
            revert InvalidBinding();
        core = IFirstClaimCore(core_);
        token = IERC20(token_);
        client = client_;
        provider = provider_;
        evaluator = evaluator_;
        reportDigest = reportDigest_;
    }

    function supportsInterface(bytes4 interfaceId) external pure override returns (bool) {
        return interfaceId == type(IERC8183Hook).interfaceId
            || interfaceId == type(IERC165).interfaceId;
    }

    function _job() private view returns (IERC8183JobView.Job memory job) {
        job = core.getJob(jobId);
        if (job.client != client || job.provider != provider || job.evaluator != evaluator
            || job.hook != address(this) || job.paymentToken != address(token)
            || job.budget != JOB_BUDGET) revert InvalidBinding();
    }

    /// @notice One-time bind after the client creates and funds a job with this hook.
    function bindJob(uint256 jobId_) external {
        if (msg.sender != client) revert Unauthorized();
        if (state != State.Unbound || jobId_ == 0) revert WrongState();
        jobId = jobId_;
        IERC8183JobView.Job memory job = _job();
        if (job.status != IERC8183JobView.JobStatus.Funded || job.settledAmount != 0
            || core.pendingClaimHash(jobId_) != bytes32(0) || job.expiredAt <= block.timestamp)
            revert InvalidBinding();
        state = State.Bound;
        emit FirstClaimJobBound(jobId_, reportDigest);
    }

    /// @notice Provider, not client, deposits 5,000,000 local minor units.
    function fund() external nonReentrant {
        if (msg.sender != provider) revert Unauthorized();
        if (state != State.Bound) revert WrongState();
        IERC8183JobView.Job memory job = _job();
        if (job.status != IERC8183JobView.JobStatus.Funded || job.settledAmount != 0
            || core.pendingClaimHash(jobId) != bytes32(0) || job.expiredAt <= block.timestamp)
            revert InvalidBinding();
        state = State.Funded;
        uint256 beforeBalance = token.balanceOf(address(this));
        token.safeTransferFrom(provider, address(this), BONUS);
        if (token.balanceOf(address(this)) - beforeBalance != BONUS) revert UnexpectedFundedAmount();
        emit FirstClaimBonusFunded(jobId, provider, BONUS);
    }

    function beforeAction(uint256 callbackJobId, bytes4 selector, bytes calldata data) external override {
        if (msg.sender != address(core)) revert Unauthorized();
        if (state != State.Funded || callbackJobId != jobId) return;
        if (selector == bytes4(keccak256("approveClaim(uint256,uint256,bytes32,bytes)"))) {
            (address actor, uint256 cumulative, bytes32 deliverable,) =
                abi.decode(data, (address, uint256, bytes32, bytes));
            IERC8183JobView.Job memory job = _job();
            qualifyingApprovalInProgress = firstClaimSeen && actor == evaluator
                && cumulative == FIRST_CLAIM && deliverable == reportDigest
                && job.status == IERC8183JobView.JobStatus.Funded
                && job.settledAmount == 0 && core.pendingClaimHash(jobId) != bytes32(0);
        }
    }

    function afterAction(uint256 callbackJobId, bytes4 selector, bytes calldata data)
        external override nonReentrant
    {
        if (msg.sender != address(core)) revert Unauthorized();
        if (state != State.Funded || callbackJobId != jobId) return;
        IERC8183JobView.Job memory job = _job();
        if (selector == bytes4(keccak256("submitClaim(uint256,uint256,bytes32,bytes)"))) {
            (address actor, uint256 cumulative, bytes32 deliverable,) =
                abi.decode(data, (address, uint256, bytes32, bytes));
            if (firstClaimSeen || actor != provider || cumulative != FIRST_CLAIM
                || deliverable != reportDigest || job.settledAmount != 0
                || core.pendingClaimHash(jobId) == bytes32(0)) {
                _refund();
            } else {
                firstClaimSeen = true;
            }
        } else if (selector == bytes4(keccak256("approveClaim(uint256,uint256,bytes32,bytes)"))) {
            bool release = qualifyingApprovalInProgress
                && job.status == IERC8183JobView.JobStatus.Funded
                && job.settledAmount == FIRST_CLAIM
                && core.pendingClaimHash(jobId) == bytes32(0);
            qualifyingApprovalInProgress = false;
            if (release) _release();
            else if (job.settledAmount > 0) _refund();
        } else if (selector == bytes4(keccak256("rejectClaim(uint256,uint256,bytes32,bytes32,bytes)"))
                   || selector == bytes4(keccak256("settleClaim(uint256,uint256,bytes32,bytes)"))
                   || selector == bytes4(keccak256("submit(uint256,bytes32,bytes)"))
                   || selector == bytes4(keccak256("reject(uint256,bytes32,bytes)"))
                   || selector == bytes4(keccak256("complete(uint256,bytes32,bytes)"))) {
            _refund();
        }
    }

    /// @notice `claimRefund` is not hookable; release provider funds after expiry.
    function refundAfterTerminal() external nonReentrant {
        if (state != State.Funded) revert WrongState();
        // The upstream admin may detach a hook from an in-flight job. Preserve
        // liveness after detachment, but keep every other obligation binding.
        IERC8183JobView.Job memory job = core.getJob(jobId);
        if (job.client != client || job.provider != provider || job.evaluator != evaluator
            || job.paymentToken != address(token) || job.budget != JOB_BUDGET
            || (job.hook != address(this) && job.hook != address(0))) revert InvalidBinding();
        if (job.status != IERC8183JobView.JobStatus.Completed
            && job.status != IERC8183JobView.JobStatus.Rejected
            && job.status != IERC8183JobView.JobStatus.Expired) revert NotTerminal();
        _refund();
    }

    function _release() private {
        state = State.Released;
        token.safeTransfer(evaluator, BONUS);
        emit FirstClaimBonusReleased(jobId, evaluator, BONUS);
    }

    function _refund() private {
        state = State.Refunded;
        token.safeTransfer(provider, BONUS);
        emit FirstClaimBonusRefunded(jobId, provider, BONUS);
    }
}
