const { ethers, getAddress, ZeroAddress, Contract, JsonRpcProvider, WebSocketProvider, Wallet } = require("ethers");
// 【重构】导入 FlashbotsBundleProvider 和 FlashbotsBundleResolution
const { FlashbotsBundleProvider, FlashbotsBundleResolution } = require("@flashbots/ethers-provider-bundle");
require("dotenv").config();

// --- ABIs: 加载所需的合约接口 ---
const { abi: ArbitrageABI } = require("../artifacts/contracts/FlashLoanArbitrage.sol/FlashLoanArbitrage.json");
// ... (ABIs remain the same)
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


// 【重构】将所有网络配置移至顶层，便于管理
const ALL_CONFIGS = {
    mainnet: {
        providerUrl: process.env.MAINNET_WSS_URL,
        backupProviderUrl: process.env.MAINNET_WSS_URL_BACKUP,
        contractAddress: "0xe24ae1fd16e7226dd4287d74f097962057cc5f59",
        watchList: [
            getAddress("0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"), // WETH
            getAddress("0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"), // USDC
            getAddress("0x6b175474e89094c44da98b954eedeac495271d0f"), // DAI
        ],
        dexFactories: {
            "UniswapV2": getAddress("0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f"),
            "SushiSwap": getAddress("0xc0aee478e3658e2610c5f7a4a2e1777ce9e4f2ac")
        },
        // 新增：DEX路由器地址，用于执行交易
        dexRouters: {
            "UniswapV2": getAddress("0x7a250d5630b4cf539739df2c5dacb4c659f2488d"),
            "SushiSwap": getAddress("0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f")
        },
        ethPriceFeedAddress: getAddress("0x5f4ec3df9cbd43714fe274045f3642155d8407aa"),
    },
    sepolia: {
        providerUrl: process.env.SEPOLIA_WSS_URL,
        rpcUrl: process.env.SEPOLIA_HTTPS_URL,
        backupProviderUrl: process.env.SEPOLIA_WSS_URL_BACKUP,
        contractAddress: "0xe24ae1fd16e7226dd4287d74f097962057cc5f59",
        watchList: [
            getAddress("0xfff9976782d46cc05630d1f6ebab18b2324d6b14"), // WETH on Sepolia
            getAddress("0x1f9840a85d5af5bf1d1762f925bdaddc4201f984"), // UNI on Sepolia
            getAddress("0xb233ac35c58d315357b3766723b75485f2694452")  // SUSHI on Sepolia
        ],
        dexFactories: {
            "UniswapV2": getAddress("0x7e0987e5b3a30e3f2828572bb659a548460a3003"),
            "SushiSwap": getAddress("0xc35dadb65012ec5796536bd9864ed8773abc74c4"),
        },
        // 新增：DEX路由器地址，用于执行交易
        dexRouters: {
            "UniswapV2": getAddress("0xc532a74256d3db42139c0955870511533d1a756f"),
            "SushiSwap": getAddress("0x1b02da8cb0d097eb8d57a175b88c7d8b47997506"),
        },
        ethPriceFeedAddress: getAddress("0x694aa1769357215de4fac081bf1f309adc325306"), // ETH/USD on Sepolia
    }
};


// --- 辅助类 ---
class DataValidator { /* ... (内容不变) ... */ 
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
class PriceFeedManager { /* ... (内容不变) ... */ 
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

                const maxAge = process.env.NETWORK === 'sepolia' ? 86400 : 3600;
                const dataAge = Date.now() / 1000 - Number(priceData.updatedAt);
                if (dataAge > maxAge) {
                    throw new Error(`Price data too old: ${dataAge}s`);
                }

                let price = DataValidator.safeParseFloat(ethers.formatUnits(priceData.answer, 8));
                if (!DataValidator.isValidPrice(price)) {
                    throw new Error(`Invalid price value: ${price}`);
                }

                if (process.env.NETWORK === 'sepolia') {
                    const fluctuation = (Math.random() - 0.5) * 0.02;
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
        throw new Error("CoinGecko API not implemented");
    }

    async getBinancePrice() {
        throw new Error("Binance API not implemented");
    }
}
class TokenManager { /* ... (内容不变) ... */ 
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
        
        if (this.tokenCache.has(normalizedAddress)) {
            return this.tokenCache.get(normalizedAddress);
        }

