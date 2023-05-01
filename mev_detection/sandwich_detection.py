import sys
import pandas as pd 
from preprocess_transactions import * 

def common(a, b):
    a_set = set(a)
    b_set = set(b)
    return a_set & b_set

def calc_profit(total_transfer, largest_dict, to_addr):
    profits = {}
    for transfer in total_transfer:
        if transfer[3] not in largest_dict.keys():
            largest_dict[transfer[3]] = transfer[2]
        else:
            if transfer[2] > largest_dict[transfer[3]]:
                largest_dict[transfer[3]] = transfer[2]

        if transfer[0] == to_addr:
            try:
                profits[transfer[3]] -= transfer[2]
            except:
                profits[transfer[3]] =- transfer[2]
        elif transfer[1] == to_addr:
            try:
                profits[transfer[3]] += transfer[2]
            except:
                profits[transfer[3]] =  transfer[2]
        else:
            try:
                profits[transfer[3]] += 0
            except:
                profits[transfer[3]] =  0
    return profits, largest_dict

def judge_sandwich(profits1, profits2, total_profit, largest_dict):
    is_sandwich = True
    if len(profits1) <= 1 or len(profits2) <= 1:
        is_sandwich = False
    if not any(val < 0 for val in list(profits1.values())):
        is_sandwich = False
    if not any(val != 0 for val in list(profits2.values())):
        is_sandwich = False
    if not (all(x in profits1.keys() for x in profits2.keys()) or all(x in profits2.keys() for x in profits1.keys())):
        is_sandwich = False

    for token, profit in total_profit.items():
        if profit < 0:
            if largest_dict[token] > -profit * 10**3:
                continue
            is_sandwich = False
            break

    if not any(val > 0 for val in list(total_profit.values())):
        is_sandwich = False
        
    return is_sandwich

def detect_sandwich_def(tx_data):
    to_list = tx_data['to_address'].values.tolist() 
    
    sandwich_list = []
    for idx,(_,tx) in enumerate(tx_data.iterrows()):
        mev_address = tx.to_address
        if mev_address in to_list[idx+2:]:
            if mev_address == to_list[idx+1]:
                continue
                
            tx2_index = to_list[idx+2:].index(mev_address)+idx+2
            tx2 = tx_data.iloc[tx2_index]
            
            total_transfer1 = tx.total_transfer
            total_transfer2 = tx2.total_transfer
            profits1, profits2 = {}, {}
            largest_dict = {}
            
            c_in, c_out = 0, 0
            
            for transfer in total_transfer1:
                if transfer[3] not in largest_dict.keys():
                    largest_dict[transfer[3]] = transfer[2]
                else:
                    if transfer[2] > largest_dict[transfer[3]]:
                        largest_dict[transfer[3]] = transfer[2]
                if transfer[0] == mev_address.lower():
                    c_out += 1
                    try:
                        profits1[transfer[3]] -= transfer[2]
                    except:
                        profits1[transfer[3]] =- transfer[2]
                elif transfer[1] == mev_address.lower():
                    c_in += 1
                    try:
                        profits1[transfer[3]] += transfer[2]
                    except:
                        profits1[transfer[3]] =  transfer[2]
                else:
                    try:
                        profits1[transfer[3]] += 0
                    except:
                        profits1[transfer[3]] =  0
            
            if c_in + c_out <= 1:
                continue
                
            for transfer in total_transfer2:
                if transfer[0] == mev_address.lower():
                    try:
                        profits2[transfer[3]] -= transfer[2]
                    except:
                        profits2[transfer[3]] =- transfer[2]
                elif transfer[1] == mev_address.lower():
                    try:
                        profits2[transfer[3]] += transfer[2]
                    except:
                        profits2[transfer[3]] =  transfer[2]
                    
                else:
                    try:
                        profits2[transfer[3]] += 0
                    except:
                        profits2[transfer[3]] =  0
            
            total_profit = {k: profits1.get(k, 0) + profits2.get(k, 0) for k in profits1.keys()}

            is_sandwich = True

            if len(profits1) <= 1 or len(profits2) <= 1:
                is_sandwich = False

            if not any(val < -largest_dict[token]/10**3 for token,val in profits1.items()):
                is_sandwich = False

            if not any(val != 0 for val in list(profits2.values())):
                is_sandwich = False

            if not (all(x in profits1.keys() for x in profits2.keys()) or all(x in profits2.keys() for x in profits1.keys())):
                is_sandwich = False

            # total_profit > 0
            for token, profit in total_profit.items():
                if profit < 0:
                    if largest_dict[token] > -profit * 10**3:
                        continue
                    is_sandwich = False
                    break

            if not any(val > largest_dict[token]/10**5 for token,val in total_profit.items()):
                is_sandwich = False

            if is_sandwich:
                sandwich_list.append((tx.block,tx.tx_hash,1))
                sandwich_list.append((tx.block,tx2.tx_hash,2))
            
    return sandwich_list

def detect_sandwich(block):
    transactions = [tx.hex() for tx in w3.eth.getBlock(block)['transactions']]
    tx_data = []
    for tx in transactions:
        receipt = w3.eth.getTransactionReceipt(tx)
        total_transfer = get_total_transfer(tx,receipt)
        if total_transfer:
            tx_data.append((block,tx, total_transfer, receipt['transactionIndex'], receipt['to']))
    # Create the DataFrame
    column_names = ['block','tx_hash', 'total_transfer', 'tx_index', 'to_address']
    tx_data = pd.DataFrame(tx_data, columns=column_names)

    sandwich_list = detect_sandwich_def(tx_data)
    return sandwich_list

if __name__ == "__main__":
    if len(sys.argv) == 2:
        blockNum = int(sys.argv[1])
        sandwich_list = detect_sandwich(blockNum)

    if len(sys.argv) == 3:
        start = int(sys.argv[1])
        end   = int(sys.argv[2])

        for blockNum in range(start, end):
            print(blockNum)
            sandwich_list = detect_sandwich(blockNum)
            if sandwich_list : print(sandwich_list)
