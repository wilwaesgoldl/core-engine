import json
import logging
import sys
import time
from typing import Dict, Any, List, Set, Optional

import requests
from web3 import Web3
from web3.contract import Contract
from web3.types import LogReceipt
from requests.exceptions import RequestException

# --- CONFIGURATION --- #
# In a real application, this would be loaded from a secure configuration file or environment variables.
CONFIG = {
    "source_chain": {
        "name": "Ethereum_Sepolia",
        "rpc_url": "https://rpc.sepolia.org",
        "contract_address": "0x5a185124B835004a4333426765354922129aE957", # Example address
        "event_name": "TokensLocked",
        "start_block": 1000000 # Block to start scanning from if no state is found
    },
    "destination_chain": {
        "name": "Polygon_Mumbai",
        "rpc_url": "https://rpc-mumbai.maticvigil.com",
        "contract_address": "0x8a9C28b8686d128340E7420492F6A3d596a7353A", # Example address
        # Relayer's wallet that will sign and send the 'mint' transaction
        "relayer_wallet": "0xYourRelayerWalletAddress",
        "relayer_private_key": "0x..." # IMPORTANT: Never hardcode private keys in production.
    },
    "api": {
        # Polygon Gas Station for fetching recommended gas prices
        "gas_station_url": "https://gasstation-mumbai.matic.today/v2"
    },
    "run_interval_seconds": 30, # How often to poll for new events
    "block_processing_limit": 100 # Max blocks to process in one go to avoid RPC timeouts
}

# --- CONTRACT ABIs --- #
# A simplified ABI for the source chain bridge contract.
SOURCE_CONTRACT_ABI = json.dumps([
    {
        "anonymous": False, "type": "event", "name": "TokensLocked",
        "inputs": [
            {"name": "user", "type": "address", "indexed": True},
            {"name": "token", "type": "address", "indexed": True},
            {"name": "amount", "type": "uint256", "indexed": False},
            {"name": "destinationChainId", "type": "uint256", "indexed": False},
            {"name": "transactionNonce", "type": "bytes32", "indexed": True}
        ]
    }
])

# A simplified ABI for the destination chain bridge contract.
DEST_CONTRACT_ABI = json.dumps([
    {
        "type": "function", "name": "mint",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "user", "type": "address"},
            {"name": "token", "type": "address"},
            {"name": "amount", "type": "uint256"},
            {"name": "sourceTransactionNonce", "type": "bytes32"}
        ]
    }
])

class ChainConnector:
    """A robust wrapper for web3.py to handle blockchain interactions.

    This class manages the connection to an RPC endpoint, provides helper
    methods for fetching blockchain data, and includes basic retry logic
    for connection establishment.
    """
    def __init__(self, name: str, rpc_url: str, contract_address: str, contract_abi: str):
        self.name = name
        self.rpc_url = rpc_url
        self.web3: Optional[Web3] = None
        self.contract_address = Web3.to_checksum_address(contract_address)
        self.contract_abi = contract_abi
        self.contract: Optional[Contract] = None
        self._connect()

    def _connect(self, max_retries: int = 3, delay: int = 5) -> None:
        """Establishes a connection to the RPC endpoint with retries."""
        for attempt in range(max_retries):
            try:
                self.web3 = Web3(Web3.HTTPProvider(self.rpc_url))
                if self.web3.is_connected():
                    logging.info(f"Successfully connected to {self.name} at {self.rpc_url}")
                    self.contract = self.web3.eth.contract(
                        address=self.contract_address,
                        abi=self.contract_abi
                    )
                    return
                else:
                    raise ConnectionError("Web3 provider not connected.")
            except Exception as e:
                logging.warning(
                    f"Connection to {self.name} failed (attempt {attempt + 1}/{max_retries}): {e}"
                )
                if attempt < max_retries - 1:
                    time.sleep(delay)
        logging.error(f"Could not connect to {self.name} after {max_retries} attempts.")
        raise ConnectionError(f"Failed to connect to {self.name}.")

    def get_latest_block(self) -> int:
        """Fetches the latest block number from the connected chain."""
        if not self.web3:
            raise ConnectionError(f"Not connected to {self.name}.")
        return self.web3.eth.block_number

    def get_events(self, from_block: int, to_block: int, event_name: str) -> List[LogReceipt]:
        """Scans a range of blocks for a specific event."""
        if not self.contract or not hasattr(self.contract.events, event_name):
            logging.error(f"Event '{event_name}' not found in contract ABI for {self.name}.")
            return []
        try:
            event_filter = self.contract.events[event_name].create_filter(
                fromBlock=from_block,
                toBlock=to_block
            )
            return event_filter.get_all_entries()
        except Exception as e:
            logging.error(f"Error fetching events from {self.name}: {e}")
            return []