        for (let attempt = 0; attempt < this.maxRetries; attempt++) {
            try {
                const contract = new Contract(address, erc20SymbolABI, this.dependencies.provider);
                
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
class Utils { /* ... (内容不变) ... */
    static getNextUTCDay() {
        const now = new Date();
        const nextDay = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1));
        return nextDay.getTime();
    }

    static sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    static sqrt(value) {
        if (value < 0n) throw 'square root of negative numbers is not supported';
        if (value < 2n) return value;
        const TWO = 2n;
        let x = value / TWO;
        let y = value;
        while (x < y) {
            y = x;
            x = (value / x + x) / TWO;
        }
        return y;
    }
    
    static calculateOptimalLoanAmount(rA, rB, r_B, r_A) {
        // This function calculates the optimal input amount for an arbitrage trade.
        // It's based on the formula derived from maximizing the profit function for a trade
        // path: Token A -> Token B (Pool 1), then Token B -> Token A (Pool 2).
        //
        // Let:
        // rA, rB = reserves of Token A and Token B in Pool 1 (the "buy" pool)
        // r_A, r_B = reserves of Token A and Token B in Pool 2 (the "sell" pool)
        //
        // An arbitrage opportunity exists if the price in Pool 1 is less than Pool 2.
        // Price (A in terms of B) in Pool 1: rB / rA
        // Price (A in terms of B) in Pool 2: r_A / r_B
        // Opportunity check: rB / rA < r_A / r_B  => rB * r_B < r_A * rA

        // Numerically stable check for rB * r_B < r_A * rA
        if (rB * r_B >= r_A * rA) {
            return 0n; // No profit opportunity
        }

        const FEE = 997n;
        const FEE_DIVISOR = 1000n;

        // The widely cited formula for optimal AMM arbitrage is:
        // amount_in = (sqrt(reserve_A_pool1 * reserve_A_pool2 * fee_1 * fee_2) - reserve_A_pool1) / fee_1
        // Since fee_1 and fee_2 are the same (0.997), this simplifies.
        
        const fee_factor_sq = FEE * FEE;
        const reserve_product = rA * r_A;
        
        // We use the fee divisor to handle the fee calculation with integer arithmetic
        const sqrt_term = Utils.sqrt((reserve_product * fee_factor_sq) / (FEE_DIVISOR * FEE_DIVISOR));

        // If the sqrt term is less than or equal to the initial reserve, there's no profit.
        if (sqrt_term <= rA) {
            return 0n;
        }
        
        // Calculate optimal amount: (sqrt_term - rA) / (FEE / FEE_DIVISOR)
        // which is equivalent to (sqrt_term - rA) * FEE_DIVISOR / FEE
        const numerator = (sqrt_term - rA) * FEE_DIVISOR;
        const optimalAmount = numerator / FEE;

        return optimalAmount > 0n ? optimalAmount : 0n;
    }

    static getAmountOutLocal(amountIn, reserveIn, reserveOut) {
        if (amountIn === 0n || reserveIn === 0n || reserveOut === 0n) {
            return 0n;
        }
        const amountInWithFee = amountIn * 997n;
        const numerator = amountInWithFee * reserveOut;
        const denominator = reserveIn * 1000n + amountInWithFee;
        if (denominator === 0n) return 0n;
        return numerator / denominator;
    }
    
    static sortReserves(pairInfo, tokenIn, reserves) {
        return pairInfo.token0 === tokenIn ? [reserves[0], reserves[1]] : [reserves[1], reserves[0]];
    }
}


/**
 * @class ArbitrageBot
 * @description The main class for the arbitrage bot, encapsulating all logic, state, and dependencies.
 */
class ArbitrageBot {
    constructor() {
        this._initializeConfig();
        this._initializeState();
    }

    // --- 1. Initialization ---

    /**
     * @description Loads configuration based on the current network environment.
     * @private
     */
    _initializeConfig() {
        this.network = process.env.NETWORK || "mainnet";
        const networkConfig = ALL_CONFIGS[this.network];
        if (!networkConfig) {
            throw new Error(`Unsupported network: ${this.network}`);
        }

        this.config = {
            ...networkConfig,
            privateKey: process.env.PRIVATE_KEY,
            flashbotsKey: process.env.FLASHBOTS_AUTH_KEY,
            minProfitUSD: this.network === 'mainnet' ? 0.000000000001 : 0.000000000001,
            minProfitToGasRatio: this.network === 'mainnet' ? 0.0000000000000000005 : 0.0000000000001,
            slippageTolerance: 0.005, // 0.5% 滑点容忍度
            maxConsecutiveFailures: 3,
            circuitBreakerCooldownMinutes: this.network === 'mainnet' ? 60 : 5,
            dailyGasLimitUSD: this.network === 'mainnet' ? 50.0 : 10.0,
            enableFlashbotsFallback: true,
            txTimeoutBlocks: 3,
        };
    }

    /**
     * @description Sets up the initial state for the bot's operation.
     * @private
     */
    _initializeState() {
        this.isExecuting = false;
        this.consecutiveFailures = 0;
        this.gasSpentTodayUSD = 0;
        this.dailyResetTimestamp = Utils.getNextUTCDay();
        this.isPaused = false;
        this.pauseTimeout = null;
        this.heartbeatInterval = null;
        this.currentProviderUrl = this.config.providerUrl;
        this.reconnectAttempts = 0;
        this.tokenPairs = {};
        this.baseGasEstimate = 800000n;
        this.dependencies = {};
    }

    /**
     * @description Validates critical startup configurations from environment variables and config files.
     * @returns {boolean} True if the configuration is valid, otherwise false.
     * @private
     */
    _validateStartupConfig() {
        const { privateKey, flashbotsKey, providerUrl, contractAddress, rpcUrl } = this.config;
        if (!privateKey || !/^(0x)?[0-9a-fA-F]{64}$/.test(privateKey)) {
            console.error("\n[配置错误] .env 文件中的 PRIVATE_KEY 无效或缺失。");
            return false;
        }
        if (flashbotsKey && !/^(0x)?[0-9a-fA-F]{64}$/.test(flashbotsKey)) {
            console.error("\n[配置错误] .env 文件中的 FLASHBOTS_AUTH_KEY 存在但格式无效。");
            return false;
        }
        if (!providerUrl || contractAddress.startsWith("YOUR_")) {
            console.error(`配置错误: 请在 .env 文件中为 ${this.network} 网络设置 WSS_URL, 并在脚本中配置 contractAddress`);
            return false;
        }
        if (this.network === 'sepolia' && !rpcUrl) {
            console.error("\n[配置错误] .env 文件中缺少 SEPOLIA_HTTPS_URL 配置，Flashbots 无法初始化。\n");
            return false;
        }
        return true;
    }

