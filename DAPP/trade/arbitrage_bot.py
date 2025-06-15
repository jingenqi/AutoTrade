import os
import time
import json
from decimal import Decimal, getcontext
from web3 import Web3
from dotenv import load_dotenv

# --- 初始设置 ---
# 设置Decimal精度
getcontext().prec = 50
# 加载 .env 文件中的环境变量
load_dotenv()


# --- 配置加载 ---
# 从环境变量中获取配置，增强安全性
RPC_URL = os.getenv("RPC_URL")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
FLASH_LOAN_CONTRACT_ADDRESS = os.getenv("FLASH_LOAN_CONTRACT_ADDRESS")

if not all([RPC_URL, PRIVATE_KEY, FLASH_LOAN_CONTRACT_ADDRESS]):
    raise ValueError("请确保 .env 文件中已配置 RPC_URL, PRIVATE_KEY, 和 FLASH_LOAN_CONTRACT_ADDRESS")

# --- 全局常量 ---
# 主要代币和DEX路由器地址 (以太坊主网)
WETH_ADDRESS = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
DAI_ADDRESS = "0x6B175474E89094C44Da98b954EedeAC495271d0F"
UNISWAP_ROUTER_ADDRESS = "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"
SUSHISWAP_ROUTER_ADDRESS = "0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F"
UNISWAP_FACTORY_ADDRESS = "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f"
SUSHISWAP_FACTORY_ADDRESS = "0xC0AEe478e3658e2610c5F7A4A2E1777cE9e4f2Ac"
CHAINLINK_ETH_USD_FEED = "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419"

# 交易参数
PROFIT_THRESHOLD_USD = Decimal("1.0")  # 最小利润阈值(1美元)
SLIPPAGE_TOLERANCE = Decimal("0.005") # 0.5% 滑点保护
GAS_LIMIT_ESTIMATE = 600000            # FlashLoan合约执行的Gas上限估算
DEX_FEE = Decimal("0.997")             # DEX交易手续费 (1 - 0.3%)

# --- 合约 ABI 定义 ---
# 根据分析报告建议，使用最小化ABI，仅包含必要函数
ERC20_ABI = json.dumps([{"constant":True,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"payable":False,"stateMutability":"view","type":"function"}])
UNISWAP_V2_FACTORY_ABI = json.dumps([{"constant": True, "inputs": [{"name": "tokenA", "type": "address"}, {"name": "tokenB", "type": "address"}], "name": "getPair", "outputs": [{"name": "pair", "type": "address"}], "payable": False, "stateMutability": "view", "type": "function"}])
UNISWAP_V2_PAIR_ABI = json.dumps([{"constant": True, "inputs": [], "name": "getReserves", "outputs": [{"name": "_reserve0", "type": "uint112"}, {"name": "_reserve1", "type": "uint112"}, {"name": "_blockTimestampLast", "type": "uint32"}], "payable": False, "stateMutability": "view", "type": "function"}, {"constant": True, "inputs": [], "name": "token0", "outputs": [{"name": "", "type": "address"}], "payable": False, "stateMutability": "view", "type": "function"}])
CHAINLINK_FEED_ABI = json.dumps([{"inputs":[],"name":"latestRoundData","outputs":[{"internalType":"uint80","name":"roundId","type":"uint80"},{"internalType":"int256","name":"answer","type":"int256"},{"internalType":"uint256","name":"startedAt","type":"uint256"},{"internalType":"uint256","name":"updatedAt","type":"uint256"},{"internalType":"uint80","name":"answeredInRound","type":"uint80"}],"stateMutability":"view","type":"function"}, {"inputs":[],"name":"decimals","outputs":[{"internalType":"uint8","name":"","type":"uint8"}],"stateMutability":"view","type":"function"}])
FLASH_LOAN_ABI = json.dumps([{"inputs":[{"internalType":"address","name":"_loanToken","type":"address"},{"internalType":"address","name":"_otherToken","type":"address"},{"internalType":"uint256","name":"_loanAmount","type":"uint256"},{"internalType":"address","name":"_buyRouter","type":"address"},{"internalType":"address","name":"_sellRouter","type":"address"},{"internalType":"uint256","name":"_minAmountOutFirstTrade","type":"uint256"},{"internalType":"uint256","name":"_minProfit","type":"uint256"}],"name":"performArbitrage","outputs":[],"stateMutability":"nonpayable","type":"function"}])

