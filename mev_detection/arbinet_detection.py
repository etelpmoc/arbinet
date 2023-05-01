import torch
from gnn import *
from preprocess_transactions import *

# Connect to Erigon archive node
w3 = Web3(Web3.HTTPProvider(f"""http://localhost:{ERIGON_PORT}"""))

def add_features(total_transfer, tx, from_addr, to_addr, blockNum, builder, target):
    tx_info = w3.eth.getTransaction(tx)

    # Ignore trivial transfer value
    if tx_info['value'] < 10**12 and tx_info['value']>0: 
        for idx, transfer in enumerate(total_transfer):
            if transfer[2] == tx_info['value'] and transfer[0] == tx_info['from'].lower():
                del total_transfer[idx]
                break
    
    nodes_dict, tokens_dict = {}, {}
    edge_start, edge_end = [], []
    
    zero_amount = []
    for idx,transfer in enumerate(total_transfer):
        if transfer[3] not in tokens_dict.keys():
            if transfer[2] > 0 :
                tokens_dict[transfer[3]] = len(tokens_dict)
            else:
                zero_amount.append(idx)
                continue
        if transfer[0] not in nodes_dict.keys():
            nodes_dict[transfer[0]] = len(nodes_dict)
        if transfer[1] not in nodes_dict.keys():
            nodes_dict[transfer[1]] = len(nodes_dict)
            
        edge_start.append(nodes_dict[transfer[0]])
        edge_end.append(nodes_dict[transfer[1]])
        
    for k in sorted(zero_amount, reverse=True):
        del total_transfer[k]   

    features = [[] for x in range(len(nodes_dict))]
    profits = [[0 for y in range(len(tokens_dict))  ] for x in range(len(nodes_dict))]
    trade_bool_send = [[0 for y in range(len(tokens_dict))  ] for x in range(len(nodes_dict))]
    trade_bool_receive = [[0 for y in range(len(tokens_dict))  ] for x in range(len(nodes_dict))]

    trade_num_send = [[0 for y in range(len(tokens_dict))  ] for x in range(len(nodes_dict))]
    trade_num_receive = [[0 for y in range(len(tokens_dict))  ] for x in range(len(nodes_dict))]
    
    max_transfer = [0 for x in range(len(tokens_dict))]
    for transfer in total_transfer:
        profits[nodes_dict[transfer[0]]][tokens_dict[transfer[3]]] -= transfer[2]
        profits[nodes_dict[transfer[1]]][tokens_dict[transfer[3]]] += transfer[2]
        
        trade_num_send[nodes_dict[transfer[0]]][tokens_dict[transfer[3]]] += 1
        trade_num_receive[nodes_dict[transfer[0]]][tokens_dict[transfer[3]]] += 1
        
        trade_bool_send[nodes_dict[transfer[0]]][tokens_dict[transfer[3]]] = 1
        trade_bool_receive[nodes_dict[transfer[1]]][tokens_dict[transfer[3]]] = 1
        
        if transfer[2] > max_transfer[tokens_dict[transfer[3]]]:
            max_transfer[tokens_dict[transfer[3]]] = transfer[2]
        
    for addridx, addr in enumerate(profits):
        for idx,profit in enumerate(addr):
            if profit < 0:
                if -profit*10000 > max_transfer[idx]:
                    profits[addridx][idx] = -1
                else:
                    profits[addridx][idx] = 0
            elif profit == 0:
                profits[addridx][idx] = 0
            else:
                if profit*10000 < max_transfer[idx]:
                    profits[addridx][idx] = 0
                else:
                    profits[addridx][idx] = 1
        
        num_negative = profits[addridx].count(-1)
        num_positive = profits[addridx].count(1)
        
        trade_bool = [a or b for a, b in zip(trade_bool_send, trade_bool_receive)]
        num_zero = len(trade_bool[addridx]) - num_negative - num_positive
        
        features[addridx] = [num_negative, num_positive, num_zero] # 1st, 2nd, 3rd features

        # trade boolean
        features[addridx].append(sum(trade_bool_send[addridx])) # 4th feature : tokens sent from the address
        features[addridx].append(sum(trade_bool_receive[addridx])) # 5th
        
        features[addridx].append(len(tokens_dict)) # 6th feature : total count of tokens
        
        features[addridx] = features[addridx] + [1,1]         # 7th, 8th feature : NULL or not / Builder or not
        
    try:
        features[nodes_dict["0x0000000000000000000000000000000000000000"]][6] = 0 # 7th
    except:
        pass
    try:
        features[nodes_dict[builder]][7] = 0 # 8th
    except:
        pass
    
    
    for node,idx in nodes_dict.items():
        if w3.eth.getCode(w3.toChecksumAddress(node)).hex() == "0x":    # 9th
            features[idx].append(0)
        else:
            features[idx].append(1)    
        if node == from_addr:          # 10th
            features[idx].append(1)
        else:
            features[idx].append(0)    
        if node == to_addr:            # 11th
            features[idx].append(1)
        else:
            features[idx].append(0)
        
    for addridx, addr in enumerate(profits):
        features[addridx].append(sum(trade_num_send[addridx])) # 12th
        features[addridx].append(sum(trade_num_receive[addridx])) # 13th
        features[addridx].append(len(edge_start)) # 14th
            
    # Convert to tensor
    x = torch.tensor(features).float()

    # Edge index
    edge_index = torch.tensor([edge_start, edge_end]).to(torch.int)
    
    y          = torch.tensor([target])
    
    data = Data(x=x, edge_index=edge_index, y=y, tx = tx)
    return data

# Test single transaction
def test_single_tx(data, mod, debug=0):
    mod.eval()
    correct = 0
    out = mod(data.x, data.edge_index, data.edge_weight, None)
    pred = out.argmax(dim=1)

    if pred.item() == 1:
        return True

def detect_mev(block, model, debug=1):
    model.eval()
    if debug: print(f"""Inspecting Block #{blockNum}..🤔""")
    block = w3.eth.getBlock(blockNum)
    transactions = block['transactions']
    builder = block['miner'].lower()
    
    arbitrages = []
    for tx in transactions:
        tx = tx.hex()
        receipt = w3.eth.getTransactionReceipt(tx)
        total_transfer = get_total_transfer(tx, receipt)
        if not total_transfer:
            continue

        from_addr = receipt['from'].lower()
        try:
            to_addr = receipt['to'].lower()
        except:
            to_addr = None
        
        data = add_features(total_transfer, tx, from_addr, to_addr, blockNum, builder, 0)

        if not len(data.x):
            continue
            
        if test_single_tx(data, model):
            if debug : 
                print(tx, "Arbitrage Found")
            arbitrages.append(tx)

    return set(arbitrages), len(transactions)

if __name__ == "__main__":
    layer = "SAGE"

    model = GraphSAGE(14, hidden_channels=512)

    # Load pretrained model
    filename = f"pretrained_models/{layer}.pkl"
    model.load_state_dict(torch.load(filename))
    optimizer = torch.optim.Adam(model.parameters(), lr=0.0001, weight_decay=0)
    criterion = torch.nn.CrossEntropyLoss(torch.tensor([1, 1], dtype=torch.float))
    
    if len(sys.argv) == 2:
        blockNum = int(sys.argv[1])
        arbitrages, _ = detect_mev(blockNum, model, debug=1)

    if len(sys.argv) == 3:
        start = int(sys.argv[1])
        end   = int(sys.argv[2])

        for blockNum in range(start, end):
            arbitrages, _ = detect_mev(blockNum, model, debug=1)

