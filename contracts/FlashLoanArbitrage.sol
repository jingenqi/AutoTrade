// SPDX-License-Identifier: MIT
// 编译器版本已更新以兼容 Solidity v0.8.x 和最新的 OpenZeppelin 合约
pragma solidity ^0.8.20;

// 使用标准的 OpenZeppelin 导入方式，兼容 Remix
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
using SafeERC20 for IERC20;
// --- 本地接口定义以避免编译器版本冲突 ---

// Aave V2 闪电贷接收者接口
interface IFlashLoanReceiver {
    function executeOperation(
        address[] calldata assets,
        uint256[] calldata amounts,
        uint256[] calldata premiums,
        address initiator,
        bytes calldata params
    ) external returns (bool);
}

// Aave V2 借贷池接口 (仅包含所需函数)
interface ILendingPool {
    function flashLoan(
        address receiverAddress,
        address[] calldata assets,
        uint256[] calldata amounts,
        uint256[] calldata modes,
        address onBehalfOf,
        bytes calldata params,
        uint16 referralCode
    ) external;
}

// Aave V2 地址提供者接口 (仅包含所需函数)
interface ILendingPoolAddressesProvider {
    function getLendingPool() external view returns (address);
}

// Uniswap V2 路由器接口
interface IUniswapV2Router02 {
    function swapExactTokensForTokens(
        uint amountIn,
        uint amountOutMin,
        address[] calldata path,
        address to,
        uint deadline
    ) external returns (uint[] memory amounts);
}

/**
 * @title 工业级闪电贷套利合约
 * @author Gemini (针对MEV风险升级)
 * @notice 本合约是一个纯粹的套利交易"执行引擎"。
 * 所有的机会发现、路径计算和利润评估都必须在链下完成。
 * 它被设计为由一个链下机器人控制，该机器人提供精确的交易参数，
 * 包括严格的滑点保护，以最小化链上Gas成本并有效防御三明治攻击。
 */