    // --- 2. Connection Management ---

    /**
     * @description Establishes a connection to the blockchain provider and initializes all dependencies.
     * @param {boolean} isInitial - Whether this is the first connection attempt.
     * @returns {Promise<boolean>} True on successful connection, false otherwise.
     * @private
     */
    async _connect(isInitial = false) {
        if (this.dependencies.provider) {
            this.dependencies.provider.removeAllListeners();
            if (this.dependencies.provider.websocket) {
                this.dependencies.provider.websocket.terminate();
            }
        }
        if (this.heartbeatInterval) clearInterval(this.heartbeatInterval);

        console.log(`[连接管理] 正在连接到 ${this.network} 网络...`);
        
        try {
            const provider = new WebSocketProvider(this.currentProviderUrl);
            await Promise.race([
                provider.getNetwork().then(network => { if (!network) throw new Error("Network not found"); }),
                new Promise((_, reject) => setTimeout(() => reject(new Error("连接超时")), 10000))
            ]);
            console.log("[连接管理] 节点连接成功!");
            
            // Initialize dependencies
            this.dependencies.provider = provider;
            this.dependencies.wallet = new Wallet(this.config.privateKey, provider);
            this.dependencies.authSigner = new Wallet(this.config.flashbotsKey || this.config.privateKey, provider);
            const flashbotsRpcProvider = new JsonRpcProvider(this.config.rpcUrl);
            this.dependencies.flashbotsProvider = await FlashbotsBundleProvider.create(flashbotsRpcProvider, this.dependencies.authSigner);
            this.dependencies.arbitrageContract = new Contract(this.config.contractAddress, ArbitrageABI, this.dependencies.wallet);
            this.dependencies.ethPriceFeed = new Contract(this.config.ethPriceFeedAddress, aggregatorV3InterfaceABI, provider);
            this.dependencies.priceFeedManager = new PriceFeedManager(this.dependencies);
            this.dependencies.tokenManager = new TokenManager(this.dependencies);

            // Setup listeners
            provider.on('block', this._blockHandler.bind(this));
            provider.websocket.on('close', async (code) => {
                console.error(`[连接管理] 节点连接已断开 (Code: ${code})。将尝试重新连接...`);
                await this._reconnect();
            });
            provider.websocket.on('error', (err) => console.error(`[连接管理] 节点连接错误: ${err.message}。`));

            this._startHeartbeat();
            
            if (isInitial) {
                await this._logBanner();
                await this._loadInitialData();
                console.log("✅ 启动成功! 机器人现在监听新的以太坊区块...");
            } else {
                console.log("[连接管理] 重新连接成功，机器人恢复运行。");
            }

            return true;
        } catch (error) {
            console.error(`[连接管理] 连接失败: ${error.message}`);
            return false;
        }
    }

    /**
     * @description Handles reconnection logic with exponential backoff.
     * @private
     */
    async _reconnect() {
        if (this.heartbeatInterval) clearInterval(this.heartbeatInterval);
        this.reconnectAttempts++;
        const delay = Math.min(1000 * (2 ** this.reconnectAttempts), 30000);
        console.log(`[连接管理] ${delay / 1000}秒后进行下一次重连...`);
        
        await Utils.sleep(delay);

        if (this.reconnectAttempts > 2 && this.config.backupProviderUrl && this.currentProviderUrl !== this.config.backupProviderUrl) {
            console.log("[连接管理] 主节点多次连接失败，尝试切换到备用节点。");
            this.currentProviderUrl = this.config.backupProviderUrl;
            this.reconnectAttempts = 0; 
        }

        const success = await this._connect();
        if (success) {
            this.reconnectAttempts = 0;
        } else {
            await this._reconnect(); 
        }
    }
    
    /**
     * @description Starts a heartbeat interval to check the provider connection.
     * @private
     */
    _startHeartbeat() {
        if (this.heartbeatInterval) clearInterval(this.heartbeatInterval);
        
        let consecutiveFails = 0;
        this.heartbeatInterval = setInterval(async () => {
            if (!this.dependencies.provider || this.dependencies.provider.websocket?.readyState !== 1) return;
            try {
                await this.dependencies.provider.getBlockNumber();
                consecutiveFails = 0; 
            } catch (e) {
                consecutiveFails++;
                console.error(`[心跳检测] 失败 #${consecutiveFails}: 无法访问节点。`);
                if (consecutiveFails >= 3) {
                    console.error("[心跳检测] 连续3次心跳失败，触发重连机制。");
                    clearInterval(this.heartbeatInterval);
                    await this._reconnect();
                }
            }
        }, 15000); 
    }

    // --- 3. Core Logic ---

    /**
     * @description The main entry point for processing each new block.
     * @param {number} blockNumber - The current block number.
     * @private
     */
    async _blockHandler(blockNumber) {
        if (this.isExecuting || this.isPaused) return;

        this._checkDailyLimits();
        if (this.isPaused) return;

        console.log(`\n[${new Date().toLocaleTimeString()} | 区块: ${blockNumber}] 扫描套利机会...`);
        await this._mainLoop(blockNumber);
    }

