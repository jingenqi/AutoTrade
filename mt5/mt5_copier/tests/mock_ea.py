#!/usr/bin/env python3
# Add project root to sys.path to allow imports from parent directories
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

"""
Mock MQL5 Expert Advisor (Comprehensive Scenario-Based)
-------------------------------------------------------
This definitive version of the mock EA generates complete, stateful, and
realistic trading scenarios covering all primary order types to ensure the
Python controller is robustly tested against all expected events.

It supports iterative runs for stress-testing.

Usage:
    python mock_ea.py
    python mock_ea.py --iterations 3
"""

import zmq
import json
import time
import random
import argparse
from datetime import datetime

# 从新的配置文件中导入所有ZMQ设置
from mt5_copier.python.config.settings import (
    ZMQ_SYNC_URI, ZMQ_BUS_URI, MSG_SYNC_REQUEST, MSG_SYNC_RESPONSE, MSG_HEARTBEAT
)

class MockEventGenerator:
    """Generates sequences of realistic, stateful trade events."""
    def __init__(self):
        self._order_id_counter = random.randint(10000, 20000)
        self._position_id_counter = random.randint(80000, 90000)
        
    def _get_next_order_id(self):
        self._order_id_counter += 1
        return self._order_id_counter

    def _get_next_position_id(self):
        self._position_id_counter += 1
        return self._position_id_counter

    def _create_base_event(self):
        """Creates a base event with common fields."""
        return {
            "symbol": "EURUSD",
            "price": round(1.07812 + random.uniform(-0.001, 0.001), 5),
            "sl": 0.0, "tp": 0.0, "magic": 12345,
            "comment": "Scenario Test",
            "timestamp_msc": int(time.time() * 1000)
        }
    
    # --- Individual Scenario Generators ---

    def _generate_market_buy(self):
        print("    - Generating: Market Buy -> Close")
        order_id = self._get_next_order_id()
        position_id = self._get_next_position_id()
        return [
            {**self._create_base_event(), "event_type": "TRADE_TRANSACTION_DEAL_ADD", "order_id": order_id, "position_id": position_id, "action": "BUY", "volume": 0.1},
            {**self._create_base_event(), "event_type": "TRADE_TRANSACTION_DEAL_ADD", "order_id": self._get_next_order_id(), "position_id": position_id, "action": "SELL", "volume": 0.1}
        ]

    def _generate_market_sell(self):
        print("    - Generating: Market Sell -> Close")
        order_id = self._get_next_order_id()
        position_id = self._get_next_position_id()
        return [
            {**self._create_base_event(), "event_type": "TRADE_TRANSACTION_DEAL_ADD", "order_id": order_id, "position_id": position_id, "action": "SELL", "volume": 0.2},
            {**self._create_base_event(), "event_type": "TRADE_TRANSACTION_DEAL_ADD", "order_id": self._get_next_order_id(), "position_id": position_id, "action": "BUY", "volume": 0.2}
        ]

    def _generate_buy_limit(self):
        print("    - Generating: Buy Limit -> Fill -> Close")
        order_id = self._get_next_order_id()
        position_id = self._get_next_position_id()
        base = self._create_base_event()
        pending_price = round(base["price"] - 0.005, 5)
        return [
            {**base, "event_type": "TRADE_TRANSACTION_ORDER_ADD", "order_id": order_id, "position_id": 0, "action": "BUY_LIMIT", "volume": 0.3, "price": pending_price},
            {**self._create_base_event(), "event_type": "TRADE_TRANSACTION_DEAL_ADD", "order_id": order_id, "position_id": position_id, "action": "BUY", "volume": 0.3},
            {**self._create_base_event(), "event_type": "TRADE_TRANSACTION_DEAL_ADD", "order_id": self._get_next_order_id(), "position_id": position_id, "action": "SELL", "volume": 0.3}
        ]

    def _generate_sell_limit(self):
        print("    - Generating: Sell Limit -> Fill -> Close")
        order_id = self._get_next_order_id()
        position_id = self._get_next_position_id()
        base = self._create_base_event()
        pending_price = round(base["price"] + 0.005, 5)
        return [
            {**base, "event_type": "TRADE_TRANSACTION_ORDER_ADD", "order_id": order_id, "position_id": 0, "action": "SELL_LIMIT", "volume": 0.4, "price": pending_price},
            {**self._create_base_event(), "event_type": "TRADE_TRANSACTION_DEAL_ADD", "order_id": order_id, "position_id": position_id, "action": "SELL", "volume": 0.4},
            {**self._create_base_event(), "event_type": "TRADE_TRANSACTION_DEAL_ADD", "order_id": self._get_next_order_id(), "position_id": position_id, "action": "BUY", "volume": 0.4}
        ]
        
    def _generate_buy_stop(self):
        print("    - Generating: Buy Stop -> Fill -> Close")
        order_id = self._get_next_order_id()
        position_id = self._get_next_position_id()
        base = self._create_base_event()
        pending_price = round(base["price"] + 0.005, 5)
        return [
            {**base, "event_type": "TRADE_TRANSACTION_ORDER_ADD", "order_id": order_id, "position_id": 0, "action": "BUY_STOP", "volume": 0.5, "price": pending_price},
            {**self._create_base_event(), "event_type": "TRADE_TRANSACTION_DEAL_ADD", "order_id": order_id, "position_id": position_id, "action": "BUY", "volume": 0.5},
            {**self._create_base_event(), "event_type": "TRADE_TRANSACTION_DEAL_ADD", "order_id": self._get_next_order_id(), "position_id": position_id, "action": "SELL", "volume": 0.5}
        ]

    def _generate_sell_stop_cancelled(self):
        print("    - Generating: Sell Stop -> Cancel")
        order_id = self._get_next_order_id()
        base = self._create_base_event()
        pending_price = round(base["price"] - 0.005, 5)
        return [
            {**base, "event_type": "TRADE_TRANSACTION_ORDER_ADD", "order_id": order_id, "position_id": 0, "action": "SELL_STOP", "volume": 0.6, "price": pending_price},
            {**base, "event_type": "TRADE_TRANSACTION_ORDER_DELETE", "order_id": order_id, "position_id": 0, "action": "ORDER_DELETE", "volume": 0.6}
        ]

    def generate_all_scenarios(self):
        """Generates a list of all defined event scenarios."""
        scenarios = []
        scenarios.extend(self._generate_market_buy())
        scenarios.extend(self._generate_market_sell())
        scenarios.extend(self._generate_buy_limit())
        scenarios.extend(self._generate_sell_limit())
        scenarios.extend(self._generate_buy_stop())
        scenarios.extend(self._generate_sell_stop_cancelled())
        random.shuffle(scenarios) # Shuffle events to test out-of-order robustness
        return scenarios