class RelayerEventHandler:
    """Handles the logic of processing an event and preparing the destination transaction.

    This class encapsulates the business logic of the bridge. It takes an event from the
    source chain, validates it, and constructs the corresponding transaction to be
    executed on the destination chain.
    """
    def __init__(self, dest_connector: ChainConnector, config: Dict[str, Any]):
        self.dest_connector = dest_connector
        self.relayer_wallet = Web3.to_checksum_address(config["destination_chain"]["relayer_wallet"])
        self.gas_station_url = config["api"]["gas_station_url"]
        # In a real relayer, a secure key management system (like HashiCorp Vault)
        # would be used instead of a hardcoded private key.
        self.private_key_placeholder = config["destination_chain"]["relayer_private_key"]

    def _get_recommended_gas_price(self) -> Optional[Dict[str, Any]]:
        """Fetches recommended gas prices from a gas station API."""
        try:
            response = requests.get(self.gas_station_url, timeout=10)
            response.raise_for_status()
            gas_data = response.json()
            # We are interested in the fast tier to ensure timely processing
            return gas_data.get('fast')
        except RequestException as e:
            logging.error(f"Failed to fetch gas prices: {e}")
            return None

    def process_lock_event(self, event: LogReceipt) -> bool:
        """Processes a TokensLocked event and simulates relaying a mint transaction."""
        try:
            args = event['args']
            nonce = event['args']['transactionNonce'].hex()
            logging.info(
                f"Processing TokensLocked event (nonce: {nonce}):\n" 
                f"  User: {args['user']}\n" 
                f"  Token: {args['token']}\n" 
                f"  Amount: {args['amount']}"
            )

            if not self.dest_connector.web3 or not self.dest_connector.contract:
                logging.error("Destination chain not connected, cannot prepare transaction.")
                return False

            # --- Build Transaction for Destination Chain ---
            dest_web3 = self.dest_connector.web3
            dest_contract = self.dest_connector.contract

            # 1. Fetch recommended gas prices
            gas_price_info = self._get_recommended_gas_price()
            if not gas_price_info or 'maxPriorityFeePerGas' not in gas_price_info:
                logging.warning("Could not fetch gas price, proceeding with provider's estimate.")
                # Fallback to web3's estimate if API fails
                gas_params = {"gas": 200000} # Set a reasonable gas limit
            else:
                gas_params = {
                    'gas': 200000,
                    'maxFeePerGas': dest_web3.to_wei(gas_price_info['maxFee'], 'gwei'),
                    'maxPriorityFeePerGas': dest_web3.to_wei(gas_price_info['maxPriorityFee'], 'gwei')
                }

            # 2. Build the 'mint' function call
            txn = dest_contract.functions.mint(
                args['user'],
                args['token'],
                args['amount'],
                args['transactionNonce']
            ).build_transaction({
                'from': self.relayer_wallet,
                'nonce': dest_web3.eth.get_transaction_count(self.relayer_wallet),
                'chainId': dest_web3.eth.chain_id,
                **gas_params
            })

            logging.info(f"Prepared mint transaction for destination chain ({self.dest_connector.name}).")
            logging.debug(f"Transaction details: {txn}")

            # --- Simulation Step ---
            # In a real system, the next steps would be to sign and send the transaction:
            # signed_txn = dest_web3.eth.account.sign_transaction(txn, self.private_key_placeholder)
            # tx_hash = dest_web3.eth.send_raw_transaction(signed_txn.rawTransaction)
            # logging.info(f"Transaction sent to {self.dest_connector.name}, hash: {tx_hash.hex()}")
            print("--- SIMULATION: TRANSACTION WOULD BE SENT ---")
            print(json.dumps(txn, indent=2, default=str))
            print("-------------------------------------------")

            return True
        except Exception as e:
            logging.exception(f"An unexpected error occurred during event processing: {e}")
            return False