    /**
     * @description The main loop that runs on every block to find and execute arbitrage.
     * @param {number} blockNumber - The current block number.
     * @private
     */
    async _mainLoop(blockNumber) {
        try {
            const marketData = await this._getMarketData();
            if (!marketData) return;

            const validPairsCount = await this._updateAndValidatePairs();
            if (validPairsCount === 0) {
                 console.warn("  - 警告: 没有有效的交易对储备数据，跳过本轮扫描");
                 return;
            }

            const baseFeeGwei = DataValidator.safeParseFloat(ethers.formatUnits(marketData.feeData.lastBaseFeePerGas || '0', 'gwei'));
            console.log(`  - 市场数据: ETH 价格 = $${marketData.ethPriceUSD.toFixed(2)} | 基础费 = ${baseFeeGwei.toFixed(2)} Gwei | 有效交易对 = ${validPairsCount}`);
            
            await this._findAndExecuteBestOpportunity(marketData, blockNumber);

        } catch (error) {
            console.error("主循环发生严重错误:", error.message, error.stack);
        }
    }

    /**
     * @description Finds the best arbitrage opportunity and triggers execution.
     * @param {object} marketData - Contains feeData and ethPriceUSD.
     * @param {number} blockNumber - The current block number.
     * @private
     */
    async _findAndExecuteBestOpportunity(marketData, blockNumber) {
        const arbitragePaths = this._buildArbitragePaths();
        if (arbitragePaths.length === 0) return;

        const opportunities = arbitragePaths
            .map(path => this._checkPath(path, marketData))
            .filter(Boolean); // Filter out nulls
        
        const profitableOpportunities = opportunities.filter(p => p.isProfitable);

        if (profitableOpportunities.length > 0) {
            const bestOpportunity = profitableOpportunities.sort((a, b) => b.netProfitUSD - a.netProfitUSD)[0];
            this._logOpportunity(bestOpportunity);
            await this._executeArbitrage(bestOpportunity, marketData.feeData, blockNumber);
        } else {
            console.log("  - 本轮检查未发现有利可图的机会。");
        }
    }

    /**
     * @description Executes the arbitrage transaction via Flashbots.
     * @param {object} opportunity - The details of the profitable opportunity.
     * @param {object} feeData - The current fee data from the provider.
     * @param {number} blockNumber - The current block number.
     * @private
     */
    async _executeArbitrage(opportunity, feeData, blockNumber) {
        this.isExecuting = true;
        let txReceipt = null;
        
        try {
            const { path, loanAmount, minProfit, amountOutFirstTrade } = opportunity;
            const { buyDex, sellDex, loanToken, otherToken } = path;
            
            // 从 amountOutFirstTrade 计算带滑点的最小期望值
            const slippageNumerator = BigInt(Math.floor((1 - this.config.slippageTolerance) * 10000));
            const minAmountOutFirstTrade = (amountOutFirstTrade * slippageNumerator) / 10000n;

            const transaction = {
                to: this.dependencies.arbitrageContract.target,
                data: this.dependencies.arbitrageContract.interface.encodeFunctionData("performArbitrage", [
                    loanToken, 
                    otherToken, 
                    loanAmount, 
                    this.config.dexRouters[buyDex], // 使用 Routers 地址
                    this.config.dexRouters[sellDex], // 使用 Routers 地址
                    minAmountOutFirstTrade, // 包含滑点保护
                    minProfit
                ]),
                gasLimit: (await this._estimatePreciseGas(opportunity)) * 120n / 100n,
                maxFeePerGas: feeData.maxFeePerGas + ethers.parseUnits('1', 'gwei'),
                maxPriorityFeePerGas: feeData.maxPriorityFeePerGas + ethers.parseUnits('1', 'gwei'),
                nonce: await this.dependencies.wallet.getNonce('pending'),
                type: 2,
                chainId: this.network === 'sepolia' ? 11155111 : 1
            };
            
            txReceipt = await this._sendFlashbotsBundle(transaction, blockNumber);

            if (txReceipt?.status === 1) {
                console.log("✅ 套利成功! 重置连续失败计数器。");
                this.consecutiveFailures = 0;
            } else {
                throw new Error(`交易失败或回滚，收据状态: ${txReceipt ? txReceipt.status : '未知'}`);
            }

        } catch(error) {
            this._handleExecutionFailure(error);
        } finally {
            if (txReceipt) {
                await this._logGasCost(txReceipt, feeData);
            }
            this.isExecuting = false;
        }
    }

    /**
     * @description Sends a transaction bundle to Flashbots and handles the outcome.
     * @param {object} transaction - The transaction object to be bundled.
     * @param {number} blockNumber - The current block number.
     * @returns {Promise<ethers.TransactionReceipt | null>} The transaction receipt if successful.
     * @private
     */
    async _sendFlashbotsBundle(transaction, blockNumber) {
        const signedTransaction = await this.dependencies.wallet.signTransaction(transaction);
        const bundle = [{ signedTransaction }];
        const targetBlock = blockNumber + 1;

        console.log(`  - 正在将交易捆绑包提交给 Flashbots，目标区块: ${targetBlock}`);
        const bundleSubmission = await this.dependencies.flashbotsProvider.sendRawBundle(bundle, targetBlock);
        
        if ('error' in bundleSubmission) throw new Error(`Flashbots 提交失败: ${bundleSubmission.error.message}`);
        
        console.log('  - 捆绑包已成功提交至 Flashbots 中继。等待上链...');
        const resolution = await bundleSubmission.wait();

        // 【重构】使用 FlashbotsBundleResolution 提高可读性
        if (resolution === FlashbotsBundleResolution.BundleIncluded) {
            console.log('  - Flashbots 交易已成功上链!');
            const txHash = ethers.keccak256(signedTransaction);
            return this.dependencies.provider.getTransactionReceipt(txHash);
        }
        if (resolution === FlashbotsBundleResolution.BlockPassedWithoutInclusion) {
            console.warn(`  - Flashbots 交易在 ${this.config.txTimeoutBlocks} 个区块内未被打包。`);
            if (this.config.enableFlashbotsFallback) {
                console.log("  - 触发回退策略: 尝试通过公共交易池发送...");
                const fallbackTx = await this.dependencies.wallet.sendTransaction(transaction);
                console.log(`  - 公共交易已发送, TxHash: ${fallbackTx.hash}`);
                return fallbackTx.wait(1);
            }
            throw new Error("Flashbots 交易超时且回退策略已禁用。");
        }
        if (resolution === FlashbotsBundleResolution.AccountNonceTooHigh) {
            throw new Error("捆绑包未被选择，账户Nonce过高。");
        }
        return null;
    }


