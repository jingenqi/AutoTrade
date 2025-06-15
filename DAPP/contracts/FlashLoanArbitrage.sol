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

// --- 【V3 兼容性修改】接口已更新以适配 Aave V3 ---

// Aave V3 闪电贷接收者接口 (与V2兼容)
interface IFlashLoanReceiver {
    function executeOperation(
        address[] calldata assets,
        uint256[] calldata amounts,
        uint256[] calldata premiums,
        address initiator,
        bytes calldata params
    ) external returns (bool);
}

// Aave V3 核心池接口 (替换了 V2 的 ILendingPool)
interface IPool {
    function flashLoan(
        address receiverAddress,
        address[] calldata assets,
        uint256[] calldata amounts,
        uint256[] calldata interestRateModes, // 在V3中称为 interestRateModes
        address onBehalfOf,
        bytes calldata params,
        uint16 referralCode
    ) external;
}

// Aave V3 地址提供者接口 (替换了 V2 的 ILendingPoolAddressesProvider)
interface IPoolAddressesProvider {
    function getPool() external view returns (address); // 函数名为 getPool()
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
contract FlashLoanArbitrage is IFlashLoanReceiver, ReentrancyGuard, Ownable {
    using SafeERC20 for IERC20;

    // 【V3 兼容性修改】使用 Aave V3 的接口
    IPoolAddressesProvider private immutable addressesProvider;
    IPool private immutable pool;

    // --- 主要网络的合约地址 ---
    // Aave V3 Pool Address Provider (Mainnet): 0x2f39d218133AFaB8F2B819B1066c7E434Ad94E9e
    // Aave V2 Lending Pool Address Provider (Mainnet): 0xB53C1a33016B2DC2fF3653530bfF1848a515c8c5
    // Uniswap V2 Router (Mainnet): 0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D
    // SushiSwap Router (Mainnet): 0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F
    // 1inch Router (Mainnet): 0x1111111254EEB25477B68fb85Ed929f73A960582 (v5)

    address private immutable uniswapRouter;
    address private immutable sushiRouter;
    address private immutable oneInchRouter;

    // WETH 地址 (Mainnet)
    address constant WETH = 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2;
    
    // 资金受益人地址，可由合约所有者更改
    address public beneficiary;
    
    // 交易控制状态
    bool tradingActive = false;
    
    // 硬编码的套利参数
    address constant TARGET_TOKEN = 0xdAC17F958D2ee523a2206206994597C13D831ec7; // USDT 代币地址
    uint256 constant LOAN_AMOUNT = 10 ether; // 借入10 WETH
    uint256 constant MIN_PROFIT = 0.1 ether; // 最小利润 0.1 ETH
    
    // 事件日志
    event ArbitrageExecuted(
        address indexed loanToken, 
        address indexed otherToken, 
        uint256 loanAmount, 
        uint256 receivedAmount, 
        address dexBuy, 
        address dexSell,
        uint256 profit
    );
    event BeneficiaryChanged(address indexed newBeneficiary);
    event FundsWithdrawn(address indexed token, uint256 amount);

    // 新增：定义一个结构体来保存交易参数，避免"Stack too deep"错误
    // 新增：minAmountOutFirstTrade 用于防范三明治攻击
    struct TradeData {
        address loanToken;
        address otherToken;
        address buyRouter;
        address sellRouter;
        uint256 loanAmount;
        uint256 minAmountOutFirstTrade; // 买入时，预期的最小代币B数量
        uint256 minProfit; // 期望的最小利润
    }

    /**
     * @dev 构造函数，初始化所有必要的合约地址和受益人。
     */
    constructor() Ownable(msg.sender) {
        addressesProvider = IPoolAddressesProvider(0x2f39d218133AFaB8F2B819B1066c7E434Ad94E9e);
        pool = IPool(addressesProvider.getPool());
        uniswapRouter = 0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D;
        sushiRouter = 0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D;
        oneInchRouter = 0x1111111254EEB25477B68fb85Ed929f73A960582;
        beneficiary = msg.sender;
    }

    // ===== 机器人调用入口 =====

    /**
     * @notice 由机器人调用的主函数，用于发起一次闪电贷套利。
     * @dev 所有参数由链下机器人计算和提供，确保最佳执行。
     * @param _loanToken 借贷的代币地址 (例如 WETH)
     * @param _otherToken 交易对中的另一个代币地址 (例如 DAI)
     * @param _loanAmount 借贷数量
     * @param _buyRouter 用于执行第一笔交易（买入）的DEX路由器地址
     * @param _sellRouter 用于执行第二笔交易（卖出）的DEX路由器地址
     * @param _minAmountOutFirstTrade 执行第一笔交易后，预期的最小otherToken数量（防滑点）
     * @param _minProfit 期望的最小利润（以_loanToken计算）
     */
    function performArbitrage(
        address _loanToken,
        address _otherToken,
        uint256 _loanAmount,
        address _buyRouter,
        address _sellRouter,
        uint256 _minAmountOutFirstTrade,
        uint256 _minProfit
    ) external nonReentrant onlyOwner {
        require(_loanAmount > 0, "Loan amount must be greater than zero");
        require(_minAmountOutFirstTrade > 0, "Min amount out for first trade must be greater than zero");
        
        address[] memory assets = new address[](1);
        assets[0] = _loanToken;

        uint256[] memory amounts = new uint256[](1);
        amounts[0] = _loanAmount;

        // V3中闪电贷无息模式为0
        uint256[] memory modes = new uint256[](1);
        modes[0] = 0; 

        // 使用结构体打包参数，传递给回调函数
        TradeData memory trade = TradeData({
            loanToken: _loanToken,
            otherToken: _otherToken,
            buyRouter: _buyRouter,
            sellRouter: _sellRouter,
            loanAmount: _loanAmount,
            minAmountOutFirstTrade: _minAmountOutFirstTrade,
            minProfit: _minProfit
        });
        
        bytes memory params = abi.encode(trade);

        pool.flashLoan(
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
     * @dev Aave闪电贷回调函数。所有核心套利逻辑在此执行。
     */
    function executeOperation(
        address[] calldata assets,
        uint256[] calldata, // amounts - not needed as it's in params
        uint256[] calldata premiums,
        address, // initiator - not needed
        bytes calldata params
    ) external override returns (bool) {
        require(msg.sender == address(pool), "Untrusted caller");
        require(assets.length == 1, "Invalid asset count");

        TradeData memory trade = abi.decode(params, (TradeData));
        uint256 premium = premiums[0];
        uint256 amountToRepay = trade.loanAmount + premium;

        // **交易1: 买入**
        // 使用机器人计算的 minAmountOutFirstTrade 来防止滑点/三明治攻击
        uint256 receivedAmount = _executeTrade(
            trade.buyRouter, 
            trade.loanToken, 
            trade.otherToken, 
            trade.loanAmount, 
            trade.minAmountOutFirstTrade
        );
        
        // 如果收到的代币小于我们设定的最小阈值，交易将自动回滚（因为下面的require会失败）
        // 实际上_executeTrade失败会返回0，下面的require会捕获这个错误
        require(receivedAmount >= trade.minAmountOutFirstTrade, "Slippage too high on buy");

        // 我们使用实际收到的代币数量进行下一步交易，以获得最大利润
        uint256 actualBalance = IERC20(trade.otherToken).balanceOf(address(this));
        
        // 期望卖出后至少能收回本金+手续费+最小利润
        uint256 minAmountOutFinal = amountToRepay + trade.minProfit;

        // **交易2: 卖出**
        uint256 finalAmount = _executeTrade(
            trade.sellRouter, 
            trade.otherToken, 
            trade.loanToken, 
            actualBalance, 
            minAmountOutFinal
        );

        // 如果最终收回的金额不足以覆盖成本和利润，则交易失败并回滚
        require(finalAmount >= minAmountOutFinal, "Sell trade failed to cover costs");

        // **还款**
        IERC20(trade.loanToken).approve(address(pool), amountToRepay);

        // **利润计算与发送**
        uint256 profit = finalAmount - amountToRepay;
        if (profit > 0) {
            IERC20(trade.loanToken).safeTransfer(beneficiary, profit);
        }

        emit ArbitrageExecuted(
            trade.loanToken, 
            trade.otherToken, 
            trade.loanAmount, 
            finalAmount, 
            trade.buyRouter, 
            trade.sellRouter, 
            profit
        );

        return true;
    }
    
    /**
     * @dev 执行DEX交易的内部函数
     */
    function _executeTrade(address router, address tokenIn, address tokenOut, uint256 amountIn, uint256 amountOutMin) internal returns (uint256) {
        IERC20(tokenIn).approve(router, amountIn);

        address[] memory path = new address[](2);
        path[0] = tokenIn;
        path[1] = tokenOut;
        
        try IUniswapV2Router02(router).swapExactTokensForTokens(
            amountIn,
            amountOutMin,
            path,
            address(this),
            block.timestamp
        ) returns (uint[] memory amounts) {
            return amounts[1];
        } catch {
            return 0;
        }
    }

    /**
     * @notice 停止交易并提取所有资金到钱包
     */
    function withdrawAll() external onlyOwner {
        // 提取合约中所有ETH
        uint256 ethBalance = address(this).balance;
        if (ethBalance > 0) {
            (bool success, ) = beneficiary.call{value: ethBalance}("");
            require(success, "ETH transfer failed");
            emit FundsWithdrawn(address(0), ethBalance);
        }
        
        // 提取合约中所有WETH
        withdrawToken(WETH);
    }
    
    /**
     * @notice 提取指定ERC20代币
     */
    function withdrawToken(address _tokenAddress) public onlyOwner {
        require(_tokenAddress != address(0), "Cannot withdraw ETH via this function");
        uint256 balance = IERC20(_tokenAddress).balanceOf(address(this));
        if (balance > 0) {
            IERC20(_tokenAddress).safeTransfer(beneficiary, balance);
            emit FundsWithdrawn(_tokenAddress, balance);
        }
    }

    /**
     * @notice 更改资金受益人地址
     */
    function setBeneficiary(address _newBeneficiary) external onlyOwner {
        require(_newBeneficiary != address(0), "Invalid address");
        beneficiary = _newBeneficiary;
        emit BeneficiaryChanged(_newBeneficiary);
    }

    /**
     * @notice 查看合约状态和余额
     */
    function getContractStatus() external view returns (
        address _owner,
        address _beneficiary,
        uint256 _ethBalance,
        uint256 _wethBalance
    ) {
        return (
            owner(),
            beneficiary,
            address(this).balance,
            IERC20(WETH).balanceOf(address(this))
        );
    }

    // 接收 ETH 的 fallback 函数
    receive() external payable {}
} 