class CrossChainBridgeListener:
    """The main orchestration class for the bridge listener.

    It manages the overall lifecycle: configuration, state, connections,
    and the main event polling loop.
    """
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._setup_logging()

        # State management
        # In a production system, this state would be persisted in a database (e.g., Redis, PostgreSQL)
        self.last_processed_block: int = config["source_chain"]["start_block"]
        self.processed_tx_nonces: Set[str] = set()

        try:
            self.source_connector = ChainConnector(
                name=config["source_chain"]["name"],
                rpc_url=config["source_chain"]["rpc_url"],
                contract_address=config["source_chain"]["contract_address"],
                contract_abi=SOURCE_CONTRACT_ABI
            )
            self.dest_connector = ChainConnector(
                name=config["destination_chain"]["name"],
                rpc_url=config["destination_chain"]["rpc_url"],
                contract_address=config["destination_chain"]["contract_address"],
                contract_abi=DEST_CONTRACT_ABI
            )
            self.event_handler = RelayerEventHandler(self.dest_connector, config)
        except ConnectionError as e:
            logging.critical(f"Initialization failed: could not connect to a blockchain. {e}")
            sys.exit(1)

    def _setup_logging(self):
        """Configures a standardized logger for the application."""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - [%(levelname)s] - %(message)s',
            stream=sys.stdout
        )
        logging.info("Logger initialized.")

    def _poll_for_events(self):
        """The core logic for scanning for and processing new events."""
        try:
            latest_block = self.source_connector.get_latest_block()
            # Define the block range to scan in this iteration
            from_block = self.last_processed_block + 1
            to_block = min(latest_block, from_block + self.config["block_processing_limit"])

            if from_block > to_block:
                logging.info(f"No new blocks to process. Current head is {latest_block}.")
                return

            logging.info(f"Scanning for '{self.config['source_chain']['event_name']}' events from block {from_block} to {to_block}...")

            events = self.source_connector.get_events(
                from_block=from_block,
                to_block=to_block,
                event_name=self.config['source_chain']['event_name']
            )

            if not events:
                logging.info("No new events found in this range.")
            else:
                logging.info(f"Found {len(events)} new event(s). Processing...")
                for event in sorted(events, key=lambda e: e['blockNumber']): # Process in order
                    nonce = event['args']['transactionNonce'].hex()
                    if nonce in self.processed_tx_nonces:
                        logging.warning(f"Skipping already processed event with nonce {nonce}.")
                        continue

                    if self.event_handler.process_lock_event(event):
                        self.processed_tx_nonces.add(nonce)

            # Update state for the next run
            self.last_processed_block = to_block

        except Exception as e:
            logging.exception(f"An error occurred in the polling loop: {e}")

    def run(self):
        """Starts the main listener loop."""
        logging.info(f"Starting cross-chain listener for bridge: {self.config['source_chain']['name']} -> {self.config['destination_chain']['name']}")
        while True:
            try:
                self._poll_for_events()
                logging.info(f"Loop finished. Waiting {self.config['run_interval_seconds']} seconds for next run.")
                time.sleep(self.config['run_interval_seconds'])
            except KeyboardInterrupt:
                logging.info("Shutdown signal received. Exiting listener.")
                break
            except Exception as e:
                logging.critical(f"A critical unhandled error occurred in the main loop: {e}")
                time.sleep(60) # Wait longer after a critical failure

if __name__ == '__main__':
    listener = CrossChainBridgeListener(CONFIG)
    listener.run()