    // --- 4. Data Loading & Preparation ---

    /**
     * @description Loads all initial data required for the bot to run.
     * @private
     */
    async _loadInitialData() {
        await this._checkPendingTransactions();
        console.log("正在获取代币信息...");
        await this._preloadTokenInformation();
        console.log("正在加载交易对...");
        await this._loadTradingPairs();

        const validPairsCount = Object.keys(this.tokenPairs).length;
        console.log(`  - 已加载 ${validPairsCount} 个有效交易对`);
        if (validPairsCount === 0) {
            console.error("  - 错误: 未找到任何有效的交易对，机器人无法启动。请检查您的代币和DEX配置。");
            process.exit(1);
        }
        await this._estimateBaseGas();
    }

    /**
     * @description Fetches market data (fees and ETH price).
     * @returns {Promise<{feeData: object, ethPriceUSD: number}|null>}
     * @private
     */
    async _getMarketData() {
        const [feeData, ethPriceUSD] = await Promise.all([
            this._safeGetFeeData(),
            this.dependencies.priceFeedManager.getETHPrice()
        ]);

        if (!feeData || !DataValidator.isValidPrice(ethPriceUSD)) {
            console.warn("  - 警告: 无法获取市场数据，跳过本轮扫描");
            return null;
        }
        return { feeData, ethPriceUSD };
    }
    
    /**
     * @description Updates reserves for all tracked pairs and returns the count of valid pairs.
     * @returns {Promise<number>} The number of pairs with valid reserve data.
     * @private
     */
    async _updateAndValidatePairs() {
        const reservesData = await Promise.all(
            Object.values(this.tokenPairs).map(pair => this._safeGetReserves(pair.contract))
        );

        let validPairsCount = 0;
        Object.keys(this.tokenPairs).forEach((key, index) => {
            const reserves = reservesData[index];
            if (DataValidator.isValidBigInt(reserves?.[0]) && DataValidator.isValidBigInt(reserves?.[1])) {
                this.tokenPairs[key].reserves = reserves;
                validPairsCount++;
            } else {
                this.tokenPairs[key].reserves = null;
            }
        });
        return validPairsCount;
    }

    /**
     * @description Preloads information for all tokens in the watchlist.
     * @private
     */
    async _preloadTokenInformation() {
        // 【修复】确保所有代币信息都被获取并等待完成
        const tokenPromises = this.config.watchList.map(async (tokenAddress, i) => {
            try {
                const tokenInfo = await this.dependencies.tokenManager.getTokenInfo(tokenAddress);
                console.log(`  - 代币 ${i + 1}: ${tokenInfo.symbol} (${tokenInfo.name})`);
            } catch (error) {
                console.warn(`  - 代币 ${i + 1} 获取失败: ${error.message}`);
            }
        });
        await Promise.all(tokenPromises);
    }

    /**
     * @description Loads all possible trading pairs from the configured DEXs and watchlist.
     * @private
     */
    async _loadTradingPairs() {
        const pairPromises = [];
        const { watchList, dexFactories } = this.config;
        for (let i = 0; i < watchList.length; i++) {
            for (let j = i + 1; j < watchList.length; j++) {
                for (const dexName in dexFactories) {
                    pairPromises.push(this._loadPair(dexName, watchList[i], watchList[j]));
                }
            }
        }
        await Promise.all(pairPromises);
    }
    
    /**
     * @description Loads a single trading pair from a specific DEX.
     * @param {string} dexName - The name of the DEX.
     * @param {string} tokenA - Address of the first token.
     * @param {string} tokenB - Address of the second token.
     * @private
     */
    async _loadPair(dexName, tokenA, tokenB) {
        const factory = new Contract(this.config.dexFactories[dexName], factoryABI, this.dependencies.provider);
        try {
            const pairAddress = await factory.getPair(tokenA, tokenB);
            if (pairAddress && pairAddress !== ZeroAddress) {
                const pairContract = new Contract(pairAddress, pairABI, this.dependencies.provider);
                const token0 = await pairContract.token0();
                const pairKey = this._getPairKey(dexName, tokenA, tokenB);
                this.tokenPairs[pairKey] = { contract: pairContract, token0, reserves: null };
                
                const [infoA, infoB] = await Promise.all([
                    this.dependencies.tokenManager.getTokenInfo(tokenA),
                    this.dependencies.tokenManager.getTokenInfo(tokenB)
                ]);
                console.log(`  - 已加载: ${dexName} 的 ${infoA.symbol}-${infoB.symbol} 交易对`);
            }
        } catch (error) {
            console.warn(`  - 警告: 加载 ${dexName} 的 ${tokenA}-${tokenB} 交易对失败: ${error.message}`);
        }
    }


    // --- 5. Calculation & Analysis ---

