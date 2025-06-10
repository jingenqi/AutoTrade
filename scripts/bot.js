const { ethers } = require("ethers");
// 【Flashbots】导入 Flashbots 库。请确保已通过 `npm install @flashbots/ethers-provider-bundle` 安装
const { FlashbotsBundleProvider } = require("@flashbots/ethers-provider-bundle");
require("dotenv").config();

// --- ABIs: 加载所需的合约接口 ---
const { abi: ArbitrageABI } = require("../artifacts/contracts/FlashLoanArbitrage.sol/FlashLoanArbitrage.json");
const pairABI = [
    'function getReserves() external view returns (uint112 reserve0, uint112 reserve1, uint32 blockTimestampLast)',
    'function token0() external view returns (address)',
    'function token1() external view returns (address)'
];
const factoryABI = [
    'function getPair(address tokenA, address tokenB) external view returns (address pair)'
];
const aggregatorV3InterfaceABI = [{"inputs":[],"name":"decimals","outputs":[{"internalType":"uint8","name":"","type":"uint8"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"description","outputs":[{"internalType":"string","name":"","type":"string"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"uint80","name":"_roundId","type":"uint80"}],"name":"getRoundData","outputs":[{"internalType":"uint80","name":"roundId","type":"uint80"},{"internalType":"int256","name":"answer","type":"int256"},{"internalType":"uint256","name":"startedAt","type":"uint256"},{"internalType":"uint256","name":"updatedAt","type":"uint256"},{"internalType":"uint80","name":"answeredInRound","type":"uint80"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"latestRoundData","outputs":[{"internalType":"uint80","name":"roundId","type":"uint80"},{"internalType":"int256","name":"answer","type":"int256"},{"internalType":"uint256","name":"startedAt","type":"uint256"},{"internalType":"uint256","name":"updatedAt","type":"uint256"},{"internalType":"uint80","name":"answeredInRound","type":"uint80"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"version","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"}];
const erc20SymbolABI = [{"inputs":[],"name":"symbol","outputs":[{"internalType":"string","name":"","type":"string"}],"stateMutability":"view","type":"function"}];

async function main() {
    // ------------------- 配置区域 -------------------
    const config = {
        providerUrl: process.env.MAINNET_WSS_URL,
        privateKey: process.env.PRIVATE_KEY,
        contractAddress: "YOUR_DEPLOYED_CONTRACT_ADDRESS",

        watchList: [
            ethers.utils.getAddress("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"), // WETH (必须是第一个，作为闪电贷资产)
            ethers.utils.getAddress("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"), // USDC
            ethers.utils.getAddress("0x6B175474E89094C44Da98b954EedeAC495271d0F"), // DAI
        ],

        dexFactories: {
            "UniswapV2": ethers.utils.getAddress("0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f"),
            "SushiSwap": ethers.utils.getAddress("0xC0AEe478e3658e2610c5F7A4a2E1777cE9e4f2Ac")
        },

        ethPriceFeedAddress: ethers.utils.getAddress("0x5f4eC3Df9cbd43714FE274045F3642155D8407aA"),

        minProfitUSD: 15.0,
        txTimeoutSeconds: 60, // 增加超时时间以适应Flashbots的捆绑包机制
    };
    // -------------------------------------------------

    let isExecuting = false;
    const tokenPairs = {};
    const tokenSymbolCache = {};
    let baseGasEstimate;

    if (!config.providerUrl || !config.privateKey || config.contractAddress === "YOUR_DEPLOYED_CONTRACT_ADDRESS") {
        console.error("配置错误: 请在 .env 文件中设置 MAINNET_WSS_URL, PRIVATE_KEY 并在脚本中配置 contractAddress");
        return;
    }
    
    // --- 【Flashbots】初始化提供者和签名钱包 ---
    const provider = new ethers.providers.WebSocketProvider(config.providerUrl);
    // 用于签名的钱包，必须与 Flashbots Provider 使用的认证私钥相对应
    const authSigner = new ethers.Wallet(process.env.FLASHBOTS_AUTH_KEY || config.privateKey, provider);
    const wallet = new ethers.Wallet(config.privateKey, provider);
    
    // Flashbots Provider 需要一个标准的 Ethers Provider 和一个签名者
    const flashbotsProvider = await FlashbotsBundleProvider.create(provider, authSigner);

    const arbitrageContract = new ethers.Contract(config.contractAddress, ArbitrageABI, wallet);
    const ethPriceFeed = new ethers.Contract(config.ethPriceFeedAddress, aggregatorV3InterfaceABI, provider);

    console.log("工业级套利机器人正在启动...");
    console.log(` - 钱包地址: ${wallet.address}`);
    console.log(` - 监控 ${Object.keys(config.dexFactories).length} 个 DEX, ${config.watchList.length} 个代币.`);
    
    await initialize();

    console.log("启动成功! 机器人现在监听新的以太坊区块...");
    provider.on('block', async (blockNumber) => {
        if (isExecuting) {
            console.log(`[区块: ${blockNumber}] 警告: 当前有交易正在执行，跳过本区块...`);
            return;
        }

        console.log(`\n[${new Date().toLocaleTimeString()} | 区块: ${blockNumber}] 扫描套利机会...`);
        await mainLoop(blockNumber);
    });

    const mainLoop = async (blockNumber) => {
        try {
            const [feeData, ethPriceData, ...reservesData] = await Promise.all([
                provider.getFeeData(),
                ethPriceFeed.latestRoundData(),
                ...Object.values(tokenPairs).map(pair => pair.contract.getReserves())
            ]);

            const ethPriceUSD = parseFloat(ethers.utils.formatUnits(ethPriceData.answer, 8));
            
            Object.keys(tokenPairs).forEach((key, index) => {
                tokenPairs[key].reserves = reservesData[index];
            });

            console.log(`  - 市场数据: ETH 价格 = $${ethPriceUSD.toFixed(2)} | 基础费 = ${ethers.utils.formatUnits(feeData.lastBaseFeePerGas, 'gwei').toFixed(2)} Gwei`);
            
            const arbitragePaths = buildArbitragePaths();
            const potentialOpportunities = arbitragePaths.map(path => checkPath(path, ethPriceUSD, feeData));
            
            const profitableOpportunities = potentialOpportunities.filter(p => p.isProfitable);

            if (profitableOpportunities.length > 0) {
                const bestOpportunity = profitableOpportunities.sort((a, b) => b.netProfitUSD - a.netProfitUSD)[0];
                
                console.log("发现最佳盈利机会!");
                console.log(`  - 路径: ${bestOpportunity.path.buyDex}(买入) -> ${bestOpportunity.path.sellDex}(卖出)`);
                console.log(`  - 交易对: ${bestOpportunity.path.token0Symbol}/${bestOpportunity.path.token1Symbol}`);
                console.log(`  - 动态闪电贷金额: ${ethers.utils.formatEther(bestOpportunity.loanAmount)} ETH`);
                console.log(`  - 预估净利润: $${bestOpportunity.netProfitUSD.toFixed(2)}`);

                await executeArbitrage(bestOpportunity, feeData, blockNumber);

            } else {
                console.log("  - 本轮检查未发现有利可图的机会。");
            }

        } catch (error) {
            console.error("主循环发生严重错误:", error);
        }
    };

    async function initialize() {
        console.log("正在预加载交易对与代币信息...");
        const pairPromises = [];

        for (let i = 0; i < config.watchList.length; i++) {
            await getTokenSymbol(config.watchList[i]);
            for (let j = i + 1; j < config.watchList.length; j++) {
                const tokenA = config.watchList[i];
                const tokenB = config.watchList[j];
                for (const dexName in config.dexFactories) {
                    pairPromises.push(loadPair(dexName, tokenA, tokenB));
                }
            }
        }
        await Promise.all(pairPromises);
        
        try {
            const samplePath = buildArbitragePaths()[0];
            if (!samplePath) throw new Error("无法构建用于 Gas 估算的示例路径, 请检查配置。");
            
            const sampleLoanAmount = ethers.utils.parseEther("1");
            const sampleMinProfit = ethers.utils.parseEther("0.001");
            const buyRouterAddress = config.dexFactories[samplePath.buyDex];
            const sellRouterAddress = config.dexFactories[samplePath.sellDex];

            baseGasEstimate = await arbitrageContract.estimateGas.performArbitrage(
                samplePath.loanToken,
                samplePath.otherToken,
                sampleLoanAmount,
                buyRouterAddress,
                sellRouterAddress,
                sampleMinProfit
            );
            console.log(`  - 基础 Gas 估算完成: ${baseGasEstimate.toString()}`);
        } catch (error) {
            console.error("关键错误: 无法估算 Gas 成本. 可能是合约地址错误、节点问题或配置不正确。", error.message);
            console.log("  - 将使用一个保守的默认值 (800,000) Gas。");
            baseGasEstimate = ethers.BigNumber.from(800000);
        }

        console.log("初始化完成!\n");
        console.log("--- 工业级机器人操作警告与建议 ---");
        console.log("1. 节点延迟: 为获得最佳性能，请考虑运行您自己的以太坊节点。公共RPC（即使是WSS）也存在不可避免的延迟。");
        console.log("2. MEV保护: 您已配置为使用 Flashbots。这是避免您的交易被抢跑或遭受三明治攻击的关键。请确保您的 `FLASHBOTS_AUTH_KEY` 环境变量已正确设置。");
        console.log("3. 资金安全: 切勿在用于运行此机器人的私钥中存放超过您愿意损失的资金。");
        console.log("-------------------------------------------------");
    }

    async function loadPair(dexName, tokenA, tokenB) {
        const factory = new ethers.Contract(config.dexFactories[dexName], factoryABI, provider);
        try {
            const pairAddress = await factory.getPair(tokenA, tokenB);
            if (pairAddress && pairAddress !== ethers.constants.AddressZero) {
                const pairContract = new ethers.Contract(pairAddress, pairABI, provider);
                const token0 = await pairContract.token0();
                const pairKey = `${dexName}-${tokenA}-${tokenB}`;
                tokenPairs[pairKey] = { contract: pairContract, token0: token0, reserves: null };
                console.log(`  - 已加载: ${dexName} 的 ${await getTokenSymbol(tokenA)}-${await getTokenSymbol(tokenB)} 交易对`);
            }
        } catch (error) {
            console.warn(`  - 警告: 加载 ${dexName} 的 ${await getTokenSymbol(tokenA)}-${await getTokenSymbol(tokenB)} 交易对失败。`);
        }
    }

    function buildArbitragePaths() {
        const paths = [];
        const dexNames = Object.keys(config.dexFactories);
        const loanToken = config.watchList[0];

        Object.keys(tokenPairs).forEach(pairKey => {
            const [dexName, tokenA, tokenB] = pairKey.split('-');

            if (tokenA !== loanToken && tokenB !== loanToken) return;

            const otherToken = (loanToken === tokenA) ? tokenB : tokenA;

            dexNames.forEach(otherDex => {
                if (dexName === otherDex) return;
                const otherPairKey = `${otherDex}-${tokenA}-${tokenB}`;
                if (tokenPairs[otherPairKey]) {
                    paths.push({
                        buyDex: dexName,
                        sellDex: otherDex,
                        loanToken,
                        otherToken,
                        token0Symbol: tokenSymbolCache[loanToken],
                        token1Symbol: tokenSymbolCache[otherToken]
                    });
                }
            });
        });
        return paths;
    }
    
    function checkPath(path, ethPriceUSD, feeData) {
        const { buyDex, sellDex, loanToken, otherToken } = path;

        const tokenA = config.watchList.indexOf(loanToken) < config.watchList.indexOf(otherToken) ? loanToken : otherToken;
        const tokenB = config.watchList.indexOf(loanToken) < config.watchList.indexOf(otherToken) ? otherToken : loanToken;

        const buyPairKey = `${buyDex}-${tokenA}-${tokenB}`;
        const sellPairKey = `${sellDex}-${tokenA}-${tokenB}`;
        
        const buyPair = tokenPairs[buyPairKey];
        const sellPair = tokenPairs[sellPairKey];

        if (!buyPair || !sellPair || !buyPair.reserves || !sellPair.reserves) {
            return { isProfitable: false };
        }
        
        try {
            const [reservesBuyLoanToken, reservesBuyOtherToken] = sortReserves(buyPair, loanToken, buyPair.reserves);
            const [reservesSellLoanToken, reservesSellOtherToken] = sortReserves(sellPair, loanToken, sellPair.reserves);

            const optimalLoanAmount = calculateOptimalLoanAmount(
                reservesBuyLoanToken,
                reservesBuyOtherToken,
                reservesSellOtherToken,
                reservesSellLoanToken
            );
            
            if (optimalLoanAmount.isZero() || optimalLoanAmount.lt(ethers.utils.parseEther("0.1"))) {
                return { isProfitable: false };
            }

            let amountOut = getAmountOutLocal(optimalLoanAmount, reservesBuyLoanToken, reservesBuyOtherToken);
            if (amountOut.isZero()) return { isProfitable: false };

            let finalAmount = getAmountOutLocal(amountOut, reservesSellOtherToken, reservesSellLoanToken);

            const grossProfit = finalAmount.sub(optimalLoanAmount);
            if (grossProfit.lte(0)) return { isProfitable: false };
            
            const priorityFee = feeData.maxPriorityFeePerGas || ethers.utils.parseUnits('1', 'gwei');
            const totalGasPrice = feeData.lastBaseFeePerGas.add(priorityFee);
            const gasCost = baseGasEstimate.mul(totalGasPrice);
            const gasCostUSD = parseFloat(ethers.utils.formatEther(gasCost)) * ethPriceUSD;
            
            const flashLoanFee = optimalLoanAmount.mul(9).div(10000);
            const flashLoanFeeUSD = parseFloat(ethers.utils.formatEther(flashLoanFee)) * ethPriceUSD;
            
            const netProfitGross = grossProfit.sub(flashLoanFee);
            const netProfitUSD = (parseFloat(ethers.utils.formatEther(netProfitGross)) * ethPriceUSD) - gasCostUSD;

            const isProfitable = netProfitUSD > config.minProfitUSD;
            if (isProfitable) {
                const minProfitInLoanToken = ethers.utils.parseEther((config.minProfitUSD / ethPriceUSD).toString());
                return { isProfitable: true, netProfitUSD, path, loanAmount: optimalLoanAmount, minProfit: minProfitInLoanToken };
            }

            return { isProfitable: false };
        } catch (error) {
            return { isProfitable: false };
        }
    }
    
    async function executeArbitrage(opportunity, feeData, blockNumber) {
        isExecuting = true;
        try {
            const { path, netProfitUSD, loanAmount, minProfit } = opportunity;
            const { buyDex, sellDex, loanToken, otherToken } = path;
            const buyRouterAddress = config.dexFactories[buyDex];
            const sellRouterAddress = config.dexFactories[sellDex];

            console.log(`正在执行套利交易... 预估利润: $${netProfitUSD.toFixed(2)}`);
            
            // 【强化 Gas 估算】在执行前进行最终的、精确的Gas估算，作为双重保险
            const finalGasEstimate = await arbitrageContract.estimateGas.performArbitrage(
                loanToken, otherToken, loanAmount, buyRouterAddress, sellRouterAddress, minProfit
            );

            console.log(`  - 精确 Gas 估算: ${finalGasEstimate.toString()} | 初始估算: ${baseGasEstimate.toString()}`);
            
            // 【Flashbots】构建交易捆绑包 (Bundle)
            const transaction = await arbitrageContract.populateTransaction.performArbitrage(
                loanToken,
                otherToken,
                loanAmount,
                buyRouterAddress,
                sellRouterAddress,
                minProfit,
                { 
                    gasLimit: finalGasEstimate.mul(12).div(10), // 使用精确估算并增加 20% 缓冲
                    maxFeePerGas: feeData.maxFeePerGas,
                    maxPriorityFeePerGas: feeData.maxPriorityFeePerGas,
                    nonce: await wallet.getTransactionCount()
                }
            );

            const signedTransaction = await wallet.signTransaction(transaction);
            const bundle = [{ signedTransaction }];
            const targetBlock = blockNumber + 1;

            console.log(`  - 正在将交易捆绑包提交给 Flashbots，目标区块: ${targetBlock}`);
            
            // 发送捆绑包
            const bundleSubmission = await flashbotsProvider.sendRawBundle(bundle, targetBlock);
            
            if ('error' in bundleSubmission) {
                throw new Error(`Flashbots 提交失败: ${bundleSubmission.error.message}`);
            }

            console.log('  - 捆绑包已成功提交至 Flashbots 中继。等待上链...');
            const waitResponse = await bundleSubmission.wait();

            // https://docs.flashbots.net/flashbots-auction/searchers/advanced/bundle-statuses
            if (waitResponse === 0) {
                 console.log('  - 交易已成功上链并被包含在目标区块中!');
            } else if (waitResponse === 1) {
                throw new Error("交易在捆绑包中，但未成功执行 (可能被其他交易抢跑或 reverting)");
            } else if (waitResponse === 2) {
                 throw new Error("捆绑包未被矿工选择 (可能出价过低)");
            }
        } catch(error) {
            console.error(`  - 交易执行失败:`, error.reason || error.message);
        } finally {
            isExecuting = false;
        }
    }

    // --- 工具函数 ---
    function sqrt(value) {
        if (value.lt(ethers.constants.Zero)) throw 'square root of negative numbers is not supported';
        if (value.lt(ethers.constants.Two)) return value;
        const TWO = ethers.constants.Two;
        let x = value.div(TWO);
        let y = value;
        while (x.lt(y)) {
            y = x;
            x = value.div(x).add(x).div(TWO);
        }
        return y;
    }
    
    function calculateOptimalLoanAmount(rA, rB, r_B, r_A) {
        try {
            const FEE = ethers.BigNumber.from(997);
            const FEE_DIVISOR = ethers.BigNumber.from(1000);
            
            const priceNumerator = r_A.mul(rB);
            const priceDenominator = r_B.mul(rA);

            if(priceDenominator.isZero() || priceNumerator.lte(priceDenominator)) {
                return ethers.constants.Zero;
            }

            const SCALE = ethers.utils.parseEther('1');
            const scaledNumerator = priceNumerator.mul(SCALE);
            const priceRatio = scaledNumerator.div(priceDenominator);
            const sqrtPriceRatio = sqrt(priceRatio);

            const term = rA.mul(sqrtPriceRatio).div(SCALE);
            const numerator = term.sub(rA);
            const optimalAmount = numerator.mul(FEE_DIVISOR).div(FEE);
            
            return optimalAmount;
        } catch (e) {
            return ethers.constants.Zero;
        }
    }

    function getAmountOutLocal(amountIn, reserveIn, reserveOut) {
        if (amountIn.isZero() || reserveIn.isZero() || reserveOut.isZero()) {
            return ethers.BigNumber.from(0);
        }
        const amountInWithFee = amountIn.mul(997);
        const numerator = amountInWithFee.mul(reserveOut);
        const denominator = reserveIn.mul(1000).add(amountInWithFee);
        if (denominator.isZero()) return ethers.BigNumber.from(0);
        return numerator.div(denominator);
    }
    
    function sortReserves(pairInfo, tokenIn, reserves) {
        return pairInfo.token0 === tokenIn ? [reserves.reserve0, reserves.reserve1] : [reserves.reserve1, reserves.reserve0];
    }
    
    async function getTokenSymbol(address) {
        if (tokenSymbolCache[address]) return tokenSymbolCache[address];
        try {
            const contract = new ethers.Contract(address, erc20SymbolABI, provider);
            const symbol = await contract.symbol();
            tokenSymbolCache[address] = symbol;
            return symbol;
        } catch {
            console.warn(`  - 警告: 无法获取地址 ${address} 的代币符号。`);
            tokenSymbolCache[address] = "UNKNOWN";
            return "UNKNOWN";
        }
    }

    process.on('SIGINT', () => {
        console.log("\n正在关闭机器人...");
        provider.removeAllListeners();
        process.exit(0);
    });
}

main().catch(error => {
    console.error("机器人启动失败:", error);
    process.exit(1);
});