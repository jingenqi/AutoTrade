const { ethers, getAddress, ZeroAddress, Contract, JsonRpcProvider, WebSocketProvider, Wallet } = require("ethers");
// 【Flashbots】导入 Flashbots 库。请确保已通过 `npm install @flashbots/ethers-provider-bundle` 安装
const { FlashbotsBundleProvider } = require("@flashbots/ethers-provider-bundle");
require("dotenv").config();

// --- 模块导入 ---
const { Config } = require("./config.js");
const { BotState } = require("./state.js");

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
const erc20SymbolABI = [
    {"inputs":[],"name":"symbol","outputs":[{"internalType":"string","name":"","type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"name","outputs":[{"internalType":"string","name":"","type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"decimals","outputs":[{"internalType":"uint8","name":"","type":"uint8"}],"stateMutability":"view","type":"function"}
];

// 【新增】企业级数据验证和错误处理工具类
class DataValidator {
    static isValidAddress(address) {
        try {
            return address && ethers.isAddress(address);
        } catch {
            return false;
        }
    }

    static isValidBigInt(value, min = 0n) {
        return value !== null && value !== undefined && typeof value === 'bigint' && value >= min;
    }

    static isValidNumber(value, min = 0) {
        return typeof value === 'number' && !isNaN(value) && isFinite(value) && value >= min;
    }

    static isValidPrice(price) {
        return this.isValidNumber(price, 0.01); // 最小价格1分
    }

    static safeParseFloat(value, defaultValue = 0) {
        try {
            if (value === null || value === undefined) return defaultValue;
            const parsed = parseFloat(value);
            return isNaN(parsed) || !isFinite(parsed) ? defaultValue : parsed;
        } catch {
            return defaultValue;
        }
    }

    static safeBigIntOperation(operation, defaultValue = 0n) {
        try {
            const result = operation();
            return this.isValidBigInt(result) ? result : defaultValue;
        } catch {
            return defaultValue;
        }
    }
}

// 【新增】企业级价格feed管理器
class PriceFeedManager {
    constructor(dependencies) {
        this.dependencies = dependencies;
        this.priceCache = new Map();
        this.lastUpdateTime = 0;
        this.updateInterval = 30000; // 30秒缓存
        this.maxRetries = 3;
        this.fallbackPrices = {
            ETH: 2500.0, // 保守的ETH价格
        };
    }

    async getETHPrice() {
        const now = Date.now();
        
        // 检查缓存
        if (this.priceCache.has('ETH') && (now - this.lastUpdateTime) < this.updateInterval) {
            return this.priceCache.get('ETH');
        }

        // 尝试多个数据源
        const priceSources = [
            () => this.getChainlinkPrice(),
            () => this.getCoinGeckoPrice(),
            () => this.getBinancePrice()
        ];

        for (const source of priceSources) {
            try {
                const price = await source();
                if (DataValidator.isValidPrice(price)) {
                    this.priceCache.set('ETH', price);
                    this.lastUpdateTime = now;
                    console.log(`  - [价格管理器] ETH价格更新: $${price.toFixed(2)}`);
                    return price;
                }
            } catch (error) {
                console.warn(`  - [价格管理器] 价格源失败: ${error.message}`);
            }
        }

        // 使用备用价格
        const fallbackPrice = this.fallbackPrices.ETH;
        console.warn(`  - [价格管理器] 使用备用ETH价格: $${fallbackPrice.toFixed(2)}`);
        return fallbackPrice;
    }

    async getChainlinkPrice() {
        if (!this.dependencies.ethPriceFeed) {
            throw new Error("Chainlink price feed not available");
        }

        for (let attempt = 0; attempt < this.maxRetries; attempt++) {
            try {
                const priceData = await this.dependencies.ethPriceFeed.latestRoundData();
                
                if (!priceData || !priceData.answer) {
                    throw new Error("Invalid price data from Chainlink");
                }

                // 检查数据新鲜度（在测试网上放宽限制）
                const maxAge = process.env.NETWORK === 'sepolia' ? 86400 : 3600; // 测试网24小时，主网1小时
                const dataAge = Date.now() / 1000 - Number(priceData.updatedAt);
                if (dataAge > maxAge) {
                    throw new Error(`Price data too old: ${dataAge}s`);
                }

                let price = DataValidator.safeParseFloat(ethers.formatUnits(priceData.answer, 8));
                if (!DataValidator.isValidPrice(price)) {
                    throw new Error(`Invalid price value: ${price}`);
                }

                // 【新增】为测试网添加小幅度的价格波动模拟
                if (process.env.NETWORK === 'sepolia') {
                    const fluctuation = (Math.random() - 0.5) * 0.02; // ±1%波动
                    price = price * (1 + fluctuation);
                    console.log(`  - [价格管理器] 添加测试网价格波动: ${(fluctuation * 100).toFixed(2)}%`);
                }

                return price;
            } catch (error) {
                if (attempt === this.maxRetries - 1) throw error;
                await new Promise(resolve => setTimeout(resolve, 1000 * (attempt + 1)));
            }
        }
    }

    async getCoinGeckoPrice() {
        // 这里可以添加CoinGecko API调用
        throw new Error("CoinGecko API not implemented");
    }

    async getBinancePrice() {
        // 这里可以添加Binance API调用
        throw new Error("Binance API not implemented");
    }
}

// 【新增】企业级代币管理器
class TokenManager {
    constructor(dependencies) {
        this.dependencies = dependencies;
        this.tokenCache = new Map();
        this.maxRetries = 3;
        this.retryDelay = 1000;
    }

    async getTokenInfo(address) {
        if (!DataValidator.isValidAddress(address)) {
            throw new Error(`Invalid token address: ${address}`);
        }

        const normalizedAddress = address.toLowerCase();
        
        // 检查缓存
        if (this.tokenCache.has(normalizedAddress)) {
            return this.tokenCache.get(normalizedAddress);
        }

        for (let attempt = 0; attempt < this.maxRetries; attempt++) {
            try {
                const contract = new Contract(address, erc20SymbolABI, this.dependencies.provider);
                
                // 并行获取代币信息
                const [symbol, name, decimals] = await Promise.all([
                    this.safeContractCall(() => contract.symbol(), 'UNKNOWN'),
                    this.safeContractCall(() => contract.name(), 'Unknown Token'),
                    this.safeContractCall(() => contract.decimals(), 18)
                ]);

                const tokenInfo = {
                    address: address,
                    symbol: symbol,
                    name: name,
                    decimals: Number(decimals)
                };

                this.tokenCache.set(normalizedAddress, tokenInfo);
                console.log(`  - [代币管理器] 成功获取代币信息: ${symbol} (${name})`);
                return tokenInfo;

            } catch (error) {
                console.warn(`  - [代币管理器] 尝试 ${attempt + 1}/${this.maxRetries} 失败: ${error.message}`);
                if (attempt === this.maxRetries - 1) {
                    // 创建备用代币信息
                    const fallbackInfo = {
                        address: address,
                        symbol: `TOKEN_${address.slice(2, 8).toUpperCase()}`,
                        name: `Token ${address.slice(2, 8)}`,
                        decimals: 18
                    };
                    this.tokenCache.set(normalizedAddress, fallbackInfo);
                    return fallbackInfo;
                }
                await new Promise(resolve => setTimeout(resolve, this.retryDelay * (attempt + 1)));
            }
        }
    }

    async safeContractCall(call, defaultValue) {
        try {
            const result = await call();
            return result !== null && result !== undefined ? result : defaultValue;
        } catch {
            return defaultValue;
        }
    }
}

// 【重构】将整个机器人逻辑封装在一个类中，以实现更好的状态管理和模块化
class ArbitrageBot {
    constructor() {
        this.config = new Config().get();
        this.state = new BotState();
        this.dependencies = { provider: null, wallet: null, authSigner: null, flashbotsProvider: null, arbitrageContract: null, ethPriceFeed: null, priceFeedManager: null, tokenManager: null };
        this.connection = { heartbeatInterval: null, currentProviderUrl: this.config.providerUrl, reconnectAttempts: 0 };

        process.on('SIGINT', () => {
            console.log("\n正在关闭机器人...");
            if (this.dependencies.provider) this.dependencies.provider.removeAllListeners();
            if (this.connection.heartbeatInterval) clearInterval(this.connection.heartbeatInterval);
            process.exit(0);
        });
    }

    async run() {
        await this.connect(true);
    }
    
    async connect(isInitial = false) {
        if (this.dependencies.provider?._websocket) {
            this.dependencies.provider.removeAllListeners();
            this.dependencies.provider._websocket.terminate();
        }
        if (this.connection.heartbeatInterval) clearInterval(this.connection.heartbeatInterval);

        console.log(`[连接管理] 正在连接到 ${this.connection.currentProviderUrl}...`);
        
        try {
            const provider = new WebSocketProvider(this.connection.currentProviderUrl);
            await Promise.race([
                provider.getNetwork().then(net => { if (!net) throw new Error("Network not found"); }),
                new Promise((_, reject) => setTimeout(() => reject(new Error("连接超时")), 10000))
            ]);

            console.log("[连接管理] 节点连接成功!");
            
            this.dependencies.provider = provider;
            this.dependencies.wallet = new Wallet(this.config.privateKey, provider);
            this.dependencies.authSigner = new Wallet(this.config.authKey, provider);
            
            const flashbotsRpcProvider = new JsonRpcProvider(this.config.rpcUrl);
            this.dependencies.flashbotsProvider = await FlashbotsBundleProvider.create(flashbotsRpcProvider, this.dependencies.authSigner);
            
            this.dependencies.arbitrageContract = new Contract(this.config.contractAddress, ArbitrageABI, this.dependencies.wallet);
            this.dependencies.ethPriceFeed = new Contract(this.config.ethPriceFeedAddress, aggregatorV3InterfaceABI, provider);
            this.dependencies.priceFeedManager = new PriceFeedManager(this.dependencies);
            this.dependencies.tokenManager = new TokenManager(this.dependencies);

            provider.on('block', this.blockHandler.bind(this));
            provider.websocket.on('close', async (code) => {
                console.error(`[连接管理] 节点连接已断开 (Code: ${code})。将尝试重新连接...`);
                await this.reconnect();
            });

            this.startHeartbeat();
            
            if (isInitial) {
                console.log("工业级套利机器人正在启动...");
                console.log(` - 网络: ${this.config.network}, 钱包地址: ${this.dependencies.wallet.address}`);
                await this.initialize();
                console.log("启动成功! 机器人现在监听新的以太坊区块...");
            } else {
                console.log("[连接管理] 重新连接成功，机器人恢复运行。");
            }
        } catch (error) {
            console.error(`[连接管理] 连接失败: ${error.message}`);
            await this.reconnect();
        }
    }

    async reconnect() {
        this.connection.reconnectAttempts++;
        const delay = Math.min(1000 * (2 ** this.connection.reconnectAttempts), 30000);
        console.log(`[连接管理] ${delay / 1000}秒后进行下一次重连...`);
        
        await new Promise(resolve => setTimeout(resolve, delay));

        if (this.connection.reconnectAttempts > 2 && this.config.backupProviderUrl && this.connection.currentProviderUrl !== this.config.backupProviderUrl) {
            console.log("[连接管理] 主节点多次连接失败，尝试切换到备用节点。");
            this.connection.currentProviderUrl = this.config.backupProviderUrl;
            this.connection.reconnectAttempts = 0; 
        }
        await this.connect();
    }
    
    startHeartbeat() {
        if (this.connection.heartbeatInterval) clearInterval(this.connection.heartbeatInterval);
        
        this.connection.heartbeatInterval = setInterval(async () => {
            try {
                if (this.dependencies.provider?.websocket?.readyState !== 1) throw new Error("WebSocket not open");
                await this.dependencies.provider.getBlockNumber();
            } catch (e) {
                console.error(`[心跳检测] 心跳失败，触发重连: ${e.message}`);
                clearInterval(this.connection.heartbeatInterval);
                await this.reconnect();
            }
        }, 15000); 
    }

    async blockHandler(blockNumber) {
        if (this.state.isExecuting || this.state.isPaused) return;

        if (Date.now() > this.state.dailyResetTimestamp) {
            this.state.gasSpentTodayUSD = 0;
            this.state.dailyResetTimestamp = this.state.getNextUTCDay();
            console.log(`[风控] 新的一天开始，重置每日Gas花费上限。`);
        }
        if (this.state.gasSpentTodayUSD > this.config.dailyGasLimitUSD) {
            console.log(`[风控] 已达到每日Gas花费上限，今日暂停交易。`);
            return;
        }
        console.log(`\n[${new Date().toLocaleTimeString()} | 区块: ${blockNumber}] 扫描套利机会...`);
        await this.mainLoop(blockNumber);
    }

    async mainLoop(blockNumber) {
        try {
            const [feeData, ethPriceUSD] = await Promise.all([
                this.dependencies.provider.getFeeData(),
                this.dependencies.priceFeedManager.getETHPrice()
            ]);

            if (!feeData?.lastBaseFeePerGas || !DataValidator.isValidPrice(ethPriceUSD)) {
                console.warn("  - 警告: 无法获取市场数据，跳过本轮扫描");
                return;
            }
            
            const reservesData = await Promise.all(Object.values(this.state.tokenPairs).map(p => this.safeGetReserves(p)));
            let validPairsCount = 0;
            Object.keys(this.state.tokenPairs).forEach((key, i) => {
                if (reservesData[i]) {
                    this.state.tokenPairs[key].reserves = reservesData[i];
                    validPairsCount++;
                } else this.state.tokenPairs[key].reserves = null;
            });
            if (validPairsCount === 0) return;

            const arbitragePaths = await this.buildArbitragePaths();
            const profitableOpportunities = arbitragePaths
                .map(path => this.checkPath(path, ethPriceUSD, feeData))
                .filter(opp => opp?.isProfitable);

            if (profitableOpportunities.length > 0) {
                const best = profitableOpportunities.sort((a, b) => b.netProfitUSD - a.netProfitUSD)[0];
                console.log(`>>> 发现盈利机会! 预估利润: $${best.netProfitUSD.toFixed(2)} | 路径: ${best.path.buyDex} -> ${best.path.sellDex}`);
                await this.executeArbitrage(best, feeData, blockNumber, ethPriceUSD);
            }
        } catch (error) {
            console.error("主循环发生严重错误:", error.message, error.stack);
        }
    }

    async safeGetReserves(pairInfo) {
        if (pairInfo?.isSimulated) return pairInfo.reserves;
        try { return await pairInfo.contract.getReserves(); } catch { return null; }
    }

    async initialize() {
        console.log("正在初始化...");
        const tokenInfos = await Promise.all(this.config.watchList.map(addr => this.dependencies.tokenManager.getTokenInfo(addr)));

        const pairPromises = [];
        for (let i = 0; i < this.config.watchList.length; i++) {
            for (let j = i + 1; j < this.config.watchList.length; j++) {
                for (const dexName in this.config.dexFactories) {
                    pairPromises.push(this.loadPair(dexName, this.config.watchList[i], this.config.watchList[j]));
                }
            }
        }
        await Promise.all(pairPromises);

        if (Object.keys(this.state.tokenPairs).length === 0 && this.config.fallbackMode?.enableSimulation) {
            this.initializeSimulationMode(tokenInfos);
        }
        
        try {
            const samplePath = (await this.buildArbitragePaths())[0];
            if (!samplePath) throw new Error("无法构建Gas估算路径");
            this.state.baseGasEstimate = await this.dependencies.arbitrageContract.performArbitrage.estimateGas(
                samplePath.loanToken, samplePath.otherToken, ethers.parseEther("1"),
                this.config.dexFactories[samplePath.buyDex], this.config.dexFactories[samplePath.sellDex], ethers.parseEther("0.001")
            );
            console.log(`  - 基础 Gas 估算: ${this.state.baseGasEstimate.toString()}`);
        } catch (error) {
            console.error(`关键错误: 无法估算 Gas: ${error.message}. 使用默认值。`);
        }
        console.log("初始化完成!");
    }

    initializeSimulationMode(tokenInfos) {
        const usdc = tokenInfos.find(t => t.symbol === 'USDC');
        const dai = tokenInfos.find(t => t.symbol === 'DAI');
        if (usdc && dai) {
            const key = `UniswapV2-${usdc.address.toLowerCase()}-${dai.address.toLowerCase()}`;
            this.state.tokenPairs[key] = {
                contract: null, token0: usdc.address, isSimulated: true,
                reserves: [ethers.parseUnits("1000000", 6), ethers.parseEther("1000000"), Math.floor(Date.now() / 1000)]
            };
            console.log("  [模拟模式] 已创建 USDC-DAI 模拟交易对。");
        }
    }

    async loadPair(dexName, tokenA, tokenB) {
        try {
            const factory = new Contract(this.config.dexFactories[dexName], factoryABI, this.dependencies.provider);
            const pairAddress = await factory.getPair(tokenA, tokenB);
            if (pairAddress !== ZeroAddress) {
                const pairContract = new Contract(pairAddress, pairABI, this.dependencies.provider);
                const token0 = await pairContract.token0();
                const key = `${dexName}-${tokenA.toLowerCase() < tokenB.toLowerCase() ? tokenA : tokenB}-${tokenA.toLowerCase() < tokenB.toLowerCase() ? tokenB : tokenA}`;
                this.state.tokenPairs[key] = { contract: pairContract, token0: token0, reserves: null };
            }
        } catch {}
    }

    async buildArbitragePaths() {
        const paths = [], uniquePairs = {};
        Object.keys(this.state.tokenPairs).forEach(key => {
             const [dex, tA, tB] = key.split('-');
             const id = `${tA}-${tB}`;
             if(!uniquePairs[id]) uniquePairs[id] = [];
             uniquePairs[id].push(dex);
        });

        for(const id in uniquePairs){
            if(uniquePairs[id].length < 2) continue;
            const [tA, tB] = id.split('-');
            const loanToken = this.config.watchList[0];
            if (loanToken.toLowerCase() !== tA && loanToken.toLowerCase() !== tB) continue;
            
            const otherToken = (loanToken.toLowerCase() === tA) ? tB : tokenA;
            const [loanTokenInfo, otherTokenInfo] = await Promise.all([
                this.dependencies.tokenManager.getTokenInfo(loanToken), this.dependencies.tokenManager.getTokenInfo(otherToken)
            ]);
            for(const buyDex of uniquePairs[id]) {
                for(const sellDex of uniquePairs[id]) {
                    if(buyDex !== sellDex) paths.push({ buyDex, sellDex, loanToken, otherToken, token0Symbol: loanTokenInfo.symbol, token1Symbol: otherTokenInfo.symbol });
                }
            }
        }
        return paths;
    }
    
    checkPath(path, ethPriceUSD, feeData) {
        const { buyDex, sellDex, loanToken, otherToken } = path;
        const keyA = loanToken.toLowerCase() < otherToken.toLowerCase() ? loanToken : otherToken;
        const keyB = loanToken.toLowerCase() < otherToken.toLowerCase() ? otherToken : loanToken;
        const buyPair = this.state.tokenPairs[`${buyDex}-${keyA}-${keyB}`];
        const sellPair = this.state.tokenPairs[`${sellDex}-${keyA}-${keyB}`];

        if (!buyPair?.reserves || !sellPair?.reserves) return null;
        
        const gasCost = this.state.baseGasEstimate * (feeData.lastBaseFeePerGas + (feeData.maxPriorityFeePerGas || 0n));
        const gasCostUSD = parseFloat(ethers.formatEther(gasCost)) * ethPriceUSD;

        const [resBuyL, resBuyO] = this.sortReserves(buyPair, loanToken);
        const [resSellL, resSellO] = this.sortReserves(sellPair, loanToken);

        const optimalLoan = this.calculateOptimalLoanAmount(resBuyL, resBuyO, resSellO, resSellL);
        if (optimalLoan <= 0n) return null;

        const amountOut = this.getAmountOutLocal(optimalLoan, resBuyL, resBuyO);
        const finalAmount = this.getAmountOutLocal(amountOut, resSellO, resSellL);
        
        const feeRate = this.config.network === 'mainnet' ? 9n : 5n;
        const netProfit = (finalAmount - optimalLoan) - ((optimalLoan * feeRate) / 10000n);
        const netProfitUSD = (parseFloat(ethers.formatEther(netProfit)) * ethPriceUSD) - gasCostUSD;

        if (netProfitUSD > this.config.minProfitUSD && netProfitUSD > (gasCostUSD * this.config.minProfitToGasRatio)) {
            return { isProfitable: true, netProfitUSD, path, loanAmount: optimalLoan, minProfit: ethers.parseEther((this.config.minProfitUSD / ethPriceUSD).toString()) };
        }
        return null;
    }
    
    sortReserves(pairInfo, tokenIn) {
        return pairInfo.token0 === tokenIn ? pairInfo.reserves : [pairInfo.reserves[1], pairInfo.reserves[0]];
    }

    getAmountOutLocal(amountIn, reserveIn, reserveOut) {
        const amountInWithFee = amountIn * 997n;
        return (amountInWithFee * reserveOut) / (reserveIn * 1000n + amountInWithFee);
    }
    
    calculateOptimalLoanAmount(rA, rB, r_B, r_A) {
        if (r_B * rA === 0n || r_A * rB <= r_B * rA) return 0n;
        const sqrtPriceRatio = this.sqrt((r_A * rB * ethers.parseEther('1')) / (r_B * rA));
        return (((rA * sqrtPriceRatio) / ethers.parseEther('1')) - rA) * 1000n / 997n;
    }
    
    sqrt(value) {
        if (value < 0n) throw 'sqrt of negative value';
        if (value < 2n) return value;
        let x = value / 2n;
        let y = value;
        while (x < y) { y = x; x = (value / x + x) / 2n; }
        return y;
    }

    async executeArbitrage(opportunity, feeData, blockNumber, ethPriceUSD) {
        this.state.isExecuting = true;
        let txReceipt = null;
        try {
            const { path, loanAmount, minProfit } = opportunity;
            const transaction = {
                to: this.dependencies.arbitrageContract.target,
                data: this.dependencies.arbitrageContract.interface.encodeFunctionData("performArbitrage", [path.loanToken, path.otherToken, loanAmount, this.config.dexFactories[path.buyDex], this.config.dexFactories[path.sellDex], minProfit]),
                gasLimit: (this.state.baseGasEstimate * 120n) / 100n,
                maxFeePerGas: feeData.maxFeePerGas,
                maxPriorityFeePerGas: feeData.maxPriorityFeePerGas,
                nonce: await this.dependencies.wallet.getNonce('pending'),
                type: 2,
                chainId: this.config.network === 'sepolia' ? 11155111 : 1
            };

            const signedTx = await this.dependencies.wallet.signTransaction(transaction);
            const bundleSub = await this.dependencies.flashbotsProvider.sendRawBundle([{ signedTransaction: signedTx }], blockNumber + 1);
            if ('error' in bundleSub) throw new Error(`Flashbots submission error: ${bundleSub.error.message}`);
            
            const waitResult = await bundleSub.wait();
            if (waitResult !== 0) throw new Error(`Flashbots transaction failed with code: ${waitResult}`);
            
            txReceipt = await this.dependencies.provider.getTransactionReceipt(ethers.keccak256(signedTx));
            if (!txReceipt || txReceipt.status !== 1) throw new Error(`Transaction reverted or receipt not found.`);
            
            this.state.consecutiveFailures = 0;
            console.log("  - ✅ 套利成功!");
        } catch(error) {
            this.state.consecutiveFailures++;
            console.error(`  - ❌ 交易执行失败: ${error.message}`);
            if (this.state.consecutiveFailures >= this.config.maxConsecutiveFailures) {
                this.state.isPaused = true;
                console.error(`[风控] 暂停机器人 ${this.config.circuitBreakerCooldownMinutes} 分钟。`);
                if (this.state.pauseTimeout) clearTimeout(this.state.pauseTimeout);
                this.state.pauseTimeout = setTimeout(() => {
                    this.state.isPaused = false;
                    this.state.consecutiveFailures = 0;
                    console.log("[风控] 机器人恢复运行。");
                }, this.config.circuitBreakerCooldownMinutes * 60 * 1000);
            }
        } finally {
            if (txReceipt) await this.recordTransactionResult(txReceipt, ethPriceUSD);
            this.state.isExecuting = false;
        }
    }

    async recordTransactionResult(txReceipt, ethPriceUSD) {
        try {
            const gasCost = txReceipt.gasUsed * txReceipt.effectiveGasPrice;
            const costUSD = parseFloat(ethers.formatEther(gasCost)) * ethPriceUSD;
            this.state.gasSpentTodayUSD += costUSD;
            console.log(`  - Gas 成本: ${ethers.formatEther(gasCost)} ETH ($${costUSD.toFixed(2)}) | 今日累计: $${this.state.gasSpentTodayUSD.toFixed(2)}`);
        } catch(e) { 
            console.error("  - Gas成本核算失败:", e.message); 
        }
    }
}

// --- 启动 ---
const bot = new ArbitrageBot();
bot.run().catch(error => {
    console.error("机器人主程序发生致命错误:", error);
    process.exit(1);
});
