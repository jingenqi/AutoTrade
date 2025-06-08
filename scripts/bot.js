const { ethers } = require("ethers");
require("dotenv").config();

// 从 artifacts 中加载合约 ABI
const { abi } = require("../artifacts/contracts/FlashLoanArbitrage.sol/FlashLoanArbitrage.json");

async function main() {
    // ------------------- 配置区域 -------------------
    // 从 .env 文件加载环境变量
    const providerUrl = process.env.MAINNET_RPC_URL; // e.g. Infura/Alchemy RPC URL
    const privateKey = process.env.PRIVATE_KEY;
    
    // 合约部署后的地址
    const contractAddress = "YOUR_DEPLOYED_CONTRACT_ADDRESS"; 

    // --- 优化：监控多个代币对 ---
    // 在这个列表中加入更多有流动性的代币地址，机器人会自动在它们之间寻找机会
    const watchList = [
        "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", // WETH
        "0x6B175474E89094C44Da98b954EedeAC495271d0F", // DAI
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", // USDC
        "0xdAC17F958D2ee523a2206206994597C13D831ec7", // USDT
        "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599", // WBTC
        "0x7D1AfA7B718fb893dB30A3aBc0C458d9C918231F"  // MATIC
    ];

    // 闪电贷的金额 (e.g. 10 WETH, 金额需要根据交易对的流动性调整)
    // 注意：对于不同代币对，最优的闪电贷额度是不同的。这里为简化，先使用一个通用值。
    // 真实的套利机器人会根据池子深度动态调整这个值。
    const flashLoanAmount = ethers.utils.parseUnits("10", 18); // 10 * 10^18 for WETH based pairs

    // 检查一轮后等待的时间 (e.g. 1.5 seconds)
    const pollingInterval = 1500;
    // -------------------------------------------------


    // --- 初始化 Provider, Wallet 和 Contract ---
    if (!providerUrl || !privateKey) {
        console.error("Please set MAINNET_RPC_URL and PRIVATE_KEY in your .env file");
        return;
    }
    const provider = new ethers.providers.JsonRpcProvider(providerUrl);
    const wallet = new ethers.Wallet(privateKey, provider);
    const arbitrageContract = new ethers.Contract(contractAddress, abi, wallet);

    console.log("🤖 Arbitrage Bot Started!");
    console.log(`Watching for opportunities between ${watchList.length} tokens...`);
    console.log(`Flash loan amount: ${ethers.utils.formatUnits(flashLoanAmount, 18)}`);
    console.log("-------------------------------------------------");


    // --- 主循环: 监控和执行套利 ---
    while (true) {
        // 从列表中随机选择两个不同的代币进行监控
        let tokenAIndex = Math.floor(Math.random() * watchList.length);
        let tokenBIndex = Math.floor(Math.random() * watchList.length);
        if (tokenAIndex === tokenBIndex) {
            tokenBIndex = (tokenBIndex + 1) % watchList.length; // 确保是不同的两个币
        }

        const token0 = watchList[tokenAIndex];
        const token1 = watchList[tokenBIndex];

        // 假设闪电贷总是以列表中的第一个代币(通常是WETH)进行
        const loanToken = watchList[0]; 

        try {
            console.log(`\n[${new Date().toLocaleTimeString()}] Checking for opportunities: ${loanToken.slice(0, 8)} -> ${token0.slice(0,8)} -> ${token1.slice(0,8)}`);
            
            // 1. 调用合约的 view function 来查找最佳交易路径
            // 注意：这里的检查路径是 闪电贷资产 -> token0 -> token1 -> 闪电贷资产
            // 为了简化，我们假设闪电贷的资产(loanToken)就是我们要交易的其中一个代币(token0)
            const bestRoute = await arbitrageContract.callStatic._findBestTrade(flashLoanAmount, token0, token1);
            const bestAmountOut = bestRoute.bestAmountOut;
            
            // 2. 检查是否有利可图
            // 闪电贷费用为 0.09%
            const loanRepaymentAmount = flashLoanAmount.add(flashLoanAmount.mul(9).div(10000)); 

            if (bestAmountOut.gt(loanRepaymentAmount)) {
                const profit = bestAmountOut.sub(loanRepaymentAmount);
                console.log("✅ Profitable opportunity found!");
                console.log(`   - Path: ${token0} -> ${token1} -> ${token0}`);
                console.log(`   - Buy on: ${bestRoute.dexToBuy}`);
                console.log(`   - Sell on: ${bestRoute.dexToSell}`);
                console.log(`   - Estimated Profit: ${ethers.utils.formatUnits(profit, 18)}`);

                // 3. 执行套利交易
                console.log("🚀 Executing arbitrage...");
                const tx = await arbitrageContract.performArbitrage(token0, token1, flashLoanAmount, {
                    gasLimit: 1500000 // Gas Limit 增加以应对更复杂的交易
                });
                
                console.log(`Transaction sent: ${tx.hash}`);
                const receipt = await tx.wait();
                console.log(`Transaction confirmed in block: ${receipt.blockNumber}`);

                // Find and log the profit from the event
                const profitLog = receipt.events?.find(e => e.event === 'ProfitLog');
                if (profitLog) {
                    console.log(`🤑 Actual Profit from event: ${ethers.utils.formatUnits(profitLog.args.profit, 18)}`);
                }
                console.log("Waiting for the next opportunity...");

            } else {
                console.log("❌ No profitable opportunity found in this round.");
            }

        } catch (error) {
            console.error("An error occurred in the main loop:", error.reason || error.message);
        }
        
        // Wait for the next poll
        await new Promise(resolve => setTimeout(resolve, pollingInterval));
    }
}

main().catch(error => {
    console.error("Fatal error:", error);
    process.exit(1);
}); 