    /**
     * @description Analyzes a potential arbitrage path for profitability.
     * @param {object} path - The arbitrage path to check.
     * @param {object} marketData - Contains feeData and ethPriceUSD.
     * @returns {object|null} An opportunity object if profitable, otherwise null.
     * @private
     */
    _checkPath(path, marketData) {
        const { buyDex, sellDex, loanToken, otherToken } = path;
        const buyPairKey = this._getPairKey(buyDex, loanToken, otherToken);
        const sellPairKey = this._getPairKey(sellDex, loanToken, otherToken);
        
        const buyPair = this.tokenPairs[buyPairKey];
        const sellPair = this.tokenPairs[sellPairKey];

        if (!buyPair?.reserves || !sellPair?.reserves) return null;
        
        try {
            // 1. Unpack data
            const { feeData, ethPriceUSD } = marketData;
            
            // 2. Sort reserves to match the trade direction (loanToken -> otherToken)
            const [reservesBuyLoan, reservesBuyOther] = Utils.sortReserves(buyPair, loanToken, buyPair.reserves);
            const [reservesSellLoan, reservesSellOther] = Utils.sortReserves(sellPair, loanToken, sellPair.reserves);

            // 3. Validate that all reserves are present and non-zero
            if (![reservesBuyLoan, reservesBuyOther, reservesSellLoan, reservesSellOther].every(r => DataValidator.isValidBigInt(r, 1n))) {
                return null;
            }

            // 4. Calculate the optimal loan amount using the improved formula
            const optimalLoanAmount = Utils.calculateOptimalLoanAmount(reservesBuyLoan, reservesBuyOther, reservesSellOther, reservesSellLoan);
            
            // If the optimal amount is too small, it's not worth pursuing.
            if (!DataValidator.isValidBigInt(optimalLoanAmount) || optimalLoanAmount < ethers.parseUnits("0.01", 18)) return null;

            // 5. Simulate the full arbitrage path to find the gross profit
            const amountOutFirstTrade = Utils.getAmountOutLocal(optimalLoanAmount, reservesBuyLoan, reservesBuyOther);
            const finalAmount = Utils.getAmountOutLocal(amountOutFirstTrade, reservesSellOther, reservesSellLoan);
            if (!DataValidator.isValidBigInt(finalAmount)) return null;

            const grossProfit = finalAmount - optimalLoanAmount;
            if (grossProfit <= 0n) return null;
            
            // 6. Calculate net profit in tokens (after flash loan fee)
            // Uniswap V3 has tiered fees, but for V2-style (which this bot targets), it's typically 0.3%
            // Aave flash loans are 0.09%. We will assume a generic 0.09% fee for the loan itself.
            const feeRate = 9n; // 0.09% represented as 9 / 10000
            const flashLoanFee = (optimalLoanAmount * feeRate) / 10000n;
            
            const netProfitTokens = grossProfit - flashLoanFee;
            if (netProfitTokens <= 0n) return null;

            // 7. Convert profit to USD and subtract gas costs
            const gasCostUSD = parseFloat(ethers.formatEther(this.baseGasEstimate * ((feeData.lastBaseFeePerGas || 0n) + (feeData.maxPriorityFeePerGas || 0n))));
            const grossProfitUSD = parseFloat(ethers.formatEther(netProfitTokens)) * ethPriceUSD;
            const netProfitUSD = grossProfitUSD - gasCostUSD;

            // 8. Final profitability check against configured thresholds
            const requiredProfitFromGas = gasCostUSD * this.config.minProfitToGasRatio;
            const isProfitable = netProfitUSD > this.config.minProfitUSD && netProfitUSD > requiredProfitFromGas;

            if (isProfitable) {
                // To set a minimum profit for the contract call, convert the USD threshold back to the loan token.
                const minProfitInLoanToken = ethers.parseUnits((this.config.minProfitUSD / ethPriceUSD).toFixed(18), 18);
                return { 
                    isProfitable: true, 
                    netProfitUSD, 
                    path, 
                    loanAmount: optimalLoanAmount, 
                    minProfit: minProfitInLoanToken,
                    amountOutFirstTrade: amountOutFirstTrade
                };
            }
            return null;
        } catch (error) {
            const tokenInfo = this.dependencies.tokenManager.tokenCache.get(path.loanToken.toLowerCase());
            const symbol = tokenInfo ? tokenInfo.symbol : 'UNKNOWN';
            console.warn(`  - 套利路径检查失败: ${path.buyDex}->${path.sellDex} for ${symbol}. Error: ${error.message}`);
            return null;
        }
    }
    
