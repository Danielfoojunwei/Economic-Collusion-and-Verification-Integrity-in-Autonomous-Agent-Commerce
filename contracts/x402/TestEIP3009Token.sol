// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// @notice Valueless local ERC-20 for exercising x402's exact/EIP-3009 scheme.
/// @dev Authorizations are checked on chain; this is not a production token.
contract TestEIP3009Token {
    string public constant name = "Research Test USD";
    string public constant symbol = "RTUSD";
    string public constant version = "1";
    uint8 public constant decimals = 6;

    bytes32 private constant DOMAIN_TYPEHASH = keccak256(
        "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
    );
    bytes32 private constant TRANSFER_TYPEHASH = keccak256(
        "TransferWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce)"
    );
    uint256 private constant SECP256K1_HALF_ORDER =
        0x7fffffffffffffffffffffffffffffff5d576e7357a4501ddfe92f46681b20a0;

    address public immutable minter;
    bytes32 public immutable DOMAIN_SEPARATOR;
    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    mapping(address => mapping(bytes32 => bool)) public authorizationState;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
    event AuthorizationUsed(address indexed authorizer, bytes32 indexed nonce);

    constructor() {
        minter = msg.sender;
        DOMAIN_SEPARATOR = keccak256(
            abi.encode(
                DOMAIN_TYPEHASH,
                keccak256(bytes(name)),
                keccak256(bytes(version)),
                block.chainid,
                address(this)
            )
        );
    }

    function mint(address to, uint256 value) external {
        require(msg.sender == minter, "OnlyMinter");
        require(to != address(0), "ZeroRecipient");
        totalSupply += value;
        balanceOf[to] += value;
        emit Transfer(address(0), to, value);
    }

    function transfer(address to, uint256 value) external returns (bool) {
        _transfer(msg.sender, to, value);
        return true;
    }

    function approve(address spender, uint256 value) external returns (bool) {
        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        return true;
    }

    function transferFrom(address from, address to, uint256 value) external returns (bool) {
        uint256 permitted = allowance[from][msg.sender];
        require(permitted >= value, "InsufficientAllowance");
        if (permitted != type(uint256).max) {
            allowance[from][msg.sender] = permitted - value;
        }
        _transfer(from, to, value);
        return true;
    }

    function transferWithAuthorization(
        address from,
        address to,
        uint256 value,
        uint256 validAfter,
        uint256 validBefore,
        bytes32 nonce,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) external {
        require(block.timestamp > validAfter, "AuthorizationNotYetValid");
        require(block.timestamp < validBefore, "AuthorizationExpired");
        require(!authorizationState[from][nonce], "AuthorizationAlreadyUsed");
        require(v == 27 || v == 28, "InvalidSignatureV");
        require(uint256(s) > 0 && uint256(s) <= SECP256K1_HALF_ORDER, "InvalidSignatureS");

        bytes32 structHash = keccak256(
            abi.encode(TRANSFER_TYPEHASH, from, to, value, validAfter, validBefore, nonce)
        );
        bytes32 digest = keccak256(abi.encodePacked("\x19\x01", DOMAIN_SEPARATOR, structHash));
        require(from != address(0) && ecrecover(digest, v, r, s) == from, "InvalidSignature");

        authorizationState[from][nonce] = true;
        emit AuthorizationUsed(from, nonce);
        _transfer(from, to, value);
    }

    function _transfer(address from, address to, uint256 value) private {
        require(to != address(0), "ZeroRecipient");
        uint256 available = balanceOf[from];
        require(available >= value, "InsufficientBalance");
        balanceOf[from] = available - value;
        balanceOf[to] += value;
        emit Transfer(from, to, value);
    }
}
