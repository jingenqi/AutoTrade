const { ethers } = require("hardhat");

async function main() {
  console.log("Starting deployment...");

  // --- 您提供的地址 ---
  const addresses = {
    addressesProvider: "0xB53C1a33016B2DC2fF3653530bfF1848a515c8c5", // Aave V2
    uniswapRouter: "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",     // Uniswap V2
    sushiRouter: "0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F",       // SushiSwap
    oneInchRouter: "0x1111111254EEB25477B68fb85Ed929f73A960582"      // 1inch v5
  };

  console.log("Fetching contract factory for FlashLoanArbitrage...");
  const FlashLoanArbitrage = await ethers.getContractFactory("FlashLoanArbitrage");
  
  console.log("Deploying contract with the following addresses:");
  console.log(addresses);
  
  const arbitrageContract = await FlashLoanArbitrage.deploy(
    addresses.addressesProvider,
    addresses.uniswapRouter,
    addresses.sushiRouter,
    addresses.oneInchRouter
  );

  await arbitrageContract.deployed();

  console.log("Contract deployed successfully!");
  console.log("Contract Address:", arbitrageContract.address);
  console.log("\n-------------------------------------------------");
  console.log("Next steps:");
  console.log("1. Copy the contract address above.");
  console.log("2. Paste it into the 'contractAddress' variable in 'scripts/bot.js'.");
  console.log("3. Run 'node scripts/bot.js' to start the bot.");
  console.log("-------------------------------------------------");
}

main()
  .then(() => process.exit(0))
  .catch(error => {
    console.error("Deployment failed:", error);
    process.exit(1);
  }); 