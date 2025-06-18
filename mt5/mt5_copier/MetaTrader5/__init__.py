"""Lightweight stub of the MetaTrader5 package for CI testing.

This stub provides the minimal constants and functions used by the unit
 tests so they can run without installing the real MetaTrader5 package.
"""

# Order types and trade actions
TRADE_ACTION_DEAL = 1
ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1

# Basic API stubs

def initialize(*args, **kwargs):
    """Pretend to initialize a connection. Always succeed."""
    return True

def shutdown():
    """Pretend to shut down the connection."""
    return True

def order_send(request):
    """Pretend to send an order and return a success result."""
    return {'retcode': 0, 'order': 123456}

def last_error():
    return (0, "")

def account_info():
    class Info:
        balance = 10000.0
        login = 0
        server = "TEST"
    return Info()

def symbol_info(symbol):
    class Info:
        volume_min = 0.01
        volume_max = 100.0
        volume_step = 0.01
    return Info()
