const { ethers } = require("hardhat");
require("dotenv").config();

async function main() {
  console.log("Starting deployment...");

  // --- 合约地址配置 ---
  const addressSets = {
    mainnet: {
      addressesProvider: "0xB53C1a33016B2DC2fF3653530bfF1848a515c8c5", // Aave V2
      uniswapRouter: "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",     // Uniswap V2
      sushiRouter: "0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F",       // SushiSwap
      oneInchRouter: "0x1111111254EEB25477B68fb85Ed929f73A960582"      // 1inch v5
    },
    sepolia: {
      addressesProvider: "0x012bac54348c0e635dcac9d5fb99f06f24136c9a", // Aave V3 on Sepolia
      uniswapRouter: "0x8898c4925917033a2415d867422995b248d3957a",     // Uniswap V2 Router on Sepolia
      sushiRouter: "0x1b02da8cb0d097eb8d57a175b88c7d8b47997506",       // SushiSwap Router on Sepolia
      oneInchRouter: "0x1111111254eeb25477b68fb85ed929f73a960582"      // 1inch v5 Router on Sepolia
    }
  };

  const networkName = process.env.NETWORK || 'mainnet';
  console.log(`Preparing to deploy on ${networkName} network...`);

  const deployAddresses = addressSets[networkName];
  if (!deployAddresses) {
    console.error(`Address configuration for network "${networkName}" not found.`);
    process.exit(1);
  }

  console.log("Fetching contract factory for FlashLoanArbitrage...");
  const FlashLoanArbitrage = await ethers.getContractFactory("FlashLoanArbitrage");
  
  console.log("Deploying contract with the following addresses:");
  console.log(deployAddresses);
  
  const arbitrageContract = await FlashLoanArbitrage.deploy(
    deployAddresses.addressesProvider,
    deployAddresses.uniswapRouter,
    deployAddresses.sushiRouter,
    deployAddresses.oneInchRouter
  );

  await arbitrageContract.deployed();

  console.log("Contract deployed successfully!");
  console.log(`Network: ${networkName}`);
  console.log("Contract Address:", arbitrageContract.address);
  console.log("\n-------------------------------------------------");
  console.log("Next steps:");
  console.log("1. Copy the contract address above.");
  console.log(`2. Paste it into the 'contractAddress' variable for the '${networkName}' network in 'scripts/bot.js'.`);
  console.log("3. Run 'node scripts/bot.js' to start the bot (make sure NETWORK in .env is set).");
  console.log("-------------------------------------------------");
}

main()
  .then(() => process.exit(0))
  .catch(error => {
    console.error("Deployment failed:", error);
    process.exit(1);
  }); 