    /**
     * @description Builds all possible arbitrage paths between configured DEXs.
     * @returns {Array<object>} A list of arbitrage path objects.
     * @private
     */
    _buildArbitragePaths() {
        const paths = [];
        const loanTokenAddress = this.config.watchList[0]; // Assume first token is loan token
        const uniquePairs = {};

        // Group DEXs by token pair
        Object.keys(this.tokenPairs).forEach(pairKey => {
             const [dexName, tokenA, tokenB] = pairKey.split('-');
             const pairIdentifier = `${tokenA}-${tokenB}`;
             if(!uniquePairs[pairIdentifier]) uniquePairs[pairIdentifier] = [];
             uniquePairs[pairIdentifier].push(dexName);
        });

        for(const pairIdentifier in uniquePairs){
            const supportedDEXes = uniquePairs[pairIdentifier];
            if(supportedDEXes.length < 2) continue;

            const [tokenA, tokenB] = pairIdentifier.split('-');
            
            // 【修复】统一使用小写地址进行比较和查找
            const loanTokenAddressLower = loanTokenAddress.toLowerCase();
            if (loanTokenAddressLower !== tokenA && loanTokenAddressLower !== tokenB) continue;
            
            const otherTokenAddress = (loanTokenAddressLower === tokenA) ? tokenB : tokenA;
            const loanTokenInfo = this.dependencies.tokenManager.tokenCache.get(loanTokenAddressLower);
            const otherTokenInfo = this.dependencies.tokenManager.tokenCache.get(otherTokenAddress);

            if (!loanTokenInfo || !otherTokenInfo) continue;

            // Create permutations of DEXs for the path
            for(let i = 0; i < supportedDEXes.length; i++){
                for(let j = 0; j < supportedDEXes.length; j++){
                    if(i === j) continue;
                    paths.push({
                        buyDex: supportedDEXes[i], sellDex: supportedDEXes[j],
                        loanToken: loanTokenAddress, otherToken: otherTokenAddress,
                        token0Symbol: loanTokenInfo.symbol, token1Symbol: otherTokenInfo.symbol
                    });
                }
            }
        }
        return paths;
    }

    /**
     * @description Estimates the base gas cost for a sample transaction.
     * @private
     */
    async _estimateBaseGas() {
        try {
            const samplePaths = this._buildArbitragePaths();
            if (samplePaths.length === 0) {
                console.warn("\n[配置警告] 无法估算 Gas: 未能构建任何套利路径。");
                if (Object.keys(this.config.dexFactories).length < 2) {
                    console.warn("  - 主要原因: 当前网络配置的 DEX 数量少于2个。套利需要至少两个市场。");
                } else {
                    console.warn("  - 原因: 检查 `watchList` 中的代币，确保至少有一个交易对存在于两个或更多的 DEX 上。");
                }
                console.warn("  - 后果: 机器人将使用保守的默认值 (800,000) Gas。在找到有效路径前，它将无法执行交易。");
                this.baseGasEstimate = 800000n;
                return;
            }
            
            const samplePath = samplePaths[0];
            this.baseGasEstimate = await this._estimatePreciseGas(
                {...samplePath, loanAmount: ethers.parseEther("1"), minProfit: ethers.parseEther("0.001"), amountOutFirstTrade: ethers.parseEther("1")}
            );
            console.log(`  - 基础 Gas 估算完成: ${this.baseGasEstimate.toString()}`);
        } catch (error) {
            console.error("关键错误: 在估算 Gas 成本时发生意外错误. 将使用保守的默认值 (800,000) Gas。", error.message);
            this.baseGasEstimate = 800000n;
        }
    }

    /**
     * @description Estimates the precise gas for a specific arbitrage transaction.
     * @param {object} opportunity - The opportunity details.
     * @returns {Promise<bigint>} The estimated gas amount.
     * @private
     */
    async _estimatePreciseGas(opportunity) {
        const { path, loanAmount, minProfit, amountOutFirstTrade } = opportunity;
        const { buyDex, sellDex, loanToken, otherToken } = path;

        // 计算带滑点的最小期望值
        const slippageNumerator = BigInt(Math.floor((1 - this.config.slippageTolerance) * 10000));
        const minAmountOutFirstTrade = (amountOutFirstTrade * slippageNumerator) / 10000n;

        return this.dependencies.arbitrageContract.performArbitrage.estimateGas(
            loanToken, 
            otherToken, 
            loanAmount, 
            this.config.dexRouters[buyDex], 
            this.config.dexRouters[sellDex], 
            minAmountOutFirstTrade,
            minProfit
        );
    }

    // --- 6. Utilities & Helpers ---

    /**
     * @description Handles the logic for execution failures and circuit breakers.
     * @param {Error} error - The error that occurred during execution.
     * @private
     */
    _handleExecutionFailure(error) {
        console.error(`❌ 交易执行失败:`, error.reason || error.message);
        this.consecutiveFailures++;
        console.log(`  - 连续失败次数: ${this.consecutiveFailures}/${this.config.maxConsecutiveFailures}`);
        
        if (this.consecutiveFailures >= this.config.maxConsecutiveFailures) {
            this.isPaused = true;
            const cooldownMinutes = this.config.circuitBreakerCooldownMinutes;
            console.error(`[风控] 已达到最大连续失败次数。机器人将暂停 ${cooldownMinutes} 分钟。`);
            
            if (this.pauseTimeout) clearTimeout(this.pauseTimeout);
            this.pauseTimeout = setTimeout(() => {
                this.isPaused = false;
                this.consecutiveFailures = 0;
                console.log("[风控] 暂停时间结束，机器人恢复运行。");
            }, cooldownMinutes * 60 * 1000);
        }
    }

    /**
     * @description Logs the gas cost of a successful transaction.
     * @param {ethers.TransactionReceipt} txReceipt - The transaction receipt.
     * @param {object} feeData - The fee data used for the transaction.
     * @private
     */
    async _logGasCost(txReceipt, feeData) {
        try {
            const gasUsed = txReceipt.gasUsed;
            const gasPrice = txReceipt.effectiveGasPrice || feeData.lastBaseFeePerGas || ethers.parseUnits('1', 'gwei');
            const gasCost = gasUsed * gasPrice;
            const ethPriceUSD = await this.dependencies.priceFeedManager.getETHPrice();
            const costUSD = parseFloat(ethers.formatEther(gasCost)) * ethPriceUSD;
            this.gasSpentTodayUSD += costUSD;
            console.log(`  - 本次交易 Gas 成本: ${ethers.formatEther(gasCost)} ETH ($${costUSD.toFixed(2)})`);
            console.log(`  - 今日累计 Gas 成本: $${this.gasSpentTodayUSD.toFixed(2)} / $${this.config.dailyGasLimitUSD.toFixed(2)}`);
        } catch (e) {
            console.error("  - Gas成本核算失败:", e.message);
        }
    }

