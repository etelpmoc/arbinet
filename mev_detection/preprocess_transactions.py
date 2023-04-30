from settings import *
import sys
import json
import requests
from web3 import Web3
import warnings
from concurrent.futures import ThreadPoolExecutor
warnings.filterwarnings('ignore')
# Connect to Erigon archive node
w3 = Web3(Web3.HTTPProvider(f"""http://localhost:{ERIGON_PORT}"""))

# Open Wrapped Ether json file
with open("abis/ERC20.json") as f:
    json_file   = json.loads(f.read())
    wethAddress = json_file['address']
    wethABI     = json_file['abi']

# Wrapped Ether Contract
wethContract = w3.eth.contract(address = wethAddress, abi = wethABI)
                                 

def get_internal_transfer(tx) -> list:
    r = session.post(f"http://localhost:{ERIGON_PORT}/",\
                      json =  {"method":"trace_transaction","params":[tx],"id":1,"jsonrpc":"2.0"},\
                     )
    traces = json.loads(r.text)['result']
    internal_transfer = []
    for trace in traces:
        try:
            if trace['action']['value'] == '0x0':
                continue

            if wethAddress.lower() in [trace['action']['from'], trace['action']['to']]:
                continue
            if trace['action']['from'] == trace['action']['to']:
                continue
        except:
            continue
            
        try:
            internal_transfer.append([trace['action']['from'], trace['action']['to'], int(trace['action']['value'],16), wethAddress])
        except:
            # Contract Creation
            internal_transfer.append([trace['action']['from'], None, int(trace['action']['value'],16), wethAddress])
    return internal_transfer

def get_erc20_transfer(transfer_logs) -> list:
    erc20_transfer = []
    for log in transfer_logs:
        erc20_transfer.append([log['args']['src'].lower(), log['args']['dst'].lower(), log['args']['wad'], log['address']]) 
    return erc20_transfer

def get_total_transfer(tx, receipt):
    if receipt['gasUsed'] < 75000:
        return None

    erc20_transfer_logs         = wethContract.events.Transfer().processReceipt(receipt)

    if len(erc20_transfer_logs) <= 1:
        return None

    erc20_transfer        = get_erc20_transfer(erc20_transfer_logs)
    return erc20_transfer
    internal_transfer     = get_internal_transfer(tx)

    total_transfer        = internal_transfer + erc20_transfer

    return total_transfer

def preprocess_transaction(tx, blockNum):
    receipt = w3.eth.getTransactionReceipt(tx)
    total_transfer = get_total_transfer(tx, receipt)
    if not total_transfer:
        return None
    return (tx, json.dumps(total_transfer), blockNum, receipt['transactionIndex'], receipt['from'], receipt['to'])

def update_tx_pp(start, end, table):
    t1 = time.time()
    with ThreadPoolExecutor(max_workers=2) as executor:
        for blockNum in range(start, end):
            block = w3.eth.getBlock(blockNum)
            transactions = block['transactions']

            rows = list(filter(None, executor.map(lambda tx: preprocess_transaction(tx.hex(), blockNum), transactions)))

            mycursor.executemany(f"""INSERT IGNORE INTO {table}_{str(blockNum)[:2]}00 (tx_hash, total_transfer, block, tx_index, from_address, to_address) VALUES (%s,%s,%s,%s,%s,%s)""", rows)

            if blockNum % 100 == 0 or blockNum == end-1:
                print(blockNum)
                mydb.commit()
                
                print(time.time()-t1)
                t1=time.time()

if __name__ == "__main__":
    table = "preprocessed_tx"
    start = int(sys.argv[1])
    end   = int(sys.argv[2])
    
    # Connect to MySQL server 
    mydb = pymysql.connect(
    host="localhost",
    user=DB_USER,
    password=DB_PASSWORD,
    database="Ethereum")

    mycursor = mydb.cursor()
    try:
        mycursor.execute(f"CREATE DATABASE {DB_NAME}")
    except:
        pass

    try:
        mycursor.execute(f"""CREATE TABLE transactions_preprocessed (
Transaction_Hash varchar(255) NOT NULL,
Total_Transfer json DEFAULT NULL,
Block_Number int NOT NULL,
PRIMARY KEY (Transaction_Hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci""")
    except:
        pass

    update_tx_pp(start,end, table)
