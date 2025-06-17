import zmq
import time
import json

# ZMQ Configuration
REP_ENDPOINT = "tcp://localhost:5555"
PUB_ENDPOINT = "tcp://localhost:5556"
TOPIC = b"TRADE_EVENT"

def main():
    """
    Main function to run the ZMQ test client.
    """
    context = zmq.Context()
    
    print("--- MT5 ZMQ Python Test Client ---")

    # --- Step 1: Perform REQ/REP handshake for synchronization ---
    print(f"Connecting to REP socket at {REP_ENDPOINT} for handshake...")
    req_socket = context.socket(zmq.REQ)
    req_socket.connect(REP_ENDPOINT)

    print("Sending 'SYNC' message...")
    req_socket.send_string("SYNC")

    # Wait for the "ACK" reply with a timeout
    poller = zmq.Poller()
    poller.register(req_socket, zmq.POLLIN)
    
    ack_received = False
    socks = dict(poller.poll(150000)) # 5-second timeout
    if req_socket in socks and socks[req_socket] == zmq.POLLIN:
        message = req_socket.recv_string()
        if message == "ACK":
            print("Received 'ACK'. Handshake successful!")
            ack_received = True
        else:
            print(f"Error: Received unexpected message: {message}")
    else:
        print("Error: Handshake timeout. No 'ACK' received from EA.")
        print("Please ensure the TradeCopierMaster EA is running on a chart in MT5.")

    req_socket.close()

    if not ack_received:
        context.term()
        return

    # --- Step 2: Subscribe to the PUB socket for trade events ---
    print(f"\nConnecting to PUB socket at {PUB_ENDPOINT}...")
    sub_socket = context.socket(zmq.SUB)
    sub_socket.connect(PUB_ENDPOINT)
    sub_socket.setsockopt(zmq.SUBSCRIBE, TOPIC)
    
    print(f"Subscribed to topic: '{TOPIC.decode()}'")
    print("Waiting for trade events... (Perform a trade in MT5 to see messages)")
    print("Press Ctrl+C to exit.")

    try:
        while True:
            # Read multipart message
            topic, payload_raw = sub_socket.recv_multipart()
            
            print("\n--- Received Event ---")
            print(f"Topic: {topic.decode()}")
            try:
                # The payload is sent as a JSON string
                payload = json.loads(payload_raw.decode('utf-8'))
                # Pretty print the JSON
                print("Payload:")
                print(json.dumps(payload, indent=2))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                print(f"Error decoding payload: {e}")
                print(f"Raw Payload: {payload_raw}")
            print("----------------------")

    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        sub_socket.close()
        context.term()
        print("ZMQ context terminated.")

if __name__ == "__main__":
    main() 