contract FlashLoanArbitrage is IFlashLoanReceiver, Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    ILendingPoolAddressesProvider public immutable addressesProvider;
    ILendingPool public immutable lendingPool;

    // --- 主要网络的合约地址 ---
    // Aave Lending Pool Address Provider (Mainnet): 0xB53C1a33016B2DC2fF3653530bfF1848a515c8c5
    // Uniswap V2 Router (Mainnet): 0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D
    // SushiSwap Router (Mainnet): 0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F
    // 1inch Router (Mainnet): 0x1111111254EEB25477B68fb85Ed929f73A960582 (v5)

    address public immutable uniswapRouter;
    address public immutable sushiRouter;
    address public immutable oneInchRouter;

    // WETH 地址 (Mainnet)
    address public constant WETH = 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2;
    
    // 事件日志
    event ArbitrageExecuted(
        address indexed tokenIn, 
        address indexed tokenOut, 
        uint256 amountIn, 
        uint256 amountOut, 
        address dexBuy, 
        address dexSell,
        uint256 profit
    );
    event ErrorLog(string message, bytes params);

    /**
     * @dev 构造函数，初始化所有必要的合约地址。
     */
    constructor(
        address _addressesProvider,
        address _uniswapRouter,
        address _sushiRouter,
        address _oneInchRouter
    ) Ownable(msg.sender) { // 调用 Ownable 的构造函数来设置初始所有者
        addressesProvider = ILendingPoolAddressesProvider(_addressesProvider);
        lendingPool = ILendingPool(addressesProvider.getLendingPool());
        uniswapRouter = _uniswapRouter;
        sushiRouter = _sushiRouter;
        oneInchRouter = _oneInchRouter;
    }

    /**
     * @notice 由链下机器人调用的主入口函数。
     * @param _loanToken 需要通过闪电贷借入的代币 (例如 WETH)。
     * @param _otherToken 与之交易的另一个代币。
     * @param _loanAmount 要借入的 `_loanToken` 的数量。
     * @param _buyRouter 用于第一笔交易的DEX路由器地址 (买入 `_otherToken`)。
     * @param _sellRouter 用于第二笔交易的DEX路由器地址 (卖出 `_otherToken`)。
     * @param _minProfit 交易成功的最低利润要求 (以 `_loanToken` 为单位)。
     */
    function performArbitrage(
        address _loanToken,
        address _otherToken,
        uint256 _loanAmount,
        address _buyRouter,
        address _sellRouter,
        uint256 _minProfit
    ) external onlyOwner nonReentrant {
        require(_loanAmount > 0, "Loan amount must be greater than zero");
        
        address[] memory assets = new address[](1);
        assets[0] = _loanToken;

        uint256[] memory amounts = new uint256[](1);
        amounts[0] = _loanAmount;

        // 使用无债务代币模式 (mode 0)
        uint256[] memory modes = new uint256[](1);
        modes[0] = 0; 

        // 将所有必要参数编码，以便在回调函数中使用
        bytes memory params = abi.encode(_loanToken, _otherToken, _buyRouter, _sellRouter, _minProfit);

        lendingPool.flashLoan(
            address(this),
            assets,
            amounts,
            modes,
            address(this),
            params,
            0 // 无推荐码
        );
    }

    /**
     * @notice 这是Aave V2的回调函数，包含核心的套利和还款逻辑。
     */
    function executeOperation(
        address[] calldata assets,
        uint256[] calldata amounts,
        uint256[] calldata premiums,
        address, // initiator
        bytes calldata params
    ) external override returns (bool) {
        // --- 安全检查 ---
        require(msg.sender == address(lendingPool), "Caller must be Aave LendingPool");
        require(assets.length == 1, "Invalid asset count");

        // --- 解码从 `performArbitrage` 传来的参数 ---
        (address loanToken, address otherToken, address buyRouter, address sellRouter, uint256 minProfit) = 
            abi.decode(params, (address, address, address, address, uint256));
        
        uint256 loanAmount = amounts[0];
        uint256 premium = premiums[0];
        uint256 amountToRepay = loanAmount + premium;

        // --- 执行交易序列 ---

        // 交易 1: 用借来的 `loanToken` 购买 `otherToken`
        // 此处 amountOutMin 设置为0，因为我们信任链下计算，并且真正的保护在第二步
        uint256 reportedAmountReceived = _executeTrade(buyRouter, loanToken, otherToken, loanAmount, 0);
        if (reportedAmountReceived == 0) {
             emit ErrorLog("Buy trade failed", params);
             return false; // 回滚状态
        }

        // 【优化】为了稳健地处理"转账即收费"(Fee-on-Transfer) 的代币，
        // 我们不依赖 DEX 报告的转出数量，而是直接查询本合约收到的实际 `otherToken` 余额。
        uint256 actualAmountReceived = IERC20(otherToken).balanceOf(address(this));
        require(actualAmountReceived > 0, "Actual otherToken balance is zero after trade");

        // 这是我们从第二笔交易中需要收回的最低金额，以确保盈利。
        // 这是我们对抗三明治攻击的【关键防线】。
        uint256 minAmountOutFromSell = amountToRepay + minProfit;

        // 交易 2: 将 `otherToken` 卖回 `loanToken`，使用实际收到的金额
        uint256 finalAmount = _executeTrade(sellRouter, otherToken, loanToken, actualAmountReceived, minAmountOutFromSell);
        if (finalAmount < minAmountOutFromSell) {
            emit ErrorLog("Sell trade failed or insufficient profit", params);
            return false; // 回滚状态
        }

        // --- 偿还闪电贷 ---
        IERC20 loanTokenContract = IERC20(loanToken);
        loanTokenContract.approve(address(lendingPool), amountToRepay);

        // --- 记录利润和成功事件 ---
        uint256 actualProfit = finalAmount - amountToRepay;
        emit ArbitrageExecuted(loanToken, otherToken, loanAmount, finalAmount, buyRouter, sellRouter, actualProfit);

        return true;
    }
    
    /**
     * @dev 在兼容Uniswap V2的路由器上执行交易的内部辅助函数。
     * @return 收到的 `tokenOut` 的数量。
     */
    function _executeTrade(address router, address tokenIn, address tokenOut, uint256 amountIn, uint256 amountOutMin) internal returns (uint256) {
        IERC20 tokenInContract = IERC20(tokenIn);
        tokenInContract.approve(router, amountIn);

        address[] memory path = new address[](2);
        path[0] = tokenIn;
        path[1] = tokenOut;
        
        try IUniswapV2Router02(router).swapExactTokensForTokens(
            amountIn,
            amountOutMin, // 关键的滑点保护
            path,
            address(this),
            block.timestamp // 交易立即执行，无需等待
        ) returns (uint[] memory receivedAmounts) {
             return receivedAmounts[1];
        } catch {
            return 0;
        }
    }

    /**
     * @notice 允许合约所有者提取累积的利润。
     */
    function withdraw(address _tokenAddress) external onlyOwner {
        IERC20 token = IERC20(_tokenAddress);
        uint256 balance = token.balanceOf(address(this));
        require(balance > 0, "No balance to withdraw");
        token.safeTransfer(owner(), balance);
    }
    
    // 接收 ETH 的 fallback 函数
    receive() external payable {}
} 

