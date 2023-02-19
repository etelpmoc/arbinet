import settings
import json
import requests
import mysql.connector

# Connect to Erigon archive node
w3 = Web3(Web3.HTTPProvider(f"""http://localhost:{PORT_NUM}"""))

# Open Wrapped Ether json file
with open("abis/WETH.json") as f:
    json_file   = json.loads(f.read())
    wethAddress = json_file['address']
    wethABI     = json_file['abi']

# Wrapped Ether Contract
wethContract = w3.eth.contract(address = wethAddress, abi = wethABI)
                                 
def get_internal_transfer(tx) -> list:
    r = requests.post(f"http://localhost:{PORT_NUM}/",\
                      json =  {"method":"trace_transaction","params":[tx],"id":1,"jsonrpc":"2.0"},\
                     )
    traces = json.loads(r.text)['result']
    internal_transfer = []
    for trace in traces:
        try:
            value = int(trace['action']['value'],16)
            if not value:
                continue
            if wethAddress.lower() in [trace['action']['from'], trace['action']['to']]:
                continue
            if trace['action']['from'] == trace['action']['to']:
                continue
        except:
            continue
            
        try:
            internal_transfer.append([trace['action']['from'], trace['action']['to'], value, wethAddress])
        except:
            # Contract Creation
            internal_transfer.append([trace['action']['from'], None, value, wethAddress])
    return internal_transfer

def get_erc20_transfer(transfer_logs) -> list:
    erc20_transfer = []
    for log in transfer_logs:
        erc20_transfer.append([log['args']['src'].lower(), log['args']['dst'].lower(), log['args']['wad'], log['address']]) 
    return erc20_transfer

def update_tx_pp(start,end):
    sql = f"""INSERT IGNORE INTO transactions_preprocessed (Transaction_Hash, Total_Transfer, Block_Number) VALUES (%s,%s,%s)"""
    rows = []
    for blockNum in range(start, end):
        block = w3.eth.getBlock(blockNum)
        transactions = block['transactions']
        print(blockNum)
        for tx in transactions:
            tx = tx.hex()
            receipt               = w3.eth.getTransactionReceipt(tx)
            if receipt['gasUsed'] < 75000:
                continue
            erc20_transfer_logs         = wethContract.events.Transfer().processReceipt(receipt)
            
            if not erc20_transfer_logs:
                continue
            erc20_transfer        = get_erc20_transfer(erc20_transfer_logs)
            internal_transfer     = get_internal_transfer(tx)

            total_transfer        = internal_transfer + erc20_transfer 
            if len(total_transfer) <= 2 or len(erc20_transfer) <= 1:
                continue
            row = (tx, json.dumps(total_transfer), blockNum)
            rows.append(row)

        if blockNum % 100 == 99:
            mycursor.executemany(sql,rows)
            mydb.commit()
            rows = []

if __name__ == "__main__":
    table = "transactions_preprocessed"
    start = int(sys.argv[1])
    end   = int(sys.argv[2])
    
    # Connect to MySQL server 
    mydb = mysql.connector.connect(
      host=DB_HOST,
      user=DB_USER,
      password=DB_PASSWORD,
      database = DB_NAME
    )
    mycursor = mydb.cursor()
    update_tx_pp(start,end)