    /**
     * @description Checks and resets the daily gas limit.
     * @private
     */
    _checkDailyLimits() {
        if (Date.now() > this.dailyResetTimestamp) {
            console.log(`[风控] 新的一天开始，重置每日Gas花费上限。`);
            this.gasSpentTodayUSD = 0;
            this.dailyResetTimestamp = Utils.getNextUTCDay();
        }
        if (this.gasSpentTodayUSD > this.config.dailyGasLimitUSD) {
            if (!this.isPaused) console.log(`[风控] 已达到每日Gas花费上限 ($${this.config.dailyGasLimitUSD.toFixed(2)})，今日暂停交易。`);
            this.isPaused = true;
        }
    }
    
    /**
     * @description Checks for pending transactions from the bot's wallet.
     * @private
     */
    async _checkPendingTransactions() {
        const nonce = await this.dependencies.wallet.getNonce();
        const pendingNonce = await this.dependencies.wallet.getNonce('pending');
        if (pendingNonce > nonce) {
            console.warn(`[启动检查] 警告: 检测到 ${pendingNonce - nonce} 笔来自您钱包的等待中交易。这可能导致 nonce 冲突。`);
        }
    }

    /**
     * @description Logs a banner with bot information on startup.
     * @private
     */
    async _logBanner() {
        console.log("=================================================");
        console.log("=====      工业级套利机器人正在启动...      =====");
        console.log("=================================================");
        console.log(` - 网络: ${this.network}`);
        console.log(` - 钱包地址: ${this.dependencies.wallet.address}`);
        console.log(` - 监控 ${Object.keys(this.config.dexFactories).length} 个 DEX, ${this.config.watchList.length} 个代币.`);
    }

    /**
     * @description Logs the details of a found opportunity.
     * @param {object} opportunity - The opportunity object.
     * @private
     */
    _logOpportunity(opportunity) {
        console.log("\n✅ 发现最佳盈利机会!");
        console.log(`  - 路径: ${opportunity.path.buyDex}(买入) -> ${opportunity.path.sellDex}(卖出)`);
        console.log(`  - 交易对: ${opportunity.path.token0Symbol}/${opportunity.path.token1Symbol}`);
        console.log(`  - 动态闪电贷金额: ${ethers.formatEther(opportunity.loanAmount)} WETH`);
        console.log(`  - 预估净利润: $${opportunity.netProfitUSD.toFixed(2)}`);
    }

    /**
     * @description Generates a standardized key for a token pair.
     * @param {string} dexName 
     * @param {string} tokenA 
     * @param {string} tokenB 
     * @returns {string} The standardized pair key.
     * @private
     */
    _getPairKey(dexName, tokenA, tokenB) {
        const addrA = tokenA.toLowerCase();
        const addrB = tokenB.toLowerCase();
        const [sortedA, sortedB] = addrA < addrB ? [addrA, addrB] : [addrB, addrA];
        return `${dexName}-${sortedA}-${sortedB}`;
    }

    /**
     * @description Safely gets fee data from the provider.
     * @returns {Promise<object|null>}
     * @private
     */
    async _safeGetFeeData() {
        try {
            const feeData = await this.dependencies.provider.getFeeData();
            if (!feeData) return null;
            if (!DataValidator.isValidBigInt(feeData.lastBaseFeePerGas, 0n)) feeData.lastBaseFeePerGas = ethers.parseUnits('1', 'gwei');
            if (!DataValidator.isValidBigInt(feeData.maxPriorityFeePerGas, 0n)) feeData.maxPriorityFeePerGas = ethers.parseUnits('1', 'gwei');
            if (!DataValidator.isValidBigInt(feeData.maxFeePerGas, 0n)) feeData.maxFeePerGas = feeData.lastBaseFeePerGas + feeData.maxPriorityFeePerGas;
            return feeData;
        } catch (error) {
            console.warn(`获取费用数据失败: ${error.message}`);
            return null;
        }
    }

    /**
     * @description Safely gets reserves from a pair contract.
     * @param {ethers.Contract} pairContract 
     * @returns {Promise<Array<bigint>|null>}
     * @private
     */
    async _safeGetReserves(pairContract) {
        try {
            const reserves = await pairContract.getReserves();
            return reserves?.length >= 2 ? reserves : null;
        } catch {
            return null;
        }
    }

    /**
     * @description Public method to start the bot.
     */
    async start() {
        if (!this._validateStartupConfig()) return;
        
        process.on('SIGINT', () => {
            console.log("\n正在关闭机器人...");
            if (this.dependencies.provider) this.dependencies.provider.removeAllListeners();
            if (this.heartbeatInterval) clearInterval(this.heartbeatInterval);
            process.exit(0);
        });

        await this._connect(true);
    }
}

/**
 * @description Main execution function.
 */
async function main() {
    try {
        const bot = new ArbitrageBot();
        await bot.start();
    } catch (error) {
        console.error("机器人启动时发生致命错误:", error);
        process.exit(1);
    }
}

// 只在直接运行此文件时启动机器人
if (require.main === module) {
    main();
}

// 导出核心类以便其他脚本可以重用它们
module.exports = { ArbitrageBot, Utils, PriceFeedManager, TokenManager };