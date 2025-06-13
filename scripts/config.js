const { getAddress } = require("ethers");

// 【模块】配置类：负责加载和验证所有静态配置
class Config {
    constructor() {
        this.NETWORK = process.env.NETWORK || "mainnet";
        this.config = {};
        this._validateEnv();
        this._load();
    }

    _validateEnv() {
        const privateKey = process.env.PRIVATE_KEY;
        if (!privateKey || !/^(0x)?[0-9a-fA-F]{64}$/.test(privateKey)) {
            console.error("\n[配置错误] .env 文件中的 PRIVATE_KEY 无效或缺失。");
            process.exit(1);
        }
        if (this.NETWORK === 'sepolia' && !process.env.SEPOLIA_HTTPS_URL) {
            console.error("\n[配置错误] .env 文件中缺少 SEPOLIA_HTTPS_URL 配置，Flashbots 无法初始化。\n");
            process.exit(1);
        }
    }

    _load() {
        const ADDRESSES = {
            mainnet: {
                providerUrl: process.env.MAINNET_WSS_URL,
                backupProviderUrl: process.env.MAINNET_WSS_URL_BACKUP,
                contractAddress: "YOUR_MAINNET_CONTRACT_ADDRESS",
                watchList: [
                    getAddress("0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"), // WETH
                    getAddress("0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"), // USDC
                    getAddress("0x6b175474e89094c44da98b954eedeac495271d0f"), // DAI
                ],
                dexFactories: {
                    "UniswapV2": getAddress("0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f"),
                    "SushiSwap": getAddress("0xc0aee478e3658e2610c5f7a4a2e1777ce9e4f2ac")
                },
                ethPriceFeedAddress: getAddress("0x5f4ec3df9cbd43714fe274045f3642155d8407aa"),
            },
            sepolia: {
                providerUrl: process.env.SEPOLIA_WSS_URL,
                rpcUrl: process.env.SEPOLIA_HTTPS_URL,
                backupProviderUrl: process.env.SEPOLIA_WSS_URL_BACKUP,
                contractAddress: "0xe24ae1fd16e7226dd4287d74f097962057cc5f59",
                watchList: [
                    getAddress("0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238"), // USDC
                    getAddress("0x68194a729C2450ad26072b3D33ADaCbcef39D574"), // DAI
                    getAddress("0x7b79995e5f793a07bc00c21412e50eaae098e7f9"), // WETH
                ],
                dexFactories: { "UniswapV2": getAddress("0x7e0987e5b3a30e3f2828572bb659a548460a3003"), },
                ethPriceFeedAddress: getAddress("0x694aa1769357215de4fac081bf1f309adc325306"),
                fallbackMode: {
                    enableSimulation: true,
                    simulatedPairs: [{ token0: "USDC", token1: "DAI", dex: "UniswapV2", reserves: [ethers.parseUnits("1000000", 6), ethers.parseUnits("1000000")] }]
                }
            }
        };

        const networkConfig = ADDRESSES[this.NETWORK];
        if (!networkConfig || !networkConfig.providerUrl || !process.env.PRIVATE_KEY || networkConfig.contractAddress.startsWith("YOUR_")) {
            console.error(`配置错误: 请在 .env 文件中为 ${this.NETWORK} 网络设置 WSS_URL, PRIVATE_KEY 并在脚本中配置 contractAddress`);
            process.exit(1);
        }

        this.config = {
            ...networkConfig,
            network: this.NETWORK,
            privateKey: process.env.PRIVATE_KEY,
            authKey: process.env.FLASHBOTS_AUTH_KEY || process.env.PRIVATE_KEY,
            minProfitUSD: this.NETWORK === 'mainnet' ? 15.0 : 1.0,
            minProfitToGasRatio: this.NETWORK === 'mainnet' ? 0.5 : 0.1,
            maxConsecutiveFailures: 3,
            circuitBreakerCooldownMinutes: this.NETWORK === 'mainnet' ? 60 : 5,
            dailyGasLimitUSD: this.NETWORK === 'mainnet' ? 50.0 : 10.0,
            enableFlashbotsFallback: true,
            txTimeoutBlocks: 3,
        };
    }

    get() { return this.config; }
}

module.exports = { Config }; 