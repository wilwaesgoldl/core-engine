# Cross-Chain Bridge Event Listener Simulation

This project is a Python-based simulation of a crucial component for a cross-chain bridge: the Event Listener and Relayer. It is designed to monitor events on a source blockchain (e.g., Ethereum) and trigger corresponding actions on a destination blockchain (e.g., Polygon).

## Concept

A cross-chain bridge allows users to transfer assets or data from one blockchain to another. A common mechanism is the "lock-and-mint" model:

1.  **Lock**: A user locks their tokens in a smart contract on the source chain.
2.  **Event Emission**: The source chain contract emits an event (`TokensLocked`) containing details of the deposit.
3.  **Relay**: An off-chain service, the **Event Listener** (or Relayer), detects this event.
4.  **Verification**: The listener verifies the event's authenticity.
5.  **Mint**: The listener submits a transaction to a smart contract on the destination chain, authorizing it to mint an equivalent amount of "wrapped" tokens for the user.

This script simulates the critical off-chain **Event Listener/Relayer** component (steps 3-5). It continuously polls the source chain for `TokensLocked` events and, upon detection, prepares and simulates the submission of a `mint` transaction to the destination chain.

## Code Architecture

The script uses a modular, object-oriented architecture to promote separation of concerns and maintainability.

-   `CrossChainBridgeListener`: The main orchestrator class. It manages the application's lifecycle, state (like the last block processed), and the primary event-polling loop.

-   `ChainConnector`: A robust wrapper around the `web3.py` library. It handles all direct interactions with a blockchain, such as establishing a connection to an RPC node, fetching the latest block number, and querying for smart contract events. It includes basic connection retry logic.

-   `RelayerEventHandler`: This class contains the core business logic. When the `CrossChainBridgeListener` finds a relevant event, it passes the event to this handler. The handler is responsible for parsing the event data, fetching external information (like gas prices via the `requests` library), constructing the corresponding `mint` transaction for the destination chain, and (in this simulation) printing it.

-   **Configuration (`CONFIG` dict)**: A centralized dictionary holds all necessary parameters, such as RPC URLs, contract addresses, and API endpoints. In a production environment, this would be managed through environment variables or a secure configuration service.

-   **State Management**: The simulation uses an in-memory set (`processed_tx_nonces`) and a variable (`last_processed_block`) to keep track of its progress. This prevents processing the same event twice and ensures the listener can resume scanning from where it left off. A production system would use a persistent database like Redis or PostgreSQL for this state.

## How it Works

The listener operates in a continuous loop, performing the following steps:

1.  **Initialization**: The `CrossChainBridgeListener` is instantiated. It sets up logging, initializes `ChainConnector` instances for both the source and destination chains, and prepares the `RelayerEventHandler`.

2.  **Get Block Range**: In each loop iteration, the listener fetches the latest block number from the source chain. It then defines a block range to scan, starting from `last_processed_block + 1` up to the current head (or a configured limit to avoid overwhelming the RPC node).

3.  **Event Query**: It uses the `source_connector` to query the defined block range for any `TokensLocked` events from the source bridge contract.

4.  **Event Processing**:
    - If events are found, it iterates through them.
    - For each event, it checks a unique nonce from the event data against its internal set of `processed_tx_nonces` to prevent duplicate processing.
    - If the event is new, it is passed to the `RelayerEventHandler`.

5.  **Transaction Preparation (Simulation)**:
    - The `RelayerEventHandler` parses the event details (`user`, `token`, `amount`).
    - It makes an HTTP request to a gas station API (e.g., Polygon Gas Station) to fetch recommended EIP-1559 gas fees (`maxFeePerGas`, `maxPriorityFeePerGas`).
    - It builds the raw `mint` transaction for the destination chain's contract, including all necessary parameters like the nonce, gas fees, and function arguments.
    - **Simulation**: Instead of signing and sending the transaction (which would require a funded private key), the script prints the fully formed transaction object to the console.

6.  **State Update**: After scanning a block range, the listener updates its `last_processed_block` state. This ensures the next loop iteration resumes from the correct position.

7.  **Wait**: The listener then pauses for a configured interval (`run_interval_seconds`) before starting the loop again.

## Usage

To run the simulation, follow these steps:

1.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Configure the script:**
    Open `script.py` and modify the `CONFIG` dictionary with your desired RPC endpoints, contract addresses, contract ABIs, and relayer wallet address.

    ```python
    # Example configuration in script.py
    CONFIG = {
        "source_chain": {
            "name": "Ethereum_Sepolia",
            "rpc_url": "https://rpc.sepolia.org",
            "contract_address": "0x...",      # Your source bridge contract address
            "contract_abi": [...]             # The ABI JSON for the source contract
        },
        "destination_chain": {
            "name": "Polygon_Mumbai",
            "rpc_url": "https://rpc-mumbai.maticvigil.com",
            "contract_address": "0x...",      # Your destination bridge contract address
            "contract_abi": [...],            # The ABI JSON for the destination contract
            "relayer_wallet": "0xYourRelayerWalletAddress" # Address that will send the mint tx
        },
        # ... other config options
    }
    ```

3.  **Run the listener:**
    ```bash
    python script.py
    ```

### Sample Output

The console will show detailed logs of the listener's activity, similar to the following:

```
2023-10-27 10:30:00,123 - [INFO] - Logger initialized.
2023-10-27 10:30:02,456 - [INFO] - Successfully connected to Ethereum_Sepolia at https://rpc.sepolia.org
2023-10-27 10:30:04,789 - [INFO] - Successfully connected to Polygon_Mumbai at https://rpc-mumbai.maticvigil.com
2023-10-27 10:30:05,001 - [INFO] - Starting cross-chain listener for bridge: Ethereum_Sepolia -> Polygon_Mumbai
2023-10-27 10:30:05,512 - [INFO] - Scanning for 'TokensLocked' events from block 1000001 to 1000101...
2023-10-27 10:30:08,999 - [INFO] - Found 1 new event(s). Processing...
2023-10-27 10:30:09,015 - [INFO] - Processing TokensLocked event (nonce: 0x...a1b2c3):
  User: 0xAbc...123
  Token: 0xDef...456
  Amount: 1000000000000000000
2023-10-27 10:30:10,321 - [INFO] - Prepared mint transaction for destination chain (Polygon_Mumbai).
--- SIMULATION: TRANSACTION WOULD BE SENT ---
{
  "from": "0xYourRelayerWalletAddress",
  "nonce": 42,
  "chainId": 80001,
  "maxFeePerGas": 35000000000,
  "maxPriorityFeePerGas": 30000000000,
  "gas": 200000,
  "to": "0x...",
  "data": "0x... (encoded mint function call)"
}
-------------------------------------------
2023-10-27 10:30:10,325 - [INFO] - Loop finished. Waiting 30 seconds for next run.
```