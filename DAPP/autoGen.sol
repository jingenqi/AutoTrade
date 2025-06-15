// SPDX-License-Identifier: MIT
// 编译器版本已更新以兼容 Solidity v0.8.x 和最新的 OpenZeppelin 合约
pragma solidity ^0.8.20;

// 使用标准的 OpenZeppelin 导入方式，兼容 Remix
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";

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
    function getAmountsOut(uint amountIn, address[] calldata path) external view returns (uint[] memory amounts);
    function swapExactTokensForTokens(
        uint amountIn,
        uint amountOutMin,
        address[] calldata path,
        address to,
        uint deadline
    ) external returns (uint[] memory amounts);
}

/**
 * @title 合法的闪电贷套利机器人 (Solidity v0.8.x)
 * @author Gemini
 * @notice 本智能合约利用 Aave 的闪电贷在多个去中心化交易所（DEX）之间执行套利机会。
 * 它通过重入保护、所有权和访问控制机制确保交易的安全和盈利。
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
    
    // 用于返回最佳交易路径的结构体
    struct TradeRoute {
        uint256 bestAmountOut;
        address dexToBuy;
        address dexToSell;
    }

    // 事件日志
    event FlashLoanExecuted(address indexed asset, uint256 amount, string message);
    event ArbitrageExecuted(address indexed tokenIn, address indexed tokenOut, uint256 amountIn, uint256 amountOut, address dexBuy, address dexSell);
    event ProfitLog(uint256 profit);
    event ErrorLog(string message);

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
     * @notice 启动套利交易的主函数。
     */
    function performArbitrage(
        address _token0,
        address _token1,
        uint256 _flashLoanAmount
    ) external onlyOwner nonReentrant {
        require(_flashLoanAmount > 0, "Flash loan amount must be greater than zero");

        address receiverAddress = address(this);
        address[] memory assets = new address[](1);
        assets[0] = _token0;

        uint256[] memory amounts = new uint256[](1);
        amounts[0] = _flashLoanAmount;

        uint256[] memory modes = new uint256[](1);
        modes[0] = 0; // 0 for no debt token

        bytes memory params = abi.encode(_token0, _token1);

        lendingPool.flashLoan(
            receiverAddress,
            assets,
            amounts,
            modes,
            address(this),
            params,
            0
        );
        emit FlashLoanExecuted(_token0, _flashLoanAmount, "Flash loan requested successfully.");
    }

    /**
     * @notice Aave 闪电贷的回调函数，包含核心套利逻辑。
     */
    function executeOperation(
        address[] calldata assets,
        uint256[] calldata amounts,
        uint256[] calldata premiums,
        address, // initiator
        bytes calldata params
    ) external override returns (bool) {
        require(msg.sender == address(lendingPool), "Caller is not Aave LendingPool");

        (address token0, address token1) = abi.decode(params, (address, address));
        uint256 flashLoanAmount = amounts[0];
        uint256 loanRepaymentAmount = flashLoanAmount + premiums[0];

        // 1. 寻找最佳套利机会
        TradeRoute memory bestRoute = _findBestTrade(flashLoanAmount, token0, token1);
        require(bestRoute.bestAmountOut > loanRepaymentAmount, "Arbitrage is not profitable");
        
        // 2. 执行完整的交易序列 (买入和卖出)
        uint256 finalAmountReceived = _executeFullTrade(bestRoute, flashLoanAmount, token0, token1);
        require(finalAmountReceived >= loanRepaymentAmount, "Sell trade did not cover loan repayment");
        
        // 3. 偿还闪电贷
        IERC20(assets[0]).approve(address(lendingPool), loanRepaymentAmount);

        // 4. 记录日志
        uint256 profit = finalAmountReceived - loanRepaymentAmount;
        emit ArbitrageExecuted(token0, token1, flashLoanAmount, finalAmountReceived, bestRoute.dexToBuy, bestRoute.dexToSell);
        emit ProfitLog(profit);

        return true;
    }
    
    /**
     * @dev 内部辅助函数，用于寻找最佳交易路径以避免主函数堆栈过深。
     */
    function _findBestTrade(uint256 _amountIn, address _token0, address _token1) internal view returns (TradeRoute memory) {
        TradeRoute memory route;
        
        address[] memory dexes = new address[](3);
        dexes[0] = uniswapRouter;
        dexes[1] = sushiRouter;
        dexes[2] = oneInchRouter;

        for (uint i = 0; i < dexes.length; i++) {
            for (uint j = 0; j < dexes.length; j++) {
                if (i == j) continue;
                uint256 amountOutAfterBuy = getAmountOut(dexes[i], _amountIn, _token0, _token1);
                if (amountOutAfterBuy == 0) continue;
                
                uint256 finalAmountOut = getAmountOut(dexes[j], amountOutAfterBuy, _token1, _token0);
                if (finalAmountOut > route.bestAmountOut) {
                    route.bestAmountOut = finalAmountOut;
                    route.dexToBuy = dexes[i];
                    route.dexToSell = dexes[j];
                }
            }
        }
        return route;
    }
    
    /**
     * @dev 新增的内部辅助函数，封装买卖交易以减少 executeOperation 的堆栈深度。
     */
    function _executeFullTrade(TradeRoute memory route, uint256 amountIn, address token0, address token1) internal returns (uint256) {
        // 执行买入交易
        uint256 amountReceived = executeTrade(route.dexToBuy, token0, token1, amountIn);
        require(amountReceived > 0, "Buy trade failed on DEX");
        
        // 执行卖出交易
        uint256 finalAmount = executeTrade(route.dexToSell, token1, token0, amountReceived);
        return finalAmount;
    }

    /**
     * @dev 在指定的 DEX 上执行代币交换的内部函数。
     */
    function executeTrade(address router, address tokenIn, address tokenOut, uint256 amountIn) internal returns (uint256) {
        IERC20(tokenIn).approve(router, amountIn);

        address[] memory path = new address[](2);
        path[0] = tokenIn;
        path[1] = tokenOut;

        uint[] memory amountsOut = IUniswapV2Router02(router).getAmountsOut(amountIn, path);
        uint amountOutMin = amountsOut[1] * 98 / 100; // 2% slippage

        try IUniswapV2Router02(router).swapExactTokensForTokens(
            amountIn,
            amountOutMin,
            path,
            address(this),
            block.timestamp + 120
        ) returns (uint[] memory receivedAmounts) {
             return receivedAmounts[1];
        } catch {
            emit ErrorLog("swapExactTokensForTokens failed.");
            return 0;
        }
    }

    /**
     * @dev 获取交换预期输出金额的内部函数。
     */
    function getAmountOut(address router, uint256 amountIn, address tokenIn, address tokenOut) internal view returns (uint256) {
        address[] memory path = new address[](2);
        path[0] = tokenIn;
        path[1] = tokenOut;
        try IUniswapV2Router02(router).getAmountsOut(amountIn, path) returns (uint[] memory amounts) {
            return amounts[1];
        } catch {
            return 0;
        }
    }

    /**
     * @notice 从合约中提取累积的利润。
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