def generate_heartbeat():
    """Generates a sample heartbeat dictionary."""
    return { "type": MSG_HEARTBEAT, "timestamp": int(time.time() * 1000), "account": 12345678 }

def run_mock_ea(iterations: int):
    """Main function to run the mock EA."""
    print(f"--- Mock MQL5 EA (Comprehensive Scenarios | Iterations: {iterations}) ---")
    event_generator = MockEventGenerator()
    
    context = zmq.Context()
    req_socket = context.socket(zmq.REQ)
    pub_socket = context.socket(zmq.PUB)
    
    try:
        # 1. Handshake
        print("\n[Step 1] Performing Handshake...")
        req_socket.connect(ZMQ_SYNC_URI)
        req_socket.send_string(MSG_SYNC_REQUEST)
        if not req_socket.poll(5000) or req_socket.recv_string() != MSG_SYNC_RESPONSE:
            print("✗ ERROR: Handshake failed. Aborting.")
            return
        print("✓ Handshake successful!")

        # 2. Start Publishing Events
        print("\n[Step 2] Binding publisher and waiting for subscriber...")
        pub_socket.bind(ZMQ_BUS_URI)
        time.sleep(1)

        for i in range(iterations):
            print(f"\n--- Starting Test Iteration {i+1}/{iterations} ---")
            all_events = event_generator.generate_all_scenarios()
            print(f"Generated {len(all_events)} events for this iteration.")
            time.sleep(1)

            for j, event_dict in enumerate(all_events):
                if j % 4 == 0 and j > 0:
                    print("\n- Sending Heartbeat -")
                    pub_socket.send_string(json.dumps(generate_heartbeat()))
                    time.sleep(1.5)

                message_str = json.dumps(event_dict)
                print(f"\nSending Event {j+1}/{len(all_events)} ({event_dict['event_type']}:{event_dict['action']})")
                print(f"-> {message_str[:120]}...")
                pub_socket.send_string(message_str)
                time.sleep(random.uniform(0.5, 2))
            
            print(f"\n✓ Iteration {i+1} finished.")
            time.sleep(3)

        print("\n✓ All test iterations completed.")

    except Exception as e:
        print(f"\n✗ An unhandled error occurred: {e}")
    finally:
        print("\nCleaning up sockets...")
        req_socket.close()
        pub_socket.close()
        context.term()
        print("Mock EA finished.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a comprehensive, scenario-based Mock MQL5 EA.")
    parser.add_argument("-i", "--iterations", type=int, default=1, help="Number of times to run the full test suite.")
    args = parser.parse_args()
    
    run_mock_ea(args.iterations) 