class ArbitrageBot:
    """
    一个生产级的套利机器人，遵循《套利机器人漏洞深度分析报告》中的设计原则。
    """
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(RPC_URL))
        self.account = self.w3.eth.account.from_key(PRIVATE_KEY)
        print(f"机器人已启动，使用地址: {self.account.address}")

        self.flash_loan_contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(FLASH_LOAN_CONTRACT_ADDRESS),
            abi=FLASH_LOAN_ABI
        )
        self.uniswap_factory = self.w3.eth.contract(address=Web3.to_checksum_address(UNISWAP_FACTORY_ADDRESS), abi=UNISWAP_V2_FACTORY_ABI)
        self.sushiswap_factory = self.w3.eth.contract(address=Web3.to_checksum_address(SUSHISWAP_FACTORY_ADDRESS), abi=UNISWAP_V2_FACTORY_ABI)
        self._pair_cache = {}
        self._decimals_cache = {}

    def get_token_decimals(self, token_address):
        """获取并缓存代币的精度"""
        token_address = Web3.to_checksum_address(token_address)
        if token_address not in self._decimals_cache:
            token_contract = self.w3.eth.contract(address=token_address, abi=ERC20_ABI)
            self._decimals_cache[token_address] = token_contract.functions.decimals().call()
        return self._decimals_cache[token_address]

    def to_decimal(self, amount, token_address):
        """将代币的wei单位转换为Decimal对象"""
        decimals = self.get_token_decimals(token_address)
        return Decimal(amount) / (10**decimals)

    def to_wei(self, amount, token_address):
        """将Decimal对象转换为代币的wei单位"""
        decimals = self.get_token_decimals(token_address)
        return int(amount * (10**decimals))

    # --- 数据采集层 ---
    def get_eth_price_usd(self):
        """从Chainlink预言机获取ETH的美元价格，实现报告中的资产价格预言机模块"""
        feed = self.w3.eth.contract(address=Web3.to_checksum_address(CHAINLINK_ETH_USD_FEED), abi=CHAINLINK_FEED_ABI)
        latest_data = feed.functions.latestRoundData().call()
        decimals = feed.functions.decimals().call()
        price = Decimal(latest_data[1]) / (10**decimals)
        print(f"获取到实时 ETH/USD 价格: ${price:,.2f}")
        return price

    def get_reserves(self, factory, token_a, token_b):
        """获取并缓存指定DEX上交易对的储备金，实现报告中的链上数据模块"""
        token_a = Web3.to_checksum_address(token_a)
        token_b = Web3.to_checksum_address(token_b)
        
        pair_key = (factory.address, token_a, token_b)
        if pair_key not in self._pair_cache:
            pair_address = factory.functions.getPair(token_a, token_b).call()
            if pair_address == '0x' + '0' * 40:
                return None, None, None
            self._pair_cache[pair_key] = Web3.to_checksum_address(pair_address)
        
        pair_address = self._pair_cache[pair_key]
        pair_contract = self.w3.eth.contract(address=pair_address, abi=UNISWAP_V2_PAIR_ABI)
        
        reserves = pair_contract.functions.getReserves().call()
        pair_token_0 = pair_contract.functions.token0().call()

        if token_a == pair_token_0:
            return reserves[0], reserves[1], pair_address
        else:
            return reserves[1], reserves[0], pair_address
            
    def get_gas_fees(self):
        """获取EIP-1559兼容的Gas费用，实现报告中的Gas预言机模块"""
        latest_block = self.w3.eth.get_block('latest')
        base_fee_per_gas = latest_block['baseFeePerGas']
        # 为确保交易快速被打包，我们可以设置一个合理的优先费
        max_priority_fee_per_gas = self.w3.eth.max_priority_fee
        # 总的 max fee per gas = base fee + priority fee
        max_fee_per_gas = base_fee_per_gas + max_priority_fee_per_gas
        return {"maxFeePerGas": max_fee_per_gas, "maxPriorityFeePerGas": max_priority_fee_per_gas}

    # --- 核心引擎 ---
    def calculate_optimal_amount_in(self, reserve_in_buy, reserve_out_buy, reserve_in_sell, reserve_out_sell):
        """
        计算最优交易输入量。
        此公式基于在一次交易后，使第一个DEX的价格与第二个DEX的当前价格相等的原理推导得出。
        这是报告中"最优交易量"和"优化问题"的直接实现。
        reserve_in_buy, reserve_out_buy: 用于购买的DEX的储备金 (流动性池中'in'和'out'代币的数量)
        reserve_in_sell, reserve_out_sell: 用于出售的DEX的储备金 (流动性池中'in'和'out'代币的数量)
        """
        # 使用Decimal进行高精度计算
        term1 = Decimal(reserve_in_buy) * Decimal(reserve_out_sell) * DEX_FEE
        term2 = Decimal(reserve_in_sell) * Decimal(reserve_out_buy)
        
        if term1 <= term2:
            return 0

        numerator = Decimal.sqrt(term1 * term2) - term2
        denominator = Decimal(reserve_out_buy) * DEX_FEE
        
        if denominator == 0:
            return 0
            
        return self.to_wei(numerator / denominator, WETH_ADDRESS) # Assume input is WETH for now

    def analyze_and_execute(self, loan_token, other_token):
        """
        完整的套利机会分析与执行流程。
        这是报告中 "3.2.1 套利扫描循环 (算法)" 的实现。
        """
        print(f"\n----- 正在扫描 {loan_token[-6:]}.../{other_token[-6:]}... 交易对 -----")
        
        # 1. 并发获取数据 (Python的串行执行在这里用函数调用顺序模拟)
        res_uni_a, res_uni_b, _ = self.get_reserves(self.uniswap_factory, loan_token, other_token)
        res_sushi_a, res_sushi_b, _ = self.get_reserves(self.sushiswap_factory, loan_token, other_token)
        
        # 2. 数据有效性检查
        if not all([res_uni_a, res_uni_b, res_sushi_a, res_sushi_b]):
            print("一个或多个池子不存在，跳过此轮。")
            return

        # 将储备金转换为Decimal，以便进行高精度计算
        res_uni_a_dec = self.to_decimal(res_uni_a, loan_token)
        res_uni_b_dec = self.to_decimal(res_uni_b, other_token)
        res_sushi_a_dec = self.to_decimal(res_sushi_a, loan_token)
        res_sushi_b_dec = self.to_decimal(res_sushi_b, other_token)

        # 价格计算 (other_token per loan_token)
        price_uni = res_uni_b_dec / res_uni_a_dec if res_uni_a_dec > 0 else 0
        price_sushi = res_sushi_b_dec / res_sushi_a_dec if res_sushi_a_dec > 0 else 0
        print(f"Uniswap价格: 1 {loan_token[-6:]}.. = {price_uni:,.4f} {other_token[-6:]}..")
        print(f"SushiSwap价格: 1 {loan_token[-6:]}.. = {price_sushi:,.4f} {other_token[-6:]}..")

        # 3. 检查两个方向的套利机会
        # 方向 1: 在SushiSwap上买入, 在Uniswap上卖出
        if price_uni > price_sushi:
            print("发现潜在机会: SushiSwap -> Uniswap")
            optimal_amount_in = self.calculate_optimal_amount_in(res_sushi_a, res_sushi_b, res_uni_b, res_uni_a)
            if optimal_amount_in > 0:
                self.evaluate_profitability(
                    loan_token, other_token, optimal_amount_in,
                    SUSHISWAP_ROUTER_ADDRESS, UNISWAP_ROUTER_ADDRESS,
                    res_sushi_a, res_sushi_b
                )
        # 方向 2: 在Uniswap上买入, 在SushiSwap上卖出
        elif price_sushi > price_uni:
            print("发现潜在机会: Uniswap -> SushiSwap")
            optimal_amount_in = self.calculate_optimal_amount_in(res_uni_a, res_uni_b, res_sushi_b, res_sushi_a)
            if optimal_amount_in > 0:
                self.evaluate_profitability(
                    loan_token, other_token, optimal_amount_in,
                    UNISWAP_ROUTER_ADDRESS, SUSHISWAP_ROUTER_ADDRESS,
                    res_uni_a, res_uni_b
                )
        else:
            print("无价差，未发现机会。")

    def get_amount_out(self, amount_in, reserve_in, reserve_out):
        """计算给定输入能获得的输出，实现报告中的getAmountOut"""
        amount_in_with_fee = amount_in * 997
        numerator = amount_in_with_fee * reserve_out
        denominator = (reserve_in * 1000) + amount_in_with_fee
        return numerator // denominator if denominator > 0 else 0

    def evaluate_profitability(self, loan_token, other_token, amount_in_wei, buy_router, sell_router, reserves_buy_in, reserves_buy_out):
        """
        评估交易的最终盈利能力，这是报告中"盈利能力检查"的实现。
        """
        print(f"  计算最优输入量: {self.to_decimal(amount_in_wei, loan_token):.6f} {loan_token[-6:]}...")
        
        # 模拟交易第一步 (买入)
        amount_out_min_wei = self.get_amount_out(amount_in_wei, reserves_buy_in, reserves_buy_out)
        
        # 准备数据以调用合约
        loan_amount_wei = int(amount_in_wei)
        
        # 计算滑点保护
        min_amount_out_first_trade_wei = int(Decimal(amount_out_min_wei) * (Decimal(1) - SLIPPAGE_TOLERANCE))
        
        # 计算 Gas 成本 (美元)
        gas_fees = self.get_gas_fees()
        eth_price_usd = self.get_eth_price_usd()
        gas_cost_usd = self.to_decimal(gas_fees['maxFeePerGas'] * GAS_LIMIT_ESTIMATE, WETH_ADDRESS) * eth_price_usd
        print(f"  预估Gas成本: ${gas_cost_usd:,.2f}")
        
        # 获取利润阈值的代币单位
        loan_token_price_usd = eth_price_usd # 假设 loan_token 是 WETH
        profit_threshold_token = PROFIT_THRESHOLD_USD / loan_token_price_usd
        min_profit_wei = self.to_wei(profit_threshold_token, loan_token)

        print(f"  利润阈值 ({PROFIT_THRESHOLD_USD}$): {self.to_decimal(min_profit_wei, loan_token):.6f} {loan_token[-6:]}...")

        # --- 执行层 ---
        print(">>> 准备执行交易 <<<")
        self.execute_trade({
            "loan_token": loan_token,
            "other_token": other_token,
            "loan_amount": loan_amount_wei,
            "buy_router": buy_router,
            "sell_router": sell_router,
            "min_amount_out_first_trade": min_amount_out_first_trade_wei,
            "min_profit": min_profit_wei
        })

    def execute_trade(self, details):
        """构建并发送交易到FlashLoanArbitrage合约"""
        try:
            tx = self.flash_loan_contract.functions.performArbitrage(
                Web3.to_checksum_address(details['loan_token']),
                Web3.to_checksum_address(details['other_token']),
                details['loan_amount'],
                Web3.to_checksum_address(details['buy_router']),
                Web3.to_checksum_address(details['sell_router']),
                details['min_amount_out_first_trade'],
                details['min_profit']
            ).build_transaction({
                'from': self.account.address,
                'nonce': self.w3.eth.get_transaction_count(self.account.address),
                'gas': GAS_LIMIT_ESTIMATE,
                'maxFeePerGas': self.get_gas_fees()['maxFeePerGas'],
                'maxPriorityFeePerGas': self.get_gas_fees()['maxPriorityFeePerGas'],
            })

            signed_tx = self.w3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            print(f"!!! 交易已发送! 哈希: {tx_hash.hex()}")
            print("    等待交易确认...")
            
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt.status == 1:
                print("✅ 交易成功! 套利完成。")
            else:
                print("❌ 交易失败! 合约逻辑可能回滚。检查 Etherscan 获取详情。")

        except Exception as e:
            print(f"交易执行时发生错误: {e}")

    def run(self):
        """机器人主循环"""
        print("套利机器人开始运行。按 Ctrl+C 停止。")
        while True:
            try:
                # 目前只监控 WETH/DAI 交易对作为示例
                self.analyze_and_execute(WETH_ADDRESS, DAI_ADDRESS)
            except Exception as e:
                print(f"主循环发生错误: {e}")
                
            # 为避免API速率限制和不必要的计算，暂停一段时间
            print("\n----- 扫描结束，休眠15秒 -----")
            time.sleep(15)

if __name__ == "__main__":
    bot = ArbitrageBot()
    bot